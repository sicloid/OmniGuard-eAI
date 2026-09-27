"""KAN-23: separate IoT-23-model to CICIoT EGRESS attack transfer report."""

import argparse
import json
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.artifact import load_model
from model.baseline_run import _sha256
from model.nlease_run import _capture_rows, malicious_overlap_seconds, replay_device


def run(pack: Path, manifest: Path, spec_path: Path, artifacts: list[Path], output: Path):
    spec = json.loads(spec_path.read_text())
    if _sha256(pack) != spec["pack"]["windows_sha256"]:
        raise ValueError("transfer pack drift")
    if _sha256(manifest) != spec["pack"]["manifest_sha256"]:
        raise ValueError("transfer manifest drift")
    if len(artifacts) != len(spec["models"]):
        raise ValueError("one artifact directory is required for every declared model")
    windows = read_windows(pack)
    if len(windows) != spec["pack"]["windows"] or not all(w.malicious for w in windows):
        raise ValueError("transfer pack must match the declared malicious-only role")
    policy_spec = {
        "replay": {
            key: spec["policy"][key]
            for key in ("decision_delay_seconds", "max_result_age", "max_lease_seconds")
        }
    }
    reports = []
    for declaration, artifact_dir in zip(spec["models"], artifacts, strict=True):
        artifact = load_model(
            artifact_dir,
            expected_model_sha256=declaration["model_sha256"],
            expected_metadata_sha256=declaration["metadata_sha256"],
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_order=FEATURE_ORDER,
        )
        if artifact.metadata.threshold != declaration["threshold"]:
            raise ValueError(f"{declaration['name']}: threshold drift")
        rows = _capture_rows(windows, artifact.model, declaration["threshold"], artifact.metadata)
        devices = []
        anomalous = blocked = malicious_seconds = detected = 0
        for group, entries in sorted(rows.items()):
            outcome = replay_device(
                [(start, result) for start, result, _ in entries],
                n=spec["policy"]["n"],
                lease_seconds=spec["policy"]["lease_seconds"],
                spec=policy_spec,
            )
            positives = sum(result.classification.value == "anomalous" for _, result, _ in entries)
            malicious_starts = [start for start, _, _ in entries]
            overlap = malicious_overlap_seconds(outcome["episodes"], malicious_starts)
            first_detection = outcome["episodes"][0]["start"] if outcome["episodes"] else None
            first_window = entries[0][0]
            anomalous += positives
            blocked += overlap
            malicious_seconds += len(entries) * 5
            detected += first_detection is not None
            devices.append(
                {
                    "group": group,
                    "windows": len(entries),
                    "anomalous_windows": positives,
                    "window_recall": positives / len(entries),
                    "detected": first_detection is not None,
                    "detection_delay_seconds": first_detection - first_window
                    if first_detection is not None
                    else None,
                    "malicious_time_blocked_fraction": overlap / (len(entries) * 5),
                    **outcome,
                }
            )
        reports.append(
            {
                **declaration,
                "aggregate": {
                    "devices": len(devices),
                    "detected_devices": detected,
                    "device_recall": detected / len(devices),
                    "windows": len(windows),
                    "anomalous_windows": anomalous,
                    "window_recall": anomalous / len(windows),
                    "malicious_time_blocked_fraction": blocked / malicious_seconds,
                },
                "devices": devices,
            }
        )
    report = {
        "card": "KAN-23",
        "spec_sha256": _sha256(spec_path),
        "pack_windows_sha256": _sha256(pack),
        "source_limit": spec["pack"]["label_basis"],
        "models": reports,
    }
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    output.with_suffix(output.suffix + ".sha256").write_text(f"{_sha256(output)}  {output.name}\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.pack, args.manifest, args.spec, args.artifact, args.output)
    print(json.dumps([row["aggregate"] for row in report["models"]]))


if __name__ == "__main__":
    main()
