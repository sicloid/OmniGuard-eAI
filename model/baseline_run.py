"""KAN-18 baseline run on a real sample pack.

Trains on the train split only and reports validation metrics; the test split is
never read here. With six capture groups a split leaves one capture per class in
each part, so every run is reported per seed: which captures landed where matters
more than any single number, and the report says so.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from data.samplepack.build import read_windows
from model.train import run_baseline, save_artifact


def _metrics(metrics) -> dict:
    return asdict(metrics)


def run(pack: Path, out_dir: Path, seeds: list[int], bootstrap: int, trees: int) -> dict:
    windows = read_windows(pack)
    runs = []
    for seed in seeds:
        report = run_baseline(windows, seed=seed, bootstrap=bootstrap, n_estimators=trees)
        artifact_dir = out_dir / f"seed-{seed}"
        meta = save_artifact(
            report.model,
            artifact_dir,
            model_id="rf-iot23",
            model_version=f"0.1.0-seed{seed}",
            threshold=0.5,
            manifest=report.manifest,
        )
        runs.append(
            {
                "seed": seed,
                "split": {
                    "train": list(report.manifest.train),
                    "validation": list(report.manifest.validation),
                    "test": list(report.manifest.test),
                },
                "counts": report.manifest.counts,
                "trained_windows": report.trained_windows,
                "rf": _metrics(report.rf),
                "rate_rule": _metrics(report.rate_rule),
                "rule": {"feature": report.rule.feature, "threshold": report.rule.threshold},
                "artifact": {
                    "dir": str(artifact_dir),
                    "model_sha256": meta.model_sha256,
                    "training_manifest_sha256": meta.training_manifest_sha256,
                },
            }
        )
    result = {
        "pack": str(pack),
        "windows": len(windows),
        "malicious_windows": sum(w.malicious for w in windows),
        "benign_windows": sum(not w.malicious for w in windows),
        "groups": sorted({w.group_id for w in windows}),
        "evaluated_split": "validation",
        "n_estimators": trees,
        "bootstrap": bootstrap,
        "runs": runs,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baseline_report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--trees", type=int, default=200)
    args = parser.parse_args()
    result = run(
        args.pack,
        args.out,
        [int(s) for s in args.seeds.split(",")],
        args.bootstrap,
        args.trees,
    )
    for entry in result["runs"]:
        rf, rule = entry["rf"], entry["rate_rule"]
        print(f"\n=== seed {entry['seed']}")
        print("  train:", entry["split"]["train"])
        print("  validation:", entry["split"]["validation"])
        print(f"  windows train/val: {entry['trained_windows']} / {rf['windows']}")
        for name, m in (("RF        ", rf), ("rate rule ", rule)):
            print(
                f"  {name} P={m['precision']} R={m['recall']} F1={m['f1']} FPR={m['fpr']}"
                f" recallCI={m['recall_ci']} fprCI={m['fpr_ci']}"
            )


if __name__ == "__main__":
    main()
