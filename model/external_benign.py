"""Device-disjoint external benign evaluation for KAN-65 and KAN-70.

The split is frozen before model scores are read.  A device is assigned from the
SHA-256 of its stable group id, so captures containing the same MAC can never cross
the development/holdout boundary.  Scoring verifies the pack, split and frozen
KAN-19 artifact pins before reporting window FPR and real DevicePolicy outcomes.
"""

import argparse
import hashlib
import json
import platform
from collections import Counter
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from data.samplepack.build import read_windows
from model.artifact import load_model
from model.baseline_run import _sha256
from model.nlease_run import _capture_rows, _observed, replay_device

SPEC_VERSION = "external-benign-eval/1"
WINDOW_SECONDS = 5.0


class ExternalBenignError(ValueError):
    """The predeclared external evaluation contract was violated."""


def _canonical(document: dict) -> bytes:
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _groups(windows) -> dict[str, int]:
    counts = Counter(window.group_id for window in windows)
    if not counts:
        raise ExternalBenignError("external pack has no windows")
    if any(window.malicious for window in windows):
        raise ExternalBenignError("external benign pack contains a malicious label")
    for window in windows:
        expected = f"device:{window.vector.device_id}"
        if window.group_id != expected:
            raise ExternalBenignError(f"{window.group_id}: expected stable device group {expected}")
    return dict(sorted(counts.items()))


def prepare_spec(
    pack: Path,
    manifest: Path,
    output: Path,
    *,
    model_sha256: str,
    metadata_sha256: str,
    threshold: float,
) -> dict:
    """Freeze an 80/20 device split without loading or scoring the model."""
    pack, manifest, output = Path(pack), Path(manifest), Path(output)
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    pack_sha = _sha256(pack)
    if manifest_doc.get("windows_sha256") != pack_sha:
        raise ExternalBenignError("pack does not match its source manifest")
    groups = _groups(read_windows(pack))
    # The first fifth in a hash-derived ordering is sealed. This uses identity only,
    # never features, labels beyond the declared benign role, or model outputs.
    ordered = sorted(groups, key=lambda group: (hashlib.sha256(group.encode()).hexdigest(), group))
    holdout_size = max(1, len(ordered) // 5)
    holdout = sorted(ordered[:holdout_size])
    development = sorted(set(ordered) - set(holdout))
    document = {
        "spec_version": SPEC_VERSION,
        "cards": {"development": "KAN-65", "holdout": "KAN-70"},
        "source_role": "CICIoT2023 external benign generalization",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "pack": {
            "windows_sha256": pack_sha,
            "manifest_sha256": _sha256(manifest),
            "windows": sum(groups.values()),
            "devices": len(groups),
        },
        "split": {
            "algorithm": "sort by sha256(stable device group id); first floor(20%) holdout",
            "development": development,
            "holdout": holdout,
            "windows_by_group": groups,
        },
        "frozen_policy": {
            "model_sha256": model_sha256,
            "metadata_sha256": metadata_sha256,
            "threshold": threshold,
            "n": 2,
            "lease_seconds": 300,
            "decision_delay_seconds": 0.5,
            "max_result_age": 2.5,
            "max_lease_seconds": 600,
        },
        "reporting": [
            "window false-positive rate per device and aggregate",
            "false quarantine episodes per observed and span device-hour",
            "blocked seconds per span device-hour",
            "policy reset and rejection counters",
            "rule-of-three upper bound when zero events are observed",
        ],
        "holdout_rule": "score exactly once after this spec is committed; report every result",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(document))
    return document


def _validate_spec(spec: dict, pack: Path, manifest: Path) -> None:
    if spec.get("spec_version") != SPEC_VERSION:
        raise ExternalBenignError(f"spec_version must be {SPEC_VERSION}")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise ExternalBenignError("feature catalogue drift")
    if _sha256(pack) != spec["pack"]["windows_sha256"]:
        raise ExternalBenignError("external pack drift")
    if _sha256(manifest) != spec["pack"]["manifest_sha256"]:
        raise ExternalBenignError("external manifest drift")
    development = set(spec["split"]["development"])
    holdout = set(spec["split"]["holdout"])
    if not development or not holdout or development & holdout:
        raise ExternalBenignError("split must have disjoint nonempty roles")


def score(
    pack: Path,
    manifest: Path,
    artifact_dir: Path,
    spec_path: Path,
    output: Path,
    *,
    role: str,
) -> dict:
    """Score one frozen role and write a self-contained evidence report."""
    if role not in {"development", "holdout"}:
        raise ExternalBenignError("role must be development or holdout")
    pack, manifest, spec_path, output = map(Path, (pack, manifest, spec_path, output))
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    _validate_spec(spec, pack, manifest)
    windows = read_windows(pack)
    actual_groups = _groups(windows)
    if actual_groups != spec["split"]["windows_by_group"]:
        raise ExternalBenignError("device/window inventory differs from frozen split")
    selected_groups = set(spec["split"][role])
    selected = [window for window in windows if window.group_id in selected_groups]
    frozen = spec["frozen_policy"]
    artifact = load_model(
        Path(artifact_dir),
        expected_model_sha256=frozen["model_sha256"],
        expected_metadata_sha256=frozen["metadata_sha256"],
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
    )
    if artifact.metadata.threshold != frozen["threshold"]:
        raise ExternalBenignError("artifact threshold differs from frozen policy")
    policy_spec = {
        "replay": {
            key: frozen[key]
            for key in ("decision_delay_seconds", "max_result_age", "max_lease_seconds")
        }
    }
    grouped = _capture_rows(selected, artifact.model, frozen["threshold"], artifact.metadata)
    devices = []
    total_anomalous = total_quarantines = 0
    total_observed = total_span = total_blocked = 0.0
    for group, rows in sorted(grouped.items()):
        observed = _observed(rows)
        outcome = replay_device(
            [(start, result) for start, result, _ in rows],
            n=frozen["n"],
            lease_seconds=frozen["lease_seconds"],
            spec=policy_spec,
        )
        anomalous = observed["anomalous_windows"]
        total_anomalous += anomalous
        total_quarantines += outcome["quarantines"]
        total_observed += observed["observed_seconds"]
        total_span += observed["span_seconds"]
        total_blocked += outcome["blocked_seconds"]
        devices.append(
            {
                "group": group,
                **observed,
                "window_fpr": anomalous / observed["windows"],
                **outcome,
                "quarantines_per_observed_device_hour": outcome["quarantines"]
                / observed["observed_hours"],
                "blocked_seconds_per_span_device_hour": outcome["blocked_seconds"]
                / observed["span_hours"],
            }
        )
    report = {
        "card": spec["cards"][role],
        "role": role,
        "spec_sha256": _sha256(spec_path),
        "pack_windows_sha256": _sha256(pack),
        "model_sha256": frozen["model_sha256"],
        "metadata_sha256": frozen["metadata_sha256"],
        "policy": {key: frozen[key] for key in ("threshold", "n", "lease_seconds")},
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "aggregate": {
            "devices": len(devices),
            "windows": sum(device["windows"] for device in devices),
            "anomalous_windows": total_anomalous,
            "window_fpr": total_anomalous / sum(device["windows"] for device in devices),
            "quarantines": total_quarantines,
            "observed_device_hours": total_observed / 3600,
            "span_device_hours": total_span / 3600,
            "quarantines_per_observed_device_hour": total_quarantines / (total_observed / 3600),
            "blocked_seconds": total_blocked,
            "blocked_seconds_per_span_device_hour": total_blocked / (total_span / 3600),
            "zero_quarantine_rule_of_three_upper_per_observed_hour": 3 / (total_observed / 3600)
            if total_quarantines == 0
            else None,
        },
        "devices": devices,
    }
    if output.exists():
        raise FileExistsError(f"{output} already exists; external evaluations are immutable")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical(report))
    output.with_suffix(output.suffix + ".sha256").write_text(f"{_sha256(output)}  {output.name}\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--pack", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--model-sha256", required=True)
    prepare.add_argument("--metadata-sha256", required=True)
    prepare.add_argument("--threshold", type=float, required=True)
    run = sub.add_parser("score")
    run.add_argument("--pack", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--artifact", type=Path, required=True)
    run.add_argument("--spec", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--role", choices=("development", "holdout"), required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_spec(
            args.pack,
            args.manifest,
            args.output,
            model_sha256=args.model_sha256,
            metadata_sha256=args.metadata_sha256,
            threshold=args.threshold,
        )
        print(
            json.dumps(
                {
                    "devices": result["pack"]["devices"],
                    "development": len(result["split"]["development"]),
                    "holdout": len(result["split"]["holdout"]),
                }
            )
        )
    else:
        result = score(
            args.pack, args.manifest, args.artifact, args.spec, args.output, role=args.role
        )
        print(json.dumps(result["aggregate"], sort_keys=True))


if __name__ == "__main__":
    main()
