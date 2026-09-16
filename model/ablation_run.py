"""KAN-20 runner: detection and cost for every declared feature set.

`ablation_spec.json` is committed before the run and fixes the budget, the seeds, the
model settings, the compact-set rule and the timing sample. The run binds itself to
the development pack the spec names, trains and calibrates each set on each seed
(validation only), applies the rule, then prices every set on the cost seed. Each run
needs a new output directory. Nothing here writes a model artifact: a compact
finalist is a proposal for KAN-51, not an operating policy.

    python -m model.ablation_run --pack ~/omniguard-data/samplepack/windows.jsonl \\
        --captures ~/omniguard-data/iot23 --out ~/omniguard-data/runs/kan20
"""

import argparse
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path

from core.features import FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.ablation import FULL, candidate_sets, run_set, select_compact
from model.ablation_cost import capture_windows, model_size, time_extraction, time_inference
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.calibrate import OBJECTIVES
from model.policy_run import _SHA256
from model.split import split_by_group
from model.train import feature_matrix, window_groups

SPEC = Path(__file__).with_name("ablation_spec.json")
REPORT_FILENAME = "ablation_report.json"


class AblationSpecError(ValueError):
    """The ablation specification would allow choosing after seeing results."""


def _positive_int(value, name: str, *, allow_zero: bool = False) -> None:
    if type(value) is not int or value < (0 if allow_zero else 1):
        kind = "non-negative" if allow_zero else "positive"
        raise AblationSpecError(f"{name} must be a {kind} int")


def load_spec(path: Path = SPEC) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AblationSpecError(f"unreadable ablation spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise AblationSpecError("ablation spec must be a JSON object")
    budget = spec.get("max_window_fpr")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not 0 <= budget <= 1:
        raise AblationSpecError("max_window_fpr must be a number in [0, 1]")
    if spec.get("selected_on") != "validation":
        raise AblationSpecError("thresholds are selected on validation only")
    if spec.get("objective") not in OBJECTIVES:
        raise AblationSpecError(f"objective must be one of {OBJECTIVES}")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise AblationSpecError(f"spec must name the runtime catalogue {FEATURE_SCHEMA_VERSION}")
    if not _SHA256.fullmatch(str(spec.get("development_pack_windows_sha256"))):
        raise AblationSpecError("development_pack_windows_sha256 must be a SHA-256 hex digest")
    _positive_int(spec.get("n_estimators"), "n_estimators")
    _positive_int(spec.get("bootstrap"), "bootstrap", allow_zero=True)
    seeds = spec.get("seeds")
    if (
        not isinstance(seeds, list)
        or not seeds
        or any(type(s) is not int for s in seeds)
        or len(set(seeds)) != len(seeds)
    ):
        raise AblationSpecError("seeds must be a nonempty list of distinct ints")
    if type(spec.get("cost_seed")) is not int or spec["cost_seed"] not in seeds:
        raise AblationSpecError("cost_seed must be one of the seeds")
    rule = spec.get("compact_rule")
    tolerance = rule.get("tolerance") if isinstance(rule, dict) else None
    if isinstance(tolerance, bool) or not isinstance(tolerance, int | float):
        raise AblationSpecError("compact_rule.tolerance must be a number")
    if not 0 <= tolerance < 1:
        raise AblationSpecError("compact_rule.tolerance must be in [0, 1)")
    cost = spec.get("cost")
    if not isinstance(cost, dict) or not isinstance(cost.get("timing_captures"), list):
        raise AblationSpecError("cost.timing_captures must name the timing captures")
    for name in ("windows_per_capture", "extraction_repeats", "inference_rows"):
        _positive_int(cost.get(name), f"cost.{name}")
    reference = spec.get("kan19_reference_threshold")
    if reference is not None and (
        isinstance(reference, bool) or not isinstance(reference, int | float)
    ):
        raise AblationSpecError("kan19_reference_threshold must be a number or null")
    return spec


def _timing_sample(spec: dict, manifest_path: Path, captures: Path | None, train) -> dict:
    """Packet windows for timing, only from captures in the cost seed's train split."""
    names = spec["cost"]["timing_captures"]
    outside = sorted(set(names) - set(train))
    if outside:
        raise AblationSpecError(f"timing captures outside the cost seed's train split: {outside}")
    if captures is None:
        return {"status": "skipped", "reason": "no --captures directory given", "windows": []}
    document = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    described = {c["group_id"]: c for c in document["captures"]}
    windows, per_capture = [], {}
    for name in names:
        entry = described[name]
        pcap = Path(captures) / name / entry["pcap"]
        if _sha256(pcap) != entry["pcap_sha256"]:
            raise PackIntegrityError(f"{pcap} is not the capture the pack was built from")
        sample = capture_windows(
            pcap, entry["lan_cidrs"], entry["devices"], spec["cost"]["windows_per_capture"]
        )
        per_capture[name] = len(sample)
        windows += sample
    return {"status": "measured", "per_capture": per_capture, "windows": windows}


def run(
    pack: Path,
    out_dir: Path,
    spec_path: Path = SPEC,
    manifest: Path | None = None,
    captures: Path | None = None,
    *,
    log=print,
) -> dict:
    spec = load_spec(spec_path)
    spec_sha256 = _sha256(Path(spec_path))
    pack, out_dir = Path(pack), Path(out_dir)
    provenance = verify_pack(pack, manifest)
    if provenance.windows_sha256 != spec["development_pack_windows_sha256"]:
        raise PackIntegrityError(f"{pack.name} is not the development pack the spec names")
    windows = read_windows(pack)
    if _sha256(pack) != provenance.windows_sha256:
        raise PackIntegrityError(f"{pack.name} changed while it was being read")

    cost_seed = spec["cost_seed"]
    cost_split = split_by_group(window_groups(windows), seed=cost_seed)
    manifest_path = Path(manifest) if manifest else pack.with_name("manifest.json")
    # Refuse a bad timing spec before creating the run directory.
    timing = _timing_sample(spec, manifest_path, captures, cost_split.train)
    out_dir.mkdir(parents=True, exist_ok=False)

    sets = candidate_sets()
    results, cost_models = {}, {}
    for feature_set in sets:
        runs = []
        for seed in spec["seeds"]:
            result = run_set(
                windows,
                feature_set,
                seed=seed,
                max_window_fpr=spec["max_window_fpr"],
                objective=spec["objective"],
                n_estimators=spec["n_estimators"],
                bootstrap=spec["bootstrap"],
            )
            if seed == cost_seed:
                cost_models[feature_set.name] = result.model
            result.model = None  # only the cost seed's forests stay in memory
            runs.append(result)
            log(f"{feature_set.name:30} seed {seed} {result.status:12} recall={result.recall}")
        results[feature_set.name] = runs

    selection = select_compact(sets, results, tolerance=spec["compact_rule"]["tolerance"])
    reference = next(r for r in results[FULL] if r.seed == cost_seed)
    expected = spec.get("kan19_reference_threshold")
    reproduces = None
    if expected is not None and reference.policy is not None:
        reproduces = reference.policy["threshold"] == expected

    validation_groups = set(cost_split.validation)
    inference_windows = [w for w in windows if w.group_id in validation_groups]
    inference_windows = inference_windows[: spec["cost"]["inference_rows"]]
    costs = {}
    for feature_set in sets:
        model = cost_models.pop(feature_set.name)
        rows = feature_matrix(inference_windows, columns=feature_set.columns)
        entry = {"model": model_size(model), "inference": time_inference(model, rows)}
        if timing["windows"]:
            entry["extraction"] = time_extraction(
                timing["windows"], feature_set.columns, repeats=spec["cost"]["extraction_repeats"]
            )
        costs[feature_set.name] = entry

    import sklearn

    report = {
        "card": "KAN-20",
        "status": selection["status"],
        "spec": {"path": str(spec_path), "sha256": spec_sha256, **spec},
        "pack": {"path": str(pack), **asdict(provenance)},
        "evaluated_split": "validation",
        "environment": {
            "python": sys.version.split()[0],
            "sklearn": sklearn.__version__,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "full_set_reproduces_kan19_threshold": reproduces,
        "selection": selection,
        "timing_sample": {k: v for k, v in timing.items() if k != "windows"},
        "sets": [
            {
                "name": s.name,
                "role": s.role,
                "features": list(s.features),
                "groups": list(s.groups),
                "runs": [r.to_dict() for r in results[s.name]],
                "cost": costs[s.name],
            }
            for s in sets
        ],
    }
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def summary(report: dict) -> str:
    selection = report["selection"]
    lines = [
        f"selection: {selection['status']}  finalist: {selection['finalist']}",
        f"full set reproduces KAN-19 threshold: {report['full_set_reproduces_kan19_threshold']}",
    ]
    for entry in report["sets"]:
        recalls = "/".join(
            "-" if r["policy"] is None else f"{r['policy']['metrics']['recall']:.3f}"
            for r in entry["runs"]
        )
        cost = entry["cost"]
        extraction = cost.get("extraction", {}).get("ns_per_window_median")
        mark = "*" if entry["name"] == selection["finalist"] else " "
        lines.append(
            f"{mark}{entry['name']:30} n={len(entry['features']):2} recall={recalls} "
            f"extract_ns={extraction} infer_us={cost['inference']['us_median']} "
            f"nodes={cost['model']['tree_nodes']}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--captures", type=Path, help="IoT-23 directory for extraction timing")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC)
    args = parser.parse_args()
    report = run(args.pack, args.out, args.spec, args.manifest, args.captures)
    print(summary(report))
    raise SystemExit(0 if report["selection"]["status"] != "no_reference" else 1)


if __name__ == "__main__":
    main()
