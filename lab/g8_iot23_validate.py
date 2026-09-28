"""Check real RF/IoT-23 live integration without claiming the process-kill gate."""

import json
import os
import sys
from pathlib import Path

from lab.g8_probe_evidence import assess_protocol

MODEL_SHA256 = os.environ.get(
    "OMNIGUARD_MODEL_SHA256",
    "d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b",
)
METADATA_SHA256 = os.environ.get(
    "OMNIGUARD_METADATA_SHA256",
    "917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad",
)
LEGACY_IDENTITY = ("rf-iot23", "0.1.0-seed1-kan19")


def validate(root: Path) -> dict:
    records = [json.loads(line) for line in (root / "core.jsonl").read_text().splitlines()]
    ready = next(item for item in records if item["kind"] == "ready")
    has_pins = "model_sha256" in ready and "metadata_sha256" in ready
    if has_pins:
        if ready["model_sha256"] != MODEL_SHA256 or ready["metadata_sha256"] != METADATA_SHA256:
            raise ValueError("ready record carries different artifact pins")
    elif (ready["model_id"], ready["model_version"]) != LEGACY_IDENTITY:
        raise ValueError("legacy ready record is not the frozen KAN-19 identity")
    replay_dirs = list((root / "replay-runs").iterdir())
    if len(replay_dirs) != 1:
        raise ValueError("expected exactly one replay")
    replay = json.loads((replay_dirs[0] / "manifest.json").read_text())
    if replay["status"] != "complete":
        raise ValueError("replay did not complete")
    if replay["prepared_pcap_sha256"] != replay["provenance"]["prepared_pcap_sha256"]:
        raise ValueError("replay did not use the prepared bytes in provenance")
    if replay["provenance"]["parent_pcap_sha256"] != (
        "80dcc2602519479ddcde889fa902fee19a76696630811452f8df38888af894f2"
    ):
        raise ValueError("replay provenance does not name audited IoT-23 8-1 parent")
    t0 = replay["reference_t0"]["send_begin_ns"]
    applied = next(
        item for item in records if item["kind"] == "kernel_receipt" and item["action"] == "APPLIED"
    )
    released = next(
        item
        for item in records
        if item["kind"] == "kernel_receipt"
        and item["action"] in ("RELEASED", "ALREADY_RELEASED")
        and item["mono_ns"] > applied["mono_ns"]
    )
    if not t0 < applied["mono_ns"] < released["mono_ns"]:
        raise ValueError("source, apply and release clocks are inconsistent")
    if not any(
        item["kind"] == "detection" and item["score"] >= ready["threshold"] for item in records
    ):
        raise ValueError("no anomalous RF result")
    if not any(
        item["kind"] == "state_event" and item["new_state"] == "QUARANTINED" for item in records
    ):
        raise ValueError("no quarantine decision")
    summary = next(item for item in records if item["kind"] == "summary")
    if summary["capture_stats"]["kernel_drops"] or summary["kernel_quarantined"]:
        raise ValueError("capture loss or kernel block remained")
    end = min(
        released["mono_ns"] - 100_000_000,
        applied["mono_ns"] + int(ready["lease_seconds"] * 1e9) - 100_000_000,
    )
    if end - applied["mono_ns"] < 1_000_000_000:
        raise ValueError("blocked interval too short to verify both sinks")
    sinks = {
        protocol: assess_protocol(
            root,
            protocol,
            applied_ns=applied["mono_ns"],
            blocked_begin_ns=applied["mono_ns"] + 300_000_000,
            blocked_end_ns=end,
            release_ns=released["mono_ns"],
        )
        for protocol in ("udp", "tcp")
    }
    local = [int(line) for line in (root / "local-source.log").read_text().splitlines()]
    local_during = sum(applied["mono_ns"] + 300_000_000 < value < end for value in local)
    if local_during < 3:
        raise ValueError("local service did not remain available during gateway block")
    return {
        "status": "partial_real_model_iot23_core",
        **(
            {
                "model_id": ready["model_id"],
                "model_version": ready["model_version"],
                "model_sha256": ready["model_sha256"],
                "metadata_sha256": ready["metadata_sha256"],
            }
            if has_pins
            else {}
        ),
        "not_yet_proven": ["process-kill/kernel-TTL run", "independent owner review"],
        "prepared_pcap_sha256": replay["prepared_pcap_sha256"],
        "replay_t0_send_begin_ns": t0,
        "apply_ns": applied["mono_ns"],
        "release_ns": released["mono_ns"],
        "sinks": sinks,
        "local_successes_during_block": local_during,
        "windows": summary["windows"],
        "kernel_drops": summary["capture_stats"]["kernel_drops"],
        "reorder_stats": summary["reorder_stats"],
    }


def main() -> None:
    result = validate(Path(sys.argv[1]))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
