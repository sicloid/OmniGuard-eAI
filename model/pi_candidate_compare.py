"""Score predeclared model profiles on the accepted KAN-66 Pi benign pack."""

import argparse
import hashlib
import json
import platform
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.artifact import load_model
from model.nlease_run import _capture_rows, _observed, replay_device


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(document: dict) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def score(pack_dir: Path, spec_path: Path, artifacts: dict[str, Path], output: Path) -> dict:
    pack_dir, spec_path, output = Path(pack_dir), Path(spec_path), Path(output)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if spec.get("spec_version") != "pi-benign-candidate-comparison/1":
        raise ValueError("unexpected Pi comparison spec")
    source = json.loads((pack_dir / "source_manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((pack_dir / "pack_provenance.json").read_text(encoding="utf-8"))
    if provenance.get("source_manifest_sha256") != _sha256(pack_dir / "source_manifest.json"):
        raise ValueError("Pi source manifest differs from pack provenance")
    declared = spec["source"]
    checks = {
        "run_directory": Path(provenance.get("source_directory", "")).name
        == declared["run_directory"],
        "device_ip": source.get("device_ip") == declared["device_ip"],
        "duration": source.get("duration_seconds", 0) >= declared["minimum_duration_seconds"],
        "tcpdump_exit": source.get("tcpdump_exit") == declared["required_tcpdump_exit"],
        "device_frames": source.get("device_frames", 0)
        >= declared["required_device_frames_minimum"],
        "throttled_before": source.get("throttled_before")
        == f"throttled={declared['required_throttled_before']}",
        "throttled_after": source.get("throttled_after")
        == f"throttled={declared['required_throttled_after']}",
    }
    if not all(checks.values()):
        raise ValueError(f"Pi source does not satisfy frozen acceptance checks: {checks}")
    windows_path = pack_dir / "windows.jsonl"
    pack_manifest = json.loads((pack_dir / "manifest.json").read_text(encoding="utf-8"))
    if _sha256(windows_path) != pack_manifest.get("windows_sha256"):
        raise ValueError("Pi benign pack hash mismatch")
    windows = read_windows(windows_path)
    if not windows or any(window.malicious for window in windows):
        raise ValueError("Pi pack must contain at least one benign window")
    groups = {window.group_id for window in windows}
    if len(groups) != 1:
        raise ValueError("Pi comparison requires exactly one device group")

    reports = []
    for profile in spec["profiles"]:
        name = profile["name"]
        if name not in artifacts:
            raise ValueError(f"artifact path missing for {name}")
        artifact = load_model(
            artifacts[name],
            expected_model_sha256=profile["model_sha256"],
            expected_metadata_sha256=profile["metadata_sha256"],
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            feature_order=FEATURE_ORDER,
        )
        if artifact.metadata.threshold != profile["threshold"]:
            raise ValueError(f"{name}: artifact threshold differs from frozen spec")
        rows = next(
            iter(
                _capture_rows(
                    windows, artifact.model, profile["threshold"], artifact.metadata
                ).values()
            )
        )
        observed = _observed(rows)
        outcome = replay_device(
            [(start, result) for start, result, _ in rows],
            n=profile["n"],
            lease_seconds=profile["lease_seconds"],
            spec={
                "replay": {
                    "decision_delay_seconds": 0.5,
                    "max_result_age": 2.5,
                    "max_lease_seconds": 600,
                }
            },
        )
        quarantines = outcome["quarantines"]
        reports.append(
            {
                "name": name,
                "model_sha256": profile["model_sha256"],
                "metadata_sha256": profile["metadata_sha256"],
                "threshold": profile["threshold"],
                "n": profile["n"],
                "lease_seconds": profile["lease_seconds"],
                **observed,
                "window_fpr": observed["anomalous_windows"] / observed["windows"],
                **outcome,
                "quarantines_per_observed_device_hour": quarantines / observed["observed_hours"],
                "quarantines_per_span_device_hour": quarantines / observed["span_hours"],
                "blocked_seconds_per_span_device_hour": outcome["blocked_seconds"]
                / observed["span_hours"],
                "zero_quarantine_rule_of_three_upper_per_observed_hour": 3
                / observed["observed_hours"]
                if quarantines == 0
                else None,
            }
        )
    report = {
        "card": spec["card"],
        "spec_sha256": _sha256(spec_path),
        "pack_windows_sha256": _sha256(windows_path),
        "source_manifest_sha256": _sha256(pack_dir / "source_manifest.json"),
        "source_acceptance": checks,
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "profiles": reports,
        "decision_rule": spec["decision_rule"],
    }
    if output.exists():
        raise FileExistsError(f"{output} already exists; Pi evaluations are immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(report))
    output.with_suffix(output.suffix + ".sha256").write_text(f"{_sha256(output)}  {output.name}\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument(
        "--artifact",
        action="append",
        required=True,
        help="predeclared profile name and artifact directory as NAME=PATH",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    artifacts = {}
    for value in args.artifact:
        name, separator, path = value.partition("=")
        if not separator or not name or not path or name in artifacts:
            parser.error("each --artifact must be a unique NAME=PATH")
        artifacts[name] = Path(path)
    result = score(args.pack_dir, args.spec, artifacts, args.output)
    print(json.dumps(result["profiles"], sort_keys=True))


if __name__ == "__main__":
    main()
