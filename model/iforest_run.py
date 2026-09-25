"""KAN-22 runner: benign-only Isolation Forest against the Random Forest, offline.

`iforest_spec.json` is committed before any run and fixes the budget, seeds, model
sizes, what is reported and the hypothesis. For each seed both models see the same
KAN-17 split: the Random Forest trains on all train windows, the Isolation Forest only
on the train split's benign-device captures. Each model's threshold is selected on
validation under the KAN-19 budget and both are judged on validation. Test rows are
never scored.

KAN-22 waits for G8 and G10. The runner therefore refuses to start unless
`--approval` names the Lead's decision to run it early, and records that reference.

    python -m model.iforest_run --pack ~/omniguard-data/samplepack/windows.jsonl \\
        --out ~/omniguard-data/runs/kan22 --approval "<link to the Lead's decision>"
"""

import argparse
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path

from core.features import FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.calibrate import OBJECTIVES, CalibrationError, apply_frozen_policy, calibrate_threshold
from model.iforest import anomaly_scores, train_isolation_forest
from model.policy_run import _SHA256
from model.split import SPLITS, split_by_group
from model.train import rf_scores, train_random_forest, window_groups

SPEC = Path(__file__).with_name("iforest_spec.json")
REPORT_FILENAME = "iforest_report.json"


class IForestSpecError(ValueError):
    """The run would break the declared plan or its gate."""


def _positive_int(value, name: str, *, allow_zero: bool = False) -> None:
    if type(value) is not int or value < (0 if allow_zero else 1):
        kind = "non-negative" if allow_zero else "positive"
        raise IForestSpecError(f"{name} must be a {kind} int")


def load_spec(path: Path = SPEC) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IForestSpecError(f"unreadable Isolation Forest spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise IForestSpecError("Isolation Forest spec must be a JSON object")
    budget = spec.get("max_window_fpr")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not 0 <= budget <= 1:
        raise IForestSpecError("max_window_fpr must be a number in [0, 1]")
    if spec.get("selected_on") != "validation":
        raise IForestSpecError("thresholds are selected on validation only")
    if spec.get("objective") not in OBJECTIVES:
        raise IForestSpecError(f"objective must be one of {OBJECTIVES}")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise IForestSpecError(f"spec must name the runtime catalogue {FEATURE_SCHEMA_VERSION}")
    if not _SHA256.fullmatch(str(spec.get("development_pack_windows_sha256"))):
        raise IForestSpecError("development_pack_windows_sha256 must be a SHA-256 hex digest")
    _positive_int(spec.get("bootstrap"), "bootstrap", allow_zero=True)
    seeds = spec.get("seeds")
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(type(s) is not int for s in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise IForestSpecError("seeds must be a nonempty list of distinct ints")
    for block in ("iforest", "random_forest_reference"):
        if not isinstance(spec.get(block), dict):
            raise IForestSpecError(f"{block} must be an object")
        _positive_int(spec[block].get("n_estimators"), f"{block}.n_estimators")
    if not isinstance(spec.get("hypothesis"), str) or not spec["hypothesis"].strip():
        raise IForestSpecError("the hypothesis must be declared before the run")
    return spec


def _average_precision(labels, scores) -> float | None:
    if all(labels) or not any(labels):
        return None
    from sklearn.metrics import average_precision_score

    return float(average_precision_score([int(v) for v in labels], list(scores)))


def _judge(model_name, validation, scores, infected, spec, seed) -> dict:
    """Select on validation, then split the benign side by where it came from."""
    labels = [w.malicious for w in validation]
    groups = [w.group_id for w in validation]
    entry = {
        "model": model_name,
        "validation_average_precision": _average_precision(labels, scores),
    }
    try:
        policy = calibrate_threshold(
            labels,
            scores,
            groups,
            objective=spec["objective"],
            max_window_fpr=spec["max_window_fpr"],
            bootstrap=spec["bootstrap"],
            seed=seed,
        )
    except CalibrationError as exc:
        return entry | {"status": "no_threshold", "error": str(exc), "policy": None}

    # The validation FPR mixes a benign device's windows with benign windows from the
    # infected capture. Report the two apart; only the first is a benign-device FPR.
    benign = [(w, s) for w, s in zip(validation, scores, strict=True) if not w.malicious]
    by_source = {}
    for name, inside in (("benign_device", False), ("inside_infected_capture", True)):
        part = [(w, s) for w, s in benign if (w.group_id in infected) is inside]
        if not part:
            by_source[name] = None
            continue
        metrics = apply_frozen_policy(
            policy,
            [w.malicious for w, _ in part],
            [s for _, s in part],
            [w.group_id for w, _ in part],
            bootstrap=0,
        )
        by_source[name] = {"windows": metrics.windows, "fp": metrics.fp, "fpr": metrics.fpr}
    return entry | {
        "status": "calibrated",
        "error": None,
        "policy": json.loads(policy.to_json()),
        "validation_benign_fpr_by_source": by_source,
    }


def run(
    pack: Path,
    out_dir: Path,
    spec_path: Path = SPEC,
    manifest: Path | None = None,
    *,
    approval: str,
) -> dict:
    if not isinstance(approval, str) or not approval.strip():
        raise IForestSpecError(
            "KAN-22 waits for G8/G10: name the Lead's decision to run it early with --approval"
        )
    spec = load_spec(spec_path)
    spec_sha256 = _sha256(Path(spec_path))
    pack, out_dir = Path(pack), Path(out_dir)
    provenance = verify_pack(pack, manifest)
    if provenance.windows_sha256 != spec["development_pack_windows_sha256"]:
        raise PackIntegrityError(f"{pack.name} is not the development pack the spec names")
    windows = read_windows(pack)
    if _sha256(pack) != provenance.windows_sha256:
        raise PackIntegrityError(f"{pack.name} changed while it was being read")
    out_dir.mkdir(parents=True, exist_ok=False)

    infected = {g.group_id for g in window_groups(windows) if g.malicious_windows}
    seeds = []
    for seed in spec["seeds"]:
        split = split_by_group(window_groups(windows), seed=seed)
        membership = {g: name for name in SPLITS for g in getattr(split, name)}
        train = [w for w in windows if membership[w.group_id] == "train"]
        validation = [w for w in windows if membership[w.group_id] == "validation"]

        # Benign windows inside an infected capture are the infected device's own
        # traffic; a benign-only model must not learn them as normal.
        benign_devices = [w for w in train if w.group_id not in infected]
        iforest = train_isolation_forest(
            benign_devices, seed=seed, n_estimators=spec["iforest"]["n_estimators"]
        )
        forest = train_random_forest(
            train, seed=seed, n_estimators=spec["random_forest_reference"]["n_estimators"]
        )
        judged = [
            _judge(
                "isolation_forest",
                validation,
                anomaly_scores(iforest, validation),
                infected,
                spec,
                seed,
            ),
            _judge(
                "random_forest", validation, rf_scores(forest, validation), infected, spec, seed
            ),
        ]
        seeds.append(
            {
                "seed": seed,
                "split": {name: list(getattr(split, name)) for name in SPLITS},
                "iforest_trained_on": {
                    "groups": sorted({w.group_id for w in benign_devices}),
                    "windows": len(benign_devices),
                },
                "results": judged,
            }
        )

    import sklearn

    report = {
        "card": "KAN-22",
        "approval": approval.strip(),
        "spec": {"path": str(spec_path), "sha256": spec_sha256, **spec},
        "pack": {"path": str(pack), **asdict(provenance)},
        "evaluated_split": "validation",
        "environment": {
            "python": sys.version.split()[0],
            "sklearn": sklearn.__version__,
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "seeds": seeds,
    }
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def summary(report: dict) -> str:
    lines = [f"approval: {report['approval']}"]
    for entry in report["seeds"]:
        for result in entry["results"]:
            policy = result["policy"]
            if policy is None:
                outcome = "no threshold under the budget"
            else:
                m = policy["metrics"]
                outcome = f"threshold={policy['threshold']:.4f} recall={m['recall']:.3f}"
            ap = result["validation_average_precision"]
            lines.append(
                f"seed {entry['seed']} {result['model']:17} {outcome} "
                f"ap={'-' if ap is None else f'{ap:.4f}'}"
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument(
        "--approval", required=True, help="reference to the Lead's decision to run KAN-22 early"
    )
    args = parser.parse_args()
    report = run(args.pack, args.out, args.spec, args.manifest, approval=args.approval)
    print(summary(report))


if __name__ == "__main__":
    main()
