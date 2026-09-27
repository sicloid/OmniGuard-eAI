"""Summarize fixed N=2/300s policy for the completed exploratory candidates."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import joblib

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from gateway.real_detector import load_pinned_rf_detector
from model.artifact import build_metadata, write_metadata
from model.nlease_run import _capture_rows, malicious_overlap_seconds, replay_device
from model.split import split_by_group
from model.train import window_groups


def summarize(pack, directory):
    report = json.loads((directory / "report.json").read_text())
    if hashlib.sha256(pack.read_bytes()).hexdigest() != report["pack"]["windows_sha256"]:
        raise ValueError("pack drift")
    windows = read_windows(pack)
    policy_spec = json.loads(Path("model/nlease_spec.json").read_text())
    output = []
    for row in report["results"]:
        if row["threshold"] is None:
            continue
        path = directory / f"{row['candidate']}-seed{row['seed']}.joblib"
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["artifact_sha256"]:
            raise ValueError("candidate artifact drift")
        model = joblib.load(path)
        selected = [w for w in windows if w.group_id in row["split"]["validation"]]
        meta = SimpleNamespace(model_id=row["candidate"], model_version="exploratory-1")
        for group, rows in _capture_rows(selected, model, row["threshold"], meta).items():
            result = replay_device(
                [(t, r) for t, r, _ in rows], n=2, lease_seconds=300, spec=policy_spec
            )
            malicious = [t for t, _, label in rows if label]
            covered = malicious_overlap_seconds(result["episodes"], malicious)
            span = rows[-1][0] + 5 - rows[0][0]
            output.append(
                {
                    "candidate": row["candidate"],
                    "seed": row["seed"],
                    "capture": group,
                    "n": 2,
                    "lease_seconds": 300,
                    "quarantines": result["quarantines"],
                    "benign_device": not malicious,
                    "observed_hours": len(rows) * 5 / 3600,
                    "span_hours": span / 3600,
                    "blocked_seconds": result["blocked_seconds"],
                    "policy_leakage": 1 - covered / (len(malicious) * 5) if malicious else None,
                    "resets": result["resets"],
                    "rejections": result["rejections"],
                }
            )
    (directory / "policy_report.json").write_text(json.dumps(output, indent=2) + "\n")
    winner = report["ranking"][0]["candidate"]
    row = next(r for r in report["results"] if r["candidate"] == winner and r["seed"] == 1)
    artifact = directory / "selected-seed1"
    artifact.mkdir(exist_ok=True)
    shutil.copyfile(directory / f"{winner}-seed1.joblib", artifact / "model.joblib")
    selected_model = joblib.load(artifact / "model.joblib")
    split = split_by_group(window_groups(windows), seed=1)
    metadata = build_metadata(
        artifact / "model.joblib",
        model_id=winner,
        model_version="exploratory-20260927",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
        threshold=row["threshold"],
        training_manifest_sha256=split.sha256(),
    )
    write_metadata(metadata, artifact)
    pins = {
        name: hashlib.sha256((artifact / name).read_bytes()).hexdigest()
        for name in ("model.joblib", "model.meta.json")
    }
    detector = load_pinned_rf_detector(
        artifact,
        expected_model_sha256=pins["model.joblib"],
        expected_metadata_sha256=pins["model.meta.json"],
    )
    selected = [w for w in windows if w.group_id in split.validation][:20]
    for window in selected:
        result = detector.predict(window.vector)
        expected = float(selected_model.predict_proba([list(window.vector.values)])[0, 1])
        if abs(result.score - expected) > 1e-12:
            raise ValueError("runtime prediction parity mismatch")
    (artifact / "pins.json").write_text(json.dumps(pins, indent=2) + "\n")
    print(json.dumps({"selected": winner, "runtime_adopted": False, "pins": pins}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.pack, args.directory)
