"""A consumer must store each event once and must never forget an unordered boot.

These tests run the decision logic against an injected database. They execute no SQL,
so they are not evidence that 002 applies or that the statements are valid PostgreSQL:
that comes from running `platform/consume.py` against the real Compose stack. What they
do prove is that redelivery does not duplicate, that a database outage leaves the
message with the broker instead of dropping it, and that a restart rebuilds the boot
ledger from the database rather than from an empty dict.
"""

import unittest

from telemetry.consumer import (
    ConsumerError,
    Database,
    DatabaseError,
    TelemetryConsumer,
    insert_script,
    load_ledger,
    validate_payload,
)
from telemetry.envelope import BootLedger, BootOrder, ProducerRef, unwrap

PRODUCER = {"producer_id": "gw-1", "boot_id": "boot-a", "boot_started_at": 1000.0}


def payload(event_id="event-1", run_id="run-1", **event):
    body = {
        "device_id": "cam-1",
        "previous_state": "NORMAL",
        "new_state": "QUARANTINED",
        "reason": "three anomalous windows",
        "timestamp": 1500.0,
        "expires_at": None,
    }
    body.update(event)
    return {
        "schema_version": "0.1.0",
        "run_id": run_id,
        "event_id": event_id,
        "event": body,
    }


def envelope(sequence=1, producer=None, **payload_kwargs):
    return {
        "envelope_version": "1",
        "producer": dict(producer or PRODUCER),
        "sequence": sequence,
        "payload": payload(**payload_kwargs),
    }


class FakeDatabase(Database):
    """Models only what the consumer depends on: a transaction that stores or does not.

    `events` is keyed by event_id, so a second insert of the same id returns nothing,
    which is what ON CONFLICT DO NOTHING ... RETURNING does on the server.
    """

    def __init__(self):
        self.events: dict[str, dict] = {}
        self.boots: dict[tuple[str, str], tuple[float, str]] = {}
        self.scripts: list[str] = []
        self.fail_with: str | None = None

    def apply(self, sql):
        self.scripts.append(sql)
        if self.fail_with is not None:
            raise DatabaseError(self.fail_with)
        if sql.startswith("SELECT producer_id"):
            return tuple(
                (producer_id, boot_id, str(started_at))
                for (producer_id, boot_id), (started_at, _) in sorted(self.boots.items())
            )
        if sql.startswith("SELECT run_id"):
            unordered = {key for key, (_, verdict) in self.boots.items() if verdict == "UNORDERED"}
            runs = {
                event["run_id"]
                for event in self.events.values()
                if (event["producer_id"], event["boot_id"]) in unordered
            }
            return tuple((run,) for run in sorted(runs))
        return self._write(sql)

    def _write(self, sql):
        if "INSERT INTO boots" in sql:
            key = (_value(sql, "boots", 0), _value(sql, "boots", 1))
            if key not in self.boots:
                self.boots[key] = (float(_value(sql, "boots", 2)), _value(sql, "boots", 3))
        event_id = _value(sql, "events", 0)
        if event_id in self.events:
            return ()
        self.events[event_id] = {
            "run_id": _value(sql, "events", 1),
            "producer_id": _value(sql, "events", 9),
            "boot_id": _value(sql, "events", 10),
            "sequence": int(_value(sql, "events", 11)),
        }
        return ((event_id,),)


def _value(sql: str, table: str, index: int) -> str:
    """Read one VALUES entry out of the generated script, as the server would parse it."""
    body = sql.split(f"INSERT INTO {table}", 1)[1].split("VALUES", 1)[1]
    body = body.split(")", 1)[0] if table == "boots" else body.split("\n)", 1)[0]
    parts, current, quoted = [], "", False
    for character in body.strip().lstrip("("):
        if character == "'":
            quoted = not quoted
            continue
        if character == "," and not quoted:
            parts.append(current.strip())
            current = ""
            continue
        current += character
    parts.append(current.strip())
    return parts[index].strip().strip("()").strip()


class PayloadValidationTests(unittest.TestCase):
    def test_a_supported_payload_is_accepted(self):
        self.assertEqual(validate_payload(payload())["device_id"], "cam-1")

    def test_an_unsupported_schema_version_is_refused_before_the_database(self):
        document = payload() | {"schema_version": "0.2.0"}
        with self.assertRaises(ConsumerError):
            validate_payload(document)

    def test_a_record_that_does_not_describe_a_transition_is_refused(self):
        with self.assertRaises(ConsumerError):
            validate_payload(payload(previous_state="NORMAL", new_state="NORMAL"))

    def test_an_unknown_state_is_refused(self):
        with self.assertRaises(ConsumerError):
            validate_payload(payload(new_state="ON_FIRE"))

    def test_a_missing_field_is_named(self):
        document = payload()
        del document["event"]["reason"]
        with self.assertRaises(ConsumerError) as raised:
            validate_payload(document)
        self.assertIn("reason", str(raised.exception))


class ScriptTests(unittest.TestCase):
    def script(self, verdict=BootOrder.ORDERED, **kwargs):
        return insert_script(unwrap(envelope(**kwargs)), verdict)

    def test_the_event_insert_is_idempotent_on_event_id(self):
        script = self.script()
        self.assertIn("ON CONFLICT (event_id) DO NOTHING", script)
        self.assertIn("RETURNING event_id", script)

    def test_the_boot_row_is_written_before_the_event_that_references_it(self):
        script = self.script()
        self.assertLess(script.index("INSERT INTO boots"), script.index("INSERT INTO events"))

    def test_a_known_boot_is_not_written_again(self):
        self.assertNotIn("INSERT INTO boots", self.script(verdict=BootOrder.KNOWN))

    def test_the_whole_thing_is_one_transaction(self):
        script = self.script()
        self.assertTrue(script.startswith("BEGIN;"))
        self.assertTrue(script.rstrip().endswith("COMMIT;"))

    def test_a_quote_in_free_text_cannot_end_the_literal(self):
        script = self.script(reason="operator's call")
        self.assertIn("'operator''s call'", script)

    def test_a_nul_in_text_is_refused_rather_than_sent(self):
        with self.assertRaises(ConsumerError):
            self.script(reason="bad\x00reason")

    def test_a_non_finite_timestamp_is_refused_rather_than_sent(self):
        for value in (float("nan"), float("inf"), -1.0):
            with self.subTest(value), self.assertRaises(ConsumerError):
                self.script(timestamp=value)

    def test_an_absent_expiry_is_written_as_null_not_zero(self):
        self.assertIn("NULL", self.script(expires_at=None))


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.database = FakeDatabase()
        self.consumer = TelemetryConsumer(database=self.database)

    def test_a_delivered_event_is_stored_with_its_ordering_identity(self):
        result = self.consumer.ingest(envelope())
        self.assertTrue(result.stored and result.acknowledge)
        self.assertEqual(result.boot, BootOrder.ORDERED)
        stored = self.database.events["event-1"]
        self.assertEqual(stored["producer_id"], "gw-1")
        self.assertEqual(stored["boot_id"], "boot-a")
        self.assertEqual(stored["sequence"], 1)

    def test_redelivery_of_the_same_event_stores_one_row(self):
        self.consumer.ingest(envelope())
        result = self.consumer.ingest(envelope())
        self.assertTrue(result.redelivered and result.acknowledge)
        self.assertFalse(result.stored)
        self.assertEqual(len(self.database.events), 1)
        self.assertEqual(self.consumer.counters.stored, 1)
        self.assertEqual(self.consumer.counters.redelivered, 1)

    def test_out_of_order_arrival_stores_both_events_and_keeps_their_sequence(self):
        self.consumer.ingest(envelope(sequence=2, event_id="event-2"))
        self.consumer.ingest(envelope(sequence=1, event_id="event-1"))
        self.assertEqual(self.database.events["event-1"]["sequence"], 1)
        self.assertEqual(self.database.events["event-2"]["sequence"], 2)

    def test_a_malformed_envelope_is_refused_and_acknowledged_so_it_stops_returning(self):
        result = self.consumer.ingest({"envelope_version": "99"})
        self.assertTrue(result.acknowledge)
        self.assertIsNotNone(result.rejected)
        self.assertEqual(self.consumer.counters.rejected, 1)
        self.assertEqual(self.database.events, {})

    def test_an_unstorable_payload_is_refused_without_touching_the_database(self):
        self.consumer.ingest(envelope(new_state="NORMAL"))
        self.assertEqual(self.consumer.counters.rejected, 1)
        self.assertEqual(self.database.scripts, [])


class DatabaseOutageTests(unittest.TestCase):
    """A database that is down must not become a message that was thrown away."""

    def setUp(self):
        self.database = FakeDatabase()
        self.consumer = TelemetryConsumer(database=self.database)

    def test_a_failed_write_is_not_acknowledged(self):
        self.database.fail_with = "could not connect to server"
        result = self.consumer.ingest(envelope())
        self.assertFalse(result.acknowledge)
        self.assertFalse(result.stored)
        self.assertEqual(self.consumer.counters.left_unacknowledged, 1)
        self.assertEqual(self.consumer.counters.database_failures, 1)

    def test_the_redelivery_after_recovery_stores_the_event(self):
        self.database.fail_with = "could not connect to server"
        self.consumer.ingest(envelope())
        self.database.fail_with = None
        result = self.consumer.ingest(envelope())
        self.assertTrue(result.stored and result.acknowledge)
        self.assertEqual(len(self.database.events), 1)

    def test_a_boot_is_not_remembered_until_its_write_commits(self):
        # The reverse order is the bug R2 found in the spool on PR #19: memory ahead of
        # disk makes the retry skip a row that was never written, and the foreign key
        # would then reject the event that names it.
        self.database.fail_with = "could not connect to server"
        self.consumer.ingest(envelope())
        self.assertEqual(self.consumer.ledger.boots_for("gw-1"), {})
        self.database.fail_with = None
        self.consumer.ingest(envelope())
        self.assertEqual(self.consumer.ledger.boots_for("gw-1"), {"boot-a": 1000.0})
        self.assertIn(("gw-1", "boot-a"), self.database.boots)


class BootOrderingTests(unittest.TestCase):
    """An unordered boot must stay unordered, including across a restart."""

    def setUp(self):
        self.database = FakeDatabase()
        self.consumer = TelemetryConsumer(database=self.database)

    def rollback_boot(self, **kwargs):
        return {"producer_id": "gw-1", "boot_id": "boot-b", "boot_started_at": 500.0, **kwargs}

    def test_a_boot_whose_clock_went_back_is_recorded_as_unordered(self):
        self.consumer.ingest(envelope())
        result = self.consumer.ingest(
            envelope(producer=self.rollback_boot(), event_id="event-2", run_id="run-2")
        )
        self.assertEqual(result.boot, BootOrder.UNORDERED)
        self.assertEqual(self.database.boots[("gw-1", "boot-b")][1], "UNORDERED")
        self.assertEqual(self.consumer.counters.unordered_boots, 1)

    def test_a_restarted_consumer_rebuilds_the_ledger_from_the_database(self):
        self.consumer.ingest(envelope())
        self.consumer.ingest(
            envelope(producer=self.rollback_boot(), event_id="event-2", run_id="run-2")
        )
        restarted = TelemetryConsumer.restored(self.database)
        self.assertEqual(restarted.ledger.boots_for("gw-1"), {"boot-a": 1000.0, "boot-b": 500.0})

    def test_a_restart_does_not_turn_an_unordered_boot_into_an_ordered_one(self):
        # R1's acceptance condition. A blank ledger would judge boot-b against nothing
        # and report ORDERED, and the only record that it was not would be gone.
        self.consumer.ingest(envelope())
        self.consumer.ingest(
            envelope(producer=self.rollback_boot(), event_id="event-2", run_id="run-2")
        )
        restarted = TelemetryConsumer.restored(self.database)
        result = restarted.ingest(
            envelope(producer=self.rollback_boot(), event_id="event-3", run_id="run-2")
        )
        self.assertEqual(result.boot, BootOrder.KNOWN)
        self.assertEqual(self.database.boots[("gw-1", "boot-b")][1], "UNORDERED")

    def test_a_blank_ledger_would_have_lost_it_which_is_why_the_load_exists(self):
        blank = TelemetryConsumer(database=self.database)
        self.consumer.ingest(envelope())
        self.assertEqual(
            blank.ledger.verdict_for(ProducerRef("gw-1", "boot-b", 500.0)), BootOrder.ORDERED
        )
        loaded = load_ledger(self.database)
        self.assertEqual(
            loaded.verdict_for(ProducerRef("gw-1", "boot-b", 500.0)), BootOrder.UNORDERED
        )

    def test_the_same_boot_seen_twice_is_known_and_not_rewritten(self):
        self.consumer.ingest(envelope())
        result = self.consumer.ingest(envelope(event_id="event-2", sequence=2))
        self.assertEqual(result.boot, BootOrder.KNOWN)
        self.assertEqual(self.consumer.counters.boots_recorded, 1)

    def test_runs_touching_an_unordered_boot_are_listed_for_exclusion(self):
        self.consumer.ingest(envelope())
        self.consumer.ingest(
            envelope(producer=self.rollback_boot(), event_id="event-2", run_id="run-2")
        )
        self.assertEqual(self.consumer.unordered_runs(), ("run-2",))

    def test_a_different_producer_is_ordered_against_its_own_boots_only(self):
        other = {"producer_id": "gw-2", "boot_id": "boot-z", "boot_started_at": 1.0}
        self.consumer.ingest(envelope())
        result = self.consumer.ingest(envelope(producer=other, event_id="event-2"))
        self.assertEqual(result.boot, BootOrder.ORDERED)


class LedgerTests(unittest.TestCase):
    """Deciding and remembering are separate so memory cannot lead the durable record."""

    def test_deciding_does_not_record(self):
        ledger = BootLedger()
        producer = ProducerRef("gw-1", "boot-a", 1000.0)
        self.assertEqual(ledger.verdict_for(producer), BootOrder.ORDERED)
        self.assertEqual(ledger.verdict_for(producer), BootOrder.ORDERED)
        self.assertEqual(ledger.boots_for("gw-1"), {})

    def test_recording_makes_the_next_verdict_known(self):
        ledger = BootLedger()
        producer = ProducerRef("gw-1", "boot-a", 1000.0)
        ledger.record(producer)
        self.assertEqual(ledger.verdict_for(producer), BootOrder.KNOWN)

    def test_observe_still_decides_and_records_in_one_step(self):
        ledger = BootLedger()
        producer = ProducerRef("gw-1", "boot-a", 1000.0)
        self.assertEqual(ledger.observe(producer), BootOrder.ORDERED)
        self.assertEqual(ledger.observe(producer), BootOrder.KNOWN)


if __name__ == "__main__":
    unittest.main()
