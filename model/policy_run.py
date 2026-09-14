"""KAN-19 operating threshold policy: selected on validation, frozen before any test.

`operating_policy_spec.json` fixes everything that could otherwise be tuned after seeing
a result, and is committed before the run: the Lead-approved window-FPR budget, the
objective, the model settings, the development pack, the one seed whose model is the
operating candidate, and the seeds reported only for sensitivity. The run then:

1. binds itself to the development pack the spec names (hash-checked);
2. for each seed, trains on the KAN-17 train split and calibrates on validation only;
3. for the operating seed alone, writes the KAN-9 artifact with the selected threshold,
   `threshold.policy.json` and a provenance record that binds the pack, spec, split,
   model, metadata and policy hashes.

The development test split and the ADR-0004 holdout are never read. When no threshold
meets the budget the run records that and writes no artifact; the budget is not relaxed.
Sensitivity seeds never produce an artifact, so a better-looking seed cannot replace the
declared one.
"""

import argparse
import json
import re
from dataclasses import asdict
from pathlib import Path

from core.features import FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.artifact import META_FILENAME
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.calibrate import OBJECTIVES, CalibrationError, calibrate_threshold, write_policy
from model.train import rf_scores, run_baseline, save_artifact

SPEC = Path(__file__).with_name("operating_policy_spec.json")
REPORT_FILENAME = "policy_report.json"
PROVENANCE_FILENAME = "provenance.json"
OPERATING_DIR = "operating"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PolicySpecError(ValueError):
    """The run specification would allow tuning after seeing results."""


def _positive_int(spec: dict, name: str, *, allow_zero: bool = False) -> None:
    value = spec.get(name)
    if type(value) is not int or value < (0 if allow_zero else 1):
        raise PolicySpecError(
            f"{name} must be a {'non-negative' if allow_zero else 'positive'} int"
        )


def load_spec(path: Path = SPEC) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PolicySpecError(f"unreadable policy spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise PolicySpecError("policy spec must be a JSON object")
    budget = spec.get("max_window_fpr")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not 0 <= budget <= 1:
        raise PolicySpecError("max_window_fpr must be a number in [0, 1]")
    if spec.get("selected_on") != "validation":
        raise PolicySpecError("thresholds are selected on validation only")
    if spec.get("objective") not in OBJECTIVES:
        raise PolicySpecError(f"objective must be one of {OBJECTIVES}")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise PolicySpecError(f"spec must name the runtime catalogue {FEATURE_SCHEMA_VERSION}")
    if not _SHA256.fullmatch(str(spec.get("development_pack_windows_sha256"))):
        raise PolicySpecError("development_pack_windows_sha256 must be a SHA-256 hex digest")
    _positive_int(spec, "n_estimators")
    _positive_int(spec, "bootstrap", allow_zero=True)
    seed, others = spec.get("operating_seed"), spec.get("sensitivity_seeds")
    if (
        type(seed) is not int
        or not isinstance(others, list)
        or any(type(s) is not int for s in others)
        or len(set(others)) != len(others)
        or seed in others
    ):
        raise PolicySpecError("operating_seed must be one int, distinct from the sensitivity seeds")
    return spec


def run(pack: Path, out_dir: Path, spec_path: Path = SPEC, manifest: Path | None = None) -> dict:
    spec = load_spec(spec_path)
    spec_sha256 = _sha256(Path(spec_path))
    pack, out_dir = Path(pack), Path(out_dir)
    provenance = verify_pack(pack, manifest)
    if provenance.windows_sha256 != spec["development_pack_windows_sha256"]:
        raise PackIntegrityError(f"{pack.name} is not the development pack the spec names")
    windows = read_windows(pack)
    if _sha256(pack) != provenance.windows_sha256:
        raise PackIntegrityError(f"{pack.name} changed while it was being read")

    runs, operating = [], None
    for seed in (spec["operating_seed"], *spec["sensitivity_seeds"]):
        role = "operating" if seed == spec["operating_seed"] else "sensitivity"
        report = run_baseline(
            windows, seed=seed, bootstrap=spec["bootstrap"], n_estimators=spec["n_estimators"]
        )
        validation_groups = set(report.manifest.validation)
        validation = [w for w in windows if w.group_id in validation_groups]
        entry = {
            "seed": seed,
            "role": role,
            "split": {
                name: list(getattr(report.manifest, name))
                for name in ("train", "validation", "test")
            },
            "training_manifest_sha256": report.manifest.sha256(),
            "reference_at_0_5": asdict(report.rf),
        }
        try:
            policy = calibrate_threshold(
                [w.malicious for w in validation],
                rf_scores(report.model, validation),
                [w.group_id for w in validation],
                objective=spec["objective"],
                max_window_fpr=spec["max_window_fpr"],
                bootstrap=spec["bootstrap"],
                seed=seed,
            )
        except CalibrationError as exc:
            entry |= {"status": "no_threshold", "error": str(exc), "policy": None}
            runs.append(entry)
            continue
        entry |= {
            "status": "calibrated",
            "error": None,
            "policy": json.loads(policy.to_json()),
            "policy_sha256": policy.sha256(),
        }
        if role == "operating":
            artifact_dir = out_dir / OPERATING_DIR
            meta = save_artifact(
                report.model,
                artifact_dir,
                model_id="rf-iot23",
                model_version=f"0.1.0-seed{seed}-kan19",
                threshold=policy.threshold,
                manifest=report.manifest,
            )
            policy_path = write_policy(policy, artifact_dir)
            operating = asdict(provenance) | {
                "spec_sha256": spec_sha256,
                "seed": seed,
                "threshold": policy.threshold,
                "max_window_fpr": spec["max_window_fpr"],
                "training_manifest_sha256": meta.training_manifest_sha256,
                "model_sha256": meta.model_sha256,
                "metadata_sha256": _sha256(artifact_dir / META_FILENAME),
                "threshold_policy_sha256": _sha256(policy_path),
            }
            (artifact_dir / PROVENANCE_FILENAME).write_text(
                json.dumps(operating, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        runs.append(entry)

    result = {
        "card": "KAN-19",
        "status": "operating_policy_frozen" if operating else "no_operating_policy",
        "spec": {"path": str(spec_path), "sha256": spec_sha256, **spec},
        "pack": {"path": str(pack), **asdict(provenance)},
        "evaluated_split": "validation",
        "operating": operating,
        "runs": runs,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC)
    args = parser.parse_args()
    result = run(args.pack, args.out, args.spec, args.manifest)
    print(f"status: {result['status']}  (spec {result['spec']['sha256']})")
    for entry in result["runs"]:
        line = f"seed {entry['seed']} {entry['role']:11} val={entry['split']['validation']}"
        if entry["policy"] is None:
            print(f"{line}\n  no threshold: {entry['error']}")
            continue
        m = entry["policy"]["metrics"]
        print(
            f"{line}\n  threshold={entry['policy']['threshold']} recall={m['recall']} "
            f"fpr={m['fpr']} precision={m['precision']}"
        )
    if result["operating"]:
        print(json.dumps(result["operating"], indent=2, sort_keys=True))
    raise SystemExit(0 if result["operating"] else 1)


if __name__ == "__main__":
    main()
