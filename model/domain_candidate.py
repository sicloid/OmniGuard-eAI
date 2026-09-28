"""Train CIC-benign-augmented candidates without touching protected holdouts."""

import argparse
import hashlib
import json
import platform
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier

from data.samplepack.build import read_windows
from model.baseline_run import verify_pack
from model.split import split_by_group
from model.train import feature_matrix, window_groups


def threshold_at_source_budgets(
    labels: np.ndarray,
    scores: np.ndarray,
    source: np.ndarray,
    budgets: dict[str, float],
) -> float | None:
    """Maximize recall while every named benign source stays in its FPR budget."""
    labels = np.asarray(labels, dtype=bool)
    scores = np.asarray(scores, dtype=float)
    source = np.asarray(source, dtype=str)
    if not (len(labels) == len(scores) == len(source)) or not len(labels):
        raise ValueError("paired nonempty labels, scores and sources required")
    if not np.all(np.isfinite(scores)) or np.any((scores < 0) | (scores > 1)):
        raise ValueError("scores must be finite in [0, 1]")
    if not labels.any():
        raise ValueError("at least one malicious validation window is required")
    if not budgets or any(not 0 <= budget <= 1 for budget in budgets.values()):
        raise ValueError("source FPR budgets must be in [0, 1]")
    for name in budgets:
        if not np.any((source == name) & ~labels):
            raise ValueError(f"{name}: no benign validation windows")

    order = np.argsort(-scores, kind="stable")
    ordered = scores[order]
    ends = np.r_[np.flatnonzero(ordered[:-1] != ordered[1:]), len(ordered) - 1]
    cumulative_tp = np.cumsum(labels[order])[ends]
    eligible = np.ones(len(ends), dtype=bool)
    for name, budget in budgets.items():
        negatives = (source == name) & ~labels
        cumulative_fp = np.cumsum(negatives[order])[ends]
        eligible &= cumulative_fp / negatives.sum() <= budget
    choices = np.flatnonzero(eligible)
    if not len(choices):
        return None
    best = max(choices, key=lambda index: (int(cumulative_tp[index]), ordered[ends[index]]))
    return float(ordered[ends[best]])


def _model(config: dict, seed: int):
    common = {
        "n_estimators": config["n_estimators"],
        "max_depth": config["max_depth"],
        "min_samples_leaf": config["min_samples_leaf"],
        "class_weight": "balanced",
        "random_state": seed,
        "n_jobs": 1,
    }
    if config["kind"] == "extra_trees":
        return ExtraTreesClassifier(**common)
    if config["kind"] == "random_forest":
        return RandomForestClassifier(**common)
    raise ValueError(f"unknown candidate kind: {config['kind']}")


def run(iot_pack: Path, ciciot_pack: Path, spec_path: Path, output: Path) -> dict:
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    iot_provenance = verify_pack(iot_pack)
    cic_provenance = verify_pack(ciciot_pack)
    if iot_provenance.windows_sha256 != spec["iot23_pack"]["windows_sha256"]:
        raise ValueError("IoT-23 pack drift")
    if cic_provenance.windows_sha256 != spec["ciciot_pack"]["windows_sha256"]:
        raise ValueError("CICIoT2023 pack drift")
    output.mkdir(parents=True, exist_ok=False)
    (output / "spec.json").write_bytes(spec_bytes)

    iot = read_windows(iot_pack)
    cic = read_windows(ciciot_pack)
    cic_train_groups = set(spec["ciciot_split"]["train"])
    cic_validation_groups = set(spec["ciciot_split"]["validation"])
    forbidden = set(spec["ciciot_split"]["forbidden_holdout"])
    actual_cic_groups = {window.group_id for window in cic}
    if (
        cic_train_groups & cic_validation_groups
        or (cic_train_groups | cic_validation_groups) & forbidden
    ):
        raise ValueError("CIC domain split overlaps a forbidden role")
    if cic_train_groups | cic_validation_groups | forbidden != actual_cic_groups:
        raise ValueError("CIC domain split does not cover the frozen pack exactly")
    cic_train = [window for window in cic if window.group_id in cic_train_groups]
    cic_validation = [window for window in cic if window.group_id in cic_validation_groups]
    if any(window.malicious for window in cic_train + cic_validation):
        raise ValueError("CIC augmentation roles must be benign-only")

    budgets = spec["max_window_fpr_by_source"]
    results = []
    for seed in spec["seeds"]:
        split = split_by_group(window_groups(iot), seed=seed)
        iot_train = [window for window in iot if window.group_id in split.train]
        iot_validation = [window for window in iot if window.group_id in split.validation]
        train = iot_train + cic_train
        x = feature_matrix(train)
        y = np.asarray([window.malicious for window in train], dtype=bool)
        validation = iot_validation + cic_validation
        vx = feature_matrix(validation)
        vy = np.asarray([window.malicious for window in validation], dtype=bool)
        source = np.asarray(
            [
                "iot23_validation_benign"
                if index < len(iot_validation) and not window.malicious
                else "iot23_validation_malicious"
                if index < len(iot_validation)
                else "ciciot_domain_validation"
                for index, window in enumerate(validation)
            ]
        )
        for name, config in spec["candidates"].items():
            candidate = _model(config, seed)
            start = perf_counter()
            candidate.fit(x, y)
            fit_seconds = perf_counter() - start
            scores = candidate.predict_proba(vx)[:, 1]
            threshold = threshold_at_source_budgets(vy, scores, source, budgets)
            row = {
                "candidate": name,
                "seed": seed,
                "iot23_split": asdict(split),
                "ciciot_train_devices": len(cic_train_groups),
                "ciciot_validation_devices": len(cic_validation_groups),
                "train_windows": len(train),
                "validation_windows": len(validation),
                "fit_seconds": fit_seconds,
                "threshold": threshold,
                "status": "no_threshold" if threshold is None else "evaluated",
            }
            if threshold is not None:
                predicted = scores >= threshold
                malicious = vy
                iot_benign = (source == "iot23_validation_benign") & ~vy
                cic_benign = (source == "ciciot_domain_validation") & ~vy
                row.update(
                    recall=float(predicted[malicious].mean()),
                    iot23_benign_fpr=float(predicted[iot_benign].mean()),
                    ciciot_domain_fpr=float(predicted[cic_benign].mean()),
                    iot23_malicious_windows=int(malicious.sum()),
                    iot23_benign_windows=int(iot_benign.sum()),
                    ciciot_domain_windows=int(cic_benign.sum()),
                )
            artifact = output / f"{name}-seed{seed}.joblib"
            joblib.dump(candidate, artifact)
            row["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            row["artifact_bytes"] = artifact.stat().st_size
            results.append(row)
            print(
                json.dumps(
                    {key: value for key, value in row.items() if key != "iot23_split"},
                    sort_keys=True,
                ),
                flush=True,
            )

    ranking = []
    for name in spec["candidates"]:
        rows = [row for row in results if row["candidate"] == name]
        if all(row["status"] == "evaluated" for row in rows):
            ranking.append(
                {
                    "candidate": name,
                    "worst_seed_recall": min(row["recall"] for row in rows),
                    "mean_recall": float(np.mean([row["recall"] for row in rows])),
                    "worst_seed_ciciot_domain_fpr": max(row["ciciot_domain_fpr"] for row in rows),
                }
            )
    ranking.sort(
        key=lambda row: (
            -row["worst_seed_recall"],
            -row["mean_recall"],
            row["worst_seed_ciciot_domain_fpr"],
        )
    )
    report = {
        "scope": spec["purpose"],
        "spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
        "iot23_pack": asdict(iot_provenance),
        "ciciot_pack": asdict(cic_provenance),
        "python": platform.python_version(),
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "results": results,
        "ranking": ranking,
        "runtime_adopted": False,
        "protected_roles_scored": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iot23-pack", type=Path, required=True)
    parser.add_argument("--ciciot-pack", type=Path, required=True)
    parser.add_argument(
        "--spec", type=Path, default=Path(__file__).with_name("domain_candidate_spec.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.iot23_pack, args.ciciot_pack, args.spec, args.output)


if __name__ == "__main__":
    main()
