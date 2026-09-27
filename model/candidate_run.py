"""Exploratory train/validation model comparison; no test or holdout scoring."""

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
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier

from data.samplepack.build import read_windows
from model.baseline_run import verify_pack
from model.split import split_by_group
from model.train import feature_matrix, train_random_forest, window_groups


def threshold_at_budget(labels, scores, budget):
    """Select maximum recall at an inclusive score threshold; ties stay together."""
    labels, scores = np.asarray(labels, dtype=bool), np.asarray(scores, dtype=float)
    if len(labels) != len(scores) or not len(labels):
        raise ValueError("paired nonempty labels and scores required")
    if not np.all(np.isfinite(scores)) or np.any((scores < 0) | (scores > 1)):
        raise ValueError("scores must be finite in [0, 1]")
    if not 0 <= budget <= 1 or labels.all() or not labels.any():
        raise ValueError("two classes and a valid FPR budget required")
    order = np.argsort(-scores, kind="stable")
    ordered = scores[order]
    ends = np.r_[np.flatnonzero(ordered[:-1] != ordered[1:]), len(ordered) - 1]
    tp = np.cumsum(labels[order])[ends]
    fp = np.cumsum(~labels[order])[ends]
    eligible = np.flatnonzero(fp / (~labels).sum() <= budget)
    if not len(eligible):
        return None
    best = max(eligible, key=lambda j: (int(tp[j]), float(ordered[ends[j]])))
    return float(ordered[ends[best]])


def run(pack, out, spec_path):
    spec_bytes = spec_path.read_bytes()
    spec = json.loads(spec_bytes)
    provenance = verify_pack(pack)
    if provenance.windows_sha256 != spec["windows_sha256"]:
        raise ValueError("development pack hash mismatch")
    out.mkdir(parents=True, exist_ok=False)
    (out / "spec.json").write_bytes(spec_bytes)
    windows = read_windows(pack)
    groups = window_groups(windows)
    results = []
    for seed in spec["seeds"]:
        split = split_by_group(groups, seed=seed)
        train = [w for w in windows if w.group_id in split.train]
        validation = [w for w in windows if w.group_id in split.validation]
        x, y = feature_matrix(train), [int(w.malicious) for w in train]
        vx = feature_matrix(validation)
        vy = np.array([w.malicious for w in validation])
        for name in spec["candidates"]:
            start = perf_counter()
            if name == "rf200_reference":
                model = train_random_forest(train, seed=seed)
            elif name == "rf64_regularized":
                model = train_random_forest(
                    train, seed=seed, n_estimators=64, max_depth=10, min_samples_leaf=20
                )
            elif name == "extra128_regularized":
                model = ExtraTreesClassifier(
                    n_estimators=128,
                    max_depth=12,
                    min_samples_leaf=10,
                    class_weight="balanced",
                    random_state=seed,
                    n_jobs=1,
                ).fit(x, y)
            elif name == "hist100_regularized":
                model = HistGradientBoostingClassifier(
                    max_iter=100,
                    max_leaf_nodes=15,
                    min_samples_leaf=30,
                    l2_regularization=10,
                    early_stopping=False,
                    class_weight="balanced",
                    random_state=seed,
                ).fit(x, y)
            else:
                raise ValueError(f"unknown candidate {name}")
            fit_seconds = perf_counter() - start
            scores = model.predict_proba(vx)[:, 1]
            threshold = threshold_at_budget(vy, scores, spec["max_window_fpr"])
            row = {
                "candidate": name,
                "seed": seed,
                "split": asdict(split),
                "threshold": threshold,
                "fit_seconds": fit_seconds,
                "status": "no_threshold" if threshold is None else "evaluated",
                "per_capture": [],
            }
            if threshold is not None:
                predicted = scores >= threshold
                row.update(recall=float(predicted[vy].mean()), fpr=float(predicted[~vy].mean()))
                for group in split.validation:
                    mask = np.array([w.group_id == group for w in validation])
                    negatives, positives = mask & ~vy, mask & vy
                    row["per_capture"].append(
                        {
                            "group": group,
                            "windows": int(mask.sum()),
                            "fpr": float(predicted[negatives].mean()) if negatives.any() else None,
                            "recall": float(predicted[positives].mean())
                            if positives.any()
                            else None,
                        }
                    )
            artifact = out / f"{name}-seed{seed}.joblib"
            joblib.dump(model, artifact)
            row["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
            row["artifact_bytes"] = artifact.stat().st_size
            results.append(row)
            print(
                json.dumps({k: v for k, v in row.items() if k not in ("split", "per_capture")}),
                flush=True,
            )
    ranking = []
    for name in spec["candidates"]:
        rows = [r for r in results if r["candidate"] == name]
        if all(r["status"] == "evaluated" for r in rows):
            ranking.append(
                {
                    "candidate": name,
                    "worst_seed_recall": min(r["recall"] for r in rows),
                    "mean_recall": float(np.mean([r["recall"] for r in rows])),
                }
            )
    ranking.sort(key=lambda r: (-r["worst_seed_recall"], -r["mean_recall"]))
    report = {
        "scope": spec["purpose"],
        "spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
        "pack": asdict(provenance),
        "python": platform.python_version(),
        "sklearn": sklearn.__version__,
        "numpy": np.__version__,
        "results": results,
        "ranking": ranking,
        "runtime_adopted": False,
        "independent_test_performed": False,
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--spec", type=Path, default=Path(__file__).with_name("candidate_spec.json")
    )
    args = parser.parse_args()
    run(args.pack, args.out, args.spec)
