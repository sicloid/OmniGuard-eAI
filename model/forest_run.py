"""KAN-20 follow-up: forest size against detection and inference cost.

The feature ablation showed that a single-window `predict_proba` costs about a thousand
times more than extracting the features, and that the cost does not move with the
feature count. This sweep asks the question that follows: does a smaller forest keep
detection at the KAN-19 budget while cutting that cost?

`forest_spec.json` is committed before the run. Every size uses the full `features-1`
catalogue, trains on train, and is calibrated and judged on validation only, exactly as
in `model.ablation`. The smallest size that stays within the declared tolerance of the
reference forest on every seed is reported. It is a proposal for KAN-51, not an
operating policy, and nothing here writes a model artifact.

    python -m model.forest_run --pack ~/omniguard-data/samplepack/windows.jsonl \\
        --out ~/omniguard-data/runs/kan20-forest
"""

import argparse
import json
import platform
import statistics
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter_ns

from core.features import FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.ablation import FULL, candidate_sets, run_set
from model.ablation_cost import model_size, time_inference
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.calibrate import OBJECTIVES
from model.policy_run import _SHA256
from model.split import split_by_group
from model.train import feature_matrix, window_groups

SPEC = Path(__file__).with_name("forest_spec.json")
REPORT_FILENAME = "forest_report.json"


class ForestSpecError(ValueError):
    """The sweep specification would allow choosing after seeing results."""


def _positive_int(value, name: str, *, allow_zero: bool = False) -> None:
    if type(value) is not int or value < (0 if allow_zero else 1):
        kind = "non-negative" if allow_zero else "positive"
        raise ForestSpecError(f"{name} must be a {kind} int")


def _int_list(value, name: str) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(type(v) is not int for v in value)
        or len(set(value)) != len(value)
    ):
        raise ForestSpecError(f"{name} must be a nonempty list of distinct ints")


def load_spec(path: Path = SPEC) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ForestSpecError(f"unreadable forest spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise ForestSpecError("forest spec must be a JSON object")
    budget = spec.get("max_window_fpr")
    if isinstance(budget, bool) or not isinstance(budget, int | float) or not 0 <= budget <= 1:
        raise ForestSpecError("max_window_fpr must be a number in [0, 1]")
    if spec.get("selected_on") != "validation":
        raise ForestSpecError("thresholds are selected on validation only")
    if spec.get("objective") not in OBJECTIVES:
        raise ForestSpecError(f"objective must be one of {OBJECTIVES}")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ForestSpecError(f"spec must name the runtime catalogue {FEATURE_SCHEMA_VERSION}")
    if not _SHA256.fullmatch(str(spec.get("development_pack_windows_sha256"))):
        raise ForestSpecError("development_pack_windows_sha256 must be a SHA-256 hex digest")
    _positive_int(spec.get("bootstrap"), "bootstrap", allow_zero=True)
    counts = spec.get("tree_counts")
    _int_list(counts, "tree_counts")
    if counts != sorted(counts) or counts[0] < 1:
        raise ForestSpecError("tree_counts must be positive and ascending")
    if type(spec.get("reference_trees")) is not int or spec["reference_trees"] not in counts:
        raise ForestSpecError("reference_trees must be one of tree_counts")
    _int_list(spec.get("seeds"), "seeds")
    if type(spec.get("cost_seed")) is not int or spec["cost_seed"] not in spec["seeds"]:
        raise ForestSpecError("cost_seed must be one of the seeds")
    rule = spec.get("smallest_rule")
    tolerance = rule.get("tolerance") if isinstance(rule, dict) else None
    if isinstance(tolerance, bool) or not isinstance(tolerance, int | float):
        raise ForestSpecError("smallest_rule.tolerance must be a number")
    if not 0 <= tolerance < 1:
        raise ForestSpecError("smallest_rule.tolerance must be in [0, 1)")
    cost = spec.get("cost")
    if not isinstance(cost, dict):
        raise ForestSpecError("cost must be an object")
    for name in ("inference_rows", "batch_rows", "batch_repeats"):
        _positive_int(cost.get(name), f"cost.{name}")
    reference = spec.get("kan19_reference_threshold")
    if reference is not None and (
        isinstance(reference, bool) or not isinstance(reference, int | float)
    ):
        raise ForestSpecError("kan19_reference_threshold must be a number or null")
    return spec


def select_smallest(results: dict, reference_trees: int, tolerance: float) -> dict:
    """Smallest forest within `tolerance` of the reference on every seed, or none.

    The reference always qualifies against itself, so a calibrated reference always
    yields an answer; the question is only whether a smaller forest also does.
    """
    reference = results[reference_trees]
    if any(r.status != "calibrated" for r in reference):
        return {"status": "no_reference", "smallest": None, "verdicts": {}}
    floor = {r.seed: r.recall - tolerance for r in reference}
    verdicts, qualified = {}, []
    for trees, runs in sorted(results.items()):
        if {r.seed for r in runs} != set(floor):
            raise ForestSpecError(f"{trees} trees were not run on the reference seeds")
        failed = [r.seed for r in runs if r.status != "calibrated"]
        short = [r.seed for r in runs if r.status == "calibrated" and r.recall < floor[r.seed]]
        ok = not failed and not short
        verdicts[str(trees)] = {
            "qualifies": ok,
            "no_threshold_seeds": failed,
            "below_tolerance_seeds": short,
        }
        if ok:
            qualified.append(trees)
    return {"status": "selected", "smallest": min(qualified), "verdicts": verdicts}


def time_batch(model, rows, *, repeats: int) -> dict:
    """Per-window cost when one call scores a whole batch, as a per-tick detector could."""
    if not rows:
        raise ValueError("no rows to time")
    samples = []
    for _ in range(repeats):
        started = perf_counter_ns()
        model.predict_proba(rows)
        samples.append((perf_counter_ns() - started) / len(rows))
    return {
        "batch_rows": len(rows),
        "repeats": repeats,
        "us_per_window_median": round(statistics.median(samples) / 1000, 2),
    }


def run(pack: Path, out_dir: Path, spec_path: Path = SPEC, manifest=None, *, log=print) -> dict:
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

    full = next(s for s in candidate_sets() if s.name == FULL)
    cost_seed = spec["cost_seed"]
    results, models = {}, {}
    for trees in spec["tree_counts"]:
        runs = []
        for seed in spec["seeds"]:
            result = run_set(
                windows,
                full,
                seed=seed,
                max_window_fpr=spec["max_window_fpr"],
                objective=spec["objective"],
                n_estimators=trees,
                bootstrap=spec["bootstrap"],
            )
            if seed == cost_seed:
                models[trees] = result.model
            result.model = None
            runs.append(result)
            log(f"trees={trees:4} seed {seed} {result.status:12} recall={result.recall}")
        results[trees] = runs

    selection = select_smallest(
        results, spec["reference_trees"], spec["smallest_rule"]["tolerance"]
    )
    reference = next(r for r in results[spec["reference_trees"]] if r.seed == cost_seed)
    expected = spec.get("kan19_reference_threshold")
    reproduces = None
    if expected is not None and reference.policy is not None:
        reproduces = reference.policy["threshold"] == expected

    validation_groups = set(split_by_group(window_groups(windows), seed=cost_seed).validation)
    rows = feature_matrix([w for w in windows if w.group_id in validation_groups])
    cost = spec["cost"]
    costs = {}
    for trees in spec["tree_counts"]:
        model = models.pop(trees)
        costs[trees] = {
            "model": model_size(model),
            "inference": time_inference(model, rows[: cost["inference_rows"]]),
            "batched": time_batch(model, rows[: cost["batch_rows"]], repeats=cost["batch_repeats"]),
        }

    import sklearn

    report = {
        "card": "KAN-20",
        "experiment": "forest-size sweep",
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
        "reference_reproduces_kan19_threshold": reproduces,
        "selection": selection,
        "forests": [
            {
                "trees": trees,
                "runs": [r.to_dict() for r in results[trees]],
                "cost": costs[trees],
            }
            for trees in spec["tree_counts"]
        ],
    }
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def summary(report: dict) -> str:
    selection = report["selection"]
    lines = [
        f"selection: {selection['status']}  smallest: {selection['smallest']}",
        f"reference reproduces KAN-19 threshold: {report['reference_reproduces_kan19_threshold']}",
    ]
    for entry in report["forests"]:
        recalls = "/".join(
            "-" if r["policy"] is None else f"{r['policy']['metrics']['recall']:.3f}"
            for r in entry["runs"]
        )
        aps = "/".join(
            "-"
            if r["validation_average_precision"] is None
            else f"{r['validation_average_precision']:.4f}"
            for r in entry["runs"]
        )
        cost = entry["cost"]
        lines.append(
            f"trees={entry['trees']:4} recall={recalls} ap={aps} "
            f"single_ms={cost['inference']['us_median'] / 1000:.2f} "
            f"batched_us={cost['batched']['us_per_window_median']} "
            f"nodes={cost['model']['tree_nodes']} bytes={cost['model']['joblib_bytes']}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC)
    args = parser.parse_args()
    report = run(args.pack, args.out, args.spec, args.manifest)
    print(summary(report))
    raise SystemExit(0 if report["status"] == "selected" else 1)


if __name__ == "__main__":
    main()
