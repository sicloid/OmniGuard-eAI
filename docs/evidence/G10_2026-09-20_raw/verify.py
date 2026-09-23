"""Verify one local G8→G10 run from raw, ignored evidence (no fabricated gate status)."""

import argparse
import json
from pathlib import Path


def documents(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify(run_dir, g8_dir):
    before = json.loads((run_dir / "before.json").read_text())
    after = json.loads((run_dir / "after.json").read_text())
    rows = documents(run_dir / "db-events.jsonl")
    log = documents(g8_dir / "core.jsonl")
    validation = json.loads((g8_dir / "validation.json").read_text())
    events = [record for record in log if record["kind"] == "state_event"]
    receipts = [record for record in log if record["kind"] == "kernel_receipt"]
    handoffs = [record for record in log if record["kind"] == "event_handoff"]
    bridge = next(record for record in log if record["kind"] == "event_bridge_summary")
    assert len(events) == len(receipts) == len(handoffs) == len(rows) == 2
    assert all(record["outcome"] == "ACCEPTED" for record in handoffs)
    assert [row["sequence"] for row in rows] == [1, 2]
    assert len({row["event_id"] for row in rows}) == 2
    assert len({row["boot_id"] for row in rows}) == 1
    assert all(row["run_id"] == before["run_id"] for row in rows)
    assert [row["event_id"] for row in rows] == [
        entry["event_id"] for entry in before["spool_entries"]
    ]
    assert [row["event_id"] for row in rows] == [entry["event_id"] for entry in after["drain"]]
    assert all(entry["broker_ack"] for entry in after["drain"])
    assert after["consumer_exit"] == after["spool_pending"] == before["runner_exit"] == 0
    assert before["adapter"]["peer_verification"] == "VERIFIED"
    assert before["adapter"]["frames"] == before["adapter"]["accepted"] == 2
    assert before["handoff"]["accepted"] == before["handoff"]["processed"] == 2
    assert before["handoff"]["overflowed"] == before["handoff"]["worker_failures"] == 0
    assert before["publisher"]["spooled"] == 2
    assert before["publisher"]["dropped_unspoolable"] == 0
    assert bridge["accepted"] == bridge["delivered"] == 2
    assert bridge["overflowed"] == bridge["failures"] == 0
    assert validation["kernel_drops"] == 0
    assert validation["sinks"]["tcp"]["blocked"] == validation["sinks"]["udp"]["blocked"] == 0
    consumer_log = (run_dir / "consumer.log").read_text()
    assert '"stored": 2' in consumer_log and '"database_failures": 0' in consumer_log
    assert '"left_unacknowledged": 0' in consumer_log

    correlation = []
    for event, receipt, row in zip(events, receipts, rows, strict=True):
        for source, target in (
            ("device_id", "device_id"),
            ("previous_state", "previous_state"),
            ("new_state", "new_state"),
            ("reason", "reason"),
            ("timestamp", "event_timestamp"),
            ("expires_at", "expires_at"),
        ):
            assert event[source] == row[target], (source, event[source], row[target])
        assert receipt["device_id"] == row["device_id"]
        assert receipt["mono_ns"] >= event["mono_ns"]
        assert receipt["namespace"] == "og-b"
        if event["new_state"] == "QUARANTINED":
            assert receipt["action"] == "APPLIED" and receipt["readback_active"] is True
        else:
            assert receipt["action"] in ("RELEASED", "ALREADY_RELEASED")
            assert receipt["readback_active"] is False
        correlation.append(
            {
                "event_id": row["event_id"],
                "sequence": row["sequence"],
                "transition": event["previous_state"] + "→" + event["new_state"],
                "kernel_action": receipt["action"],
                "kernel_readback_active": receipt["readback_active"],
            }
        )
    return {
        "run_id": before["run_id"],
        "status": "local_correlation_and_completeness_verified",
        "scope": "one declared RF/IoT-23 lab run; pairing uses unique state payloads and sequence",
        "counts": {
            "core_events": 2,
            "bridge_delivered": 2,
            "uds_accepted": 2,
            "handoff_processed": 2,
            "spooled_during_outage": 2,
            "recovered_puback": 2,
            "consumer_stored": 2,
            "db_rows": 2,
            "drop_or_unacked": 0,
        },
        "correlation": correlation,
        "limitations": [
            "not an independent PR review",
            "not a final KAN-50 gate",
            "no durable shared decision/application correlation key in schema",
            "no general completeness claim outside this bounded run",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("g8_dir", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(json.dumps(verify(args.run_dir, args.g8_dir), indent=2, ensure_ascii=False))
