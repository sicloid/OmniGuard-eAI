"""KAN-21 unseen-family holdout on a real sample pack.

Runs every leave-one-family-out fold from `model.holdout` on a verified pack and
writes `holdout_report.json`. This result is separate from the KAN-18 baseline: the
held-out family is never trained or validated on, and each fold's threshold is
frozen on validation before its test windows are scored.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from data.samplepack.build import read_windows
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.holdout import METHOD, REFERENCE_THRESHOLD, folds_sha256, plan_folds, run_fold
from model.train import window_groups

REPORT_FILENAME = "holdout_report.json"

# Malware family per IoT-23 scenario, from the Stratosphere IoT-23 scenario table
# (https://www.stratosphereips.org/datasets-iot23, accessed 2026-09-14).
IOT23_FAMILIES = {
    "CTU-IoT-Malware-Capture-3-1": "Muhstik",
    "CTU-IoT-Malware-Capture-8-1": "Hakai",
    "CTU-IoT-Malware-Capture-34-1": "Mirai",
}


def _range(values) -> dict | None:
    present = [v for v in values if v is not None]
    return {"min": min(present), "max": max(present), "n": len(present)} if present else None


def _summary(results) -> dict:
    out = {}
    for family in sorted({r.fold.held_out_family for r in results}):
        mine = [r for r in results if r.fold.held_out_family == family]
        calibrated = [r for r in mine if r.policy is not None]
        out[family] = {
            "folds": len(mine),
            "no_threshold": len(mine) - len(calibrated),
            "recall": _range(r.held_out_family.recall for r in calibrated),
            "unseen_benign_fpr": _range(r.unseen_benign.fpr for r in calibrated),
            "reference_recall": _range(r.reference_held_out_family.recall for r in mine),
            "reference_unseen_benign_fpr": _range(r.reference_unseen_benign.fpr for r in mine),
        }
    return out


def run(
    pack: Path,
    out_dir: Path,
    *,
    seed: int,
    bootstrap: int,
    trees: int,
    max_window_fpr: float,
    manifest: Path | None = None,
    families: dict[str, str] | None = None,
) -> dict:
    families = IOT23_FAMILIES if families is None else families
    pack, out_dir = Path(pack), Path(out_dir)
    provenance = verify_pack(pack, manifest)
    windows = read_windows(pack)
    if _sha256(pack) != provenance.windows_sha256:
        raise PackIntegrityError(f"{pack.name} changed while it was being read")
    folds = plan_folds(window_groups(windows), families)
    results = [
        run_fold(
            windows,
            fold,
            seed=seed,
            max_window_fpr=max_window_fpr,
            bootstrap=bootstrap,
            n_estimators=trees,
        )
        for fold in folds
    ]
    report = {
        "method": METHOD,
        "pack": {"path": str(pack), **asdict(provenance)},
        "families": dict(sorted(families.items())),
        "folds_sha256": folds_sha256(folds),
        "seed": seed,
        "n_estimators": trees,
        "bootstrap": bootstrap,
        "max_window_fpr": max_window_fpr,
        "reference_threshold": REFERENCE_THRESHOLD,
        "summary": _summary(results),
        "folds": [asdict(r) for r in results],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--bootstrap", type=int, default=300)
    parser.add_argument("--trees", type=int, default=200)
    parser.add_argument("--max-window-fpr", type=float, default=0.01)
    args = parser.parse_args()
    report = run(
        args.pack,
        args.out,
        seed=args.seed,
        bootstrap=args.bootstrap,
        trees=args.trees,
        max_window_fpr=args.max_window_fpr,
        manifest=args.manifest,
    )
    print(f"pack {report['pack']['windows_sha256']} folds {report['folds_sha256']}")
    for fold in report["folds"]:
        f = fold["fold"]
        policy = fold["policy"]
        line = (
            f"held={f['held_out_family']:8} val={f['validation_family']:8} "
            f"benign_test={f['benign_test']}"
        )
        if policy is None:
            line += "  no threshold under budget"
        else:
            line += (
                f"  t={policy['threshold']:.4f} recall={fold['held_out_family']['recall']}"
                f" benignFPR={fold['unseen_benign']['fpr']}"
            )
        ref = fold["reference_held_out_family"], fold["reference_unseen_benign"]
        print(line + f"  | @0.5 recall={ref[0]['recall']} benignFPR={ref[1]['fpr']}")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
