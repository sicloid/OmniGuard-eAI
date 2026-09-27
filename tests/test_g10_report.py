"""The G10 report must fail on each loss or mismatch it exists to catch.

These fixtures are shaped like one `platform/run_g10.sh` scenario directory. They test
the report's joins and judgements, not the gate: only a real run is G10 evidence.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

# platform/ is deliberately not a Python package; load the module by path.
SOURCE = Path(__file__).resolve().parents[1] / "platform" / "g10_report.py"
_spec = importlib.util.spec_from_file_location("omniguard_g10_report", SOURCE)
g10_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(g10_report)

RUN_ID = "g10-normal-test"
EVENTS = [
    ("NORMAL", "QUARANTINED", "consecutive eligible anomalies", 1790000000.5, 1790000006.5),
    ("QUARANTINED", "NORMAL", "lease expired; not a clean bill", 1790000006.6, None),
]
RECEIPTS = [("APPLIED", True), ("ALREADY_RELEASED", False)]


def _write_lines(path: Path, records) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


def build(root: Path, name: str = "normal") -> Path:
    directory = root / name
    (directory / "g8").mkdir(parents=True)
    (directory / "run_id").write_text(RUN_ID, encoding="utf-8")
    (directory / "g8-exit").write_text("0", encoding="utf-8")
    core, rows, publishes = [], [], []
    for index, ((before, after, reason, ts, expires), (action, active)) in enumerate(
        zip(EVENTS, RECEIPTS, strict=True), start=1
    ):
        event = {
            "device_id": "camera",
            "previous_state": before,
            "new_state": after,
            "reason": reason,
            "timestamp": ts,
            "expires_at": expires,
        }
        core.append({"kind": "state_event", "mono_ns": index * 1000, **event})
        core.append({"kind": "event_handoff", "mono_ns": index * 1000 + 1, "outcome": "ACCEPTED"})
        core.append(
            {
                "kind": "kernel_receipt",
                "mono_ns": index * 1000 + 2,
                "action": action,
                "readback_active": active,
            }
        )
        event_id = f"id-{index}"
        publishes.append(
            {"event_id": event_id, "sequence": index, "outcome": "ACKED", "phase": "serve"}
        )
        rows.append(
            {
                "event_id": event_id,
                "run_id": RUN_ID,
                "sequence": index,
                "device_id": "camera",
                "previous_state": before,
                "new_state": after,
                "reason": reason,
                "event_timestamp": ts,
                "expires_at": expires,
                "ingested_at": "2026-09-22T12:00:00+00:00",
            }
        )
    core.append({"kind": "event_bridge_summary", "accepted": 2, "delivered": 2, "failures": 0})
    _write_lines(directory / "g8" / "core.jsonl", core)
    (directory / "g8" / "validation.json").write_text(
        json.dumps({"kernel_drops": 0, "sinks": {"tcp": {"blocked": 0}, "udp": {"blocked": 0}}}),
        encoding="utf-8",
    )
    (directory / "host-serve.json").write_text(
        json.dumps(
            {
                "adapter": {"peer_verification": "VERIFIED", "accepted": 2},
                "handoff": {"processed": 2, "overflowed": 0},
                "publisher": {"published": 2, "spooled": 0},
            }
        ),
        encoding="utf-8",
    )
    _write_lines(directory / "publishes.jsonl", publishes)
    _write_lines(directory / "db-events.jsonl", rows)
    consumer = {
        "stored": 2,
        "redelivered": 0,
        "rejected": 0,
        "database_failures": 0,
        "left_unacknowledged": 0,
    }
    (directory / "consumer.log").write_text(
        "ledger restored\n" + json.dumps(consumer, indent=2) + "\n", encoding="utf-8"
    )
    grafana = {
        "results": {
            "A": {
                "frames": [
                    {
                        "schema": {"fields": [{"name": "event_id"}, {"name": "sequence"}]},
                        "data": {"values": [["id-1", "id-2"], [1, 2]]},
                    }
                ]
            }
        }
    }
    (directory / "grafana.json").write_text(json.dumps(grafana), encoding="utf-8")
    return directory


def failed(directory: Path) -> list[str]:
    return [name for name, ok in g10_report.scenario(directory)["checks"].items() if not ok]


class G10ReportTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)

    def tearDown(self):
        self._temporary.cleanup()

    def test_a_complete_run_passes_every_check(self):
        result = g10_report.scenario(build(self.root))
        self.assertEqual(failed(build(self.root, "normal-2")), [])
        self.assertTrue(result["passed"])
        self.assertEqual(result["completeness"]["lost"], 0)

    def test_a_missing_row_is_counted_as_lost_and_fails(self):
        directory = build(self.root)
        rows = (directory / "db-events.jsonl").read_text(encoding="utf-8").splitlines()
        (directory / "db-events.jsonl").write_text(rows[0] + "\n", encoding="utf-8")
        result = g10_report.scenario(directory)
        self.assertFalse(result["passed"])
        self.assertEqual(result["completeness"]["lost"], 1)
        self.assertIn("db_rows_equal_produced", failed(directory))

    def test_a_row_that_differs_from_the_decision_fails(self):
        directory = build(self.root)
        path = directory / "db-events.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace("lease expired", "x"), "utf-8")
        self.assertIn("event_2_row_fields_match", failed(directory))

    def test_a_kernel_receipt_that_contradicts_the_decision_fails(self):
        directory = build(self.root)
        path = directory / "g8" / "core.jsonl"
        text = path.read_text(encoding="utf-8").replace(
            '"readback_active": true', '"readback_active": false'
        )
        path.write_text(text, encoding="utf-8")
        self.assertIn("event_1_kernel_matches_decision", failed(directory))

    def test_a_failed_uds_delivery_fails_even_if_the_rows_look_complete(self):
        directory = build(self.root)
        path = directory / "g8" / "core.jsonl"
        text = path.read_text(encoding="utf-8").replace('"failures": 0', '"failures": 1')
        path.write_text(text, encoding="utf-8")
        self.assertIn("gateway_bridge_delivered_every_event", failed(directory))

    def test_grafana_must_return_the_committed_rows(self):
        directory = build(self.root)
        path = directory / "grafana.json"
        path.write_text(path.read_text(encoding="utf-8").replace('"id-2"', '"id-9"'), "utf-8")
        self.assertIn("grafana_returns_the_committed_rows", failed(directory))

    def test_a_duplicate_that_stored_a_new_row_fails(self):
        directory = build(self.root, "duplicate")
        (directory / "republish.json").write_text(json.dumps({"outcome": "ACKED"}), "utf-8")
        log = directory / "consumer.log"
        log.write_text(
            log.read_text(encoding="utf-8").replace('"stored": 2', '"stored": 3'), "utf-8"
        )
        self.assertIn("duplicate_stored_nothing_new", failed(directory))

    def test_an_outage_whose_drain_left_entries_pending_fails(self):
        directory = build(self.root, "outage")
        (directory / "host-serve.json").write_text(
            json.dumps(
                {
                    "adapter": {"peer_verification": "VERIFIED", "accepted": 2},
                    "handoff": {"processed": 2, "overflowed": 0},
                    "publisher": {"published": 0, "spooled": 2},
                }
            ),
            encoding="utf-8",
        )
        drain = {
            "before": {"pending": [1, 2]},
            "after": {"pending": [2], "counters": {"dropped_events": 0}},
            "publisher": {"drained": 1},
            "outcomes": [{"broker_ack": True}, {"broker_ack": False}],
        }
        (directory / "host-drain.json").write_text(json.dumps(drain), encoding="utf-8")
        self.assertEqual(failed(directory), ["drain_recovered_every_event"])


if __name__ == "__main__":
    unittest.main()
