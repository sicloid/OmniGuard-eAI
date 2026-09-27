"""Verify owned kernel timeout and independent sink recovery after SIGKILL."""

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
    applied = next(
        item for item in records if item["kind"] == "kernel_receipt" and item["action"] == "APPLIED"
    )
    if not any(
        item["kind"] == "detection" and item["score"] >= ready["threshold"] for item in records
    ):
        raise ValueError("no anomalous frozen RF result before process kill")
    if not any(
        item["kind"] == "state_event" and item["new_state"] == "QUARANTINED" for item in records
    ):
        raise ValueError("no quarantine decision before process kill")
    if any(
        item["kind"] == "kernel_receipt" and item["action"] in ("RELEASED", "ALREADY_RELEASED")
        for item in records
    ):
        raise ValueError("controller released before it was killed")
    replay_dirs = list((root / "replay-runs").iterdir())
    if len(replay_dirs) != 1:
        raise ValueError("expected one replay")
    replay = json.loads((replay_dirs[0] / "manifest.json").read_text())
    if (
        replay["status"] != "complete"
        or replay["reference_t0"]["send_begin_ns"] >= applied["mono_ns"]
    ):
        raise ValueError("replay incomplete or after quarantine")
    if replay["prepared_pcap_sha256"] != replay["provenance"]["prepared_pcap_sha256"]:
        raise ValueError("replay provenance mismatch")
    killed = json.loads((root / "killed.json").read_text())
    if killed["pid"] != ready["pid"] or killed["kill_mono_ns"] <= applied["mono_ns"]:
        raise ValueError("controller was not killed after apply")
    before = json.loads((root / "kernel-before.json").read_text())
    during = json.loads((root / "kernel-during.json").read_text())
    after = json.loads((root / "kernel-after.json").read_text())
    if not before["kernel_quarantined"] or not during["kernel_quarantined"]:
        raise ValueError("kernel block did not survive controller death")
    if after["kernel_quarantined"]:
        raise ValueError("kernel TTL did not release the block")
    if not (
        applied["mono_ns"]
        < killed["kill_mono_ns"]
        < before["mono_ns"]
        < during["mono_ns"]
        < after["mono_ns"]
    ):
        raise ValueError("clock ordering invalid")
    sinks = {
        protocol: assess_protocol(
            root,
            protocol,
            applied_ns=applied["mono_ns"],
            blocked_begin_ns=before["mono_ns"] + 300_000_000,
            blocked_end_ns=during["mono_ns"],
            release_ns=after["mono_ns"],
        )
        for protocol in ("udp", "tcp")
    }
    local = [int(line) for line in (root / "local-source.log").read_text().splitlines()]
    local_during = sum(
        before["mono_ns"] + 300_000_000 < value < during["mono_ns"] for value in local
    )
    if local_during < 3:
        raise ValueError("local service did not survive the gateway block")
    return {
        "status": "kernel_ttl_restored_after_sigkill",
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
        "prepared_pcap_sha256": replay["prepared_pcap_sha256"],
        "controller_pid": ready["pid"],
        "apply_ns": applied["mono_ns"],
        "kill_ns": killed["kill_mono_ns"],
        "kernel_active_after_kill_ns": before["mono_ns"],
        "kernel_active_during_ns": during["mono_ns"],
        "kernel_inactive_after_ttl_ns": after["mono_ns"],
        "sinks": sinks,
        "local_successes_during_block": local_during,
    }


def main() -> None:
    print(json.dumps(validate(Path(sys.argv[1])), sort_keys=True))


if __name__ == "__main__":
    main()
