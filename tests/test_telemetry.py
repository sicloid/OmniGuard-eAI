"""ADR-0003 framing, identity, spool, handoff and publisher behaviour.

A fake transport proves the fault behaviour, not delivery. Real broker and
database evidence is a separate Compose run under KAN-50.
"""

import io
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path

from core.schema import SCHEMA_VERSION, DeviceState, StateEvent, TelemetryPayload
from telemetry.canonical import CanonicalError, canonical_bytes
from telemetry.envelope import (
    BootLedger,
    BootOrder,
    EnvelopeError,
    ProducerRef,
    unwrap,
    wrap,
)
from telemetry.framing import (
    MAX_FRAME,
    FrameError,
    FrameTooLarge,
    IncompleteFrame,
    encode_frame,
    read_frame,
)
from telemetry.handoff import HandoffOutcome, TelemetryHandoff
from telemetry.identity import (
    EventIdentity,
    IdentityError,
    ProducerIdentity,
    SequenceCounter,
    event_id,
    validate_device_id,
)
from telemetry.publisher import (
    LEGACY_TOPIC_PREFIX,
    QOS,
    RETAIN,
    TOPIC_PREFIX,
    Acknowledgement,
    TelemetryPublisher,
    TransportContractError,
    TransportError,
    topic_for,
)
from telemetry.spool import JOURNAL_FILENAME, BoundedSpool, SpoolScope

PRODUCER = ProducerIdentity("gateway-01", "3f2b0c0e-0000-4000-8000-000000000001", 1_700_000_000.0)
SCOPE = SpoolScope(PRODUCER.producer_id, PRODUCER.boot_id, PRODUCER.boot_started_at)
# The same installation after a restart: sequences start over, the boot does not.
OTHER_SCOPE = SpoolScope("gateway-01", "3f2b0c0e-0000-4000-8000-000000000002", 1_700_000_500.0)


def an_event(**overrides) -> StateEvent:
    fields = {
        "device_id": "lan-device-07",
        "previous_state": DeviceState.NORMAL,
        "new_state": DeviceState.QUARANTINED,
        "reason": "policy_n_of_m",
        "timestamp": 1_700_000_123.5,
        "expires_at": None,
    }
    fields.update(overrides)
    return StateEvent(**fields)


class CountingStream(io.RawIOBase):
    """Stream that records how many bytes a reader actually consumed."""

    def __init__(self, data: bytes):
        self._buffer = io.BytesIO(data)
        self.consumed = 0

    def read(self, size=-1):
        chunk = self._buffer.read(size)
        self.consumed += len(chunk)
        return chunk


class CollectingTransport:
    """A broker that acknowledges every message it does not reject."""

    def __init__(self, fail_times: int = 0):
        self.sent: list[tuple[str, bytes, int, bool]] = []
        self.fail_times = fail_times

    def publish(self, topic, payload, *, qos, retain):
        if self.fail_times:
            self.fail_times -= 1
            raise TransportError("broker unavailable")
        self.sent.append((topic, payload, qos, retain))
        return Acknowledgement.ACKED


class QueueOnlyTransport(CollectingTransport):
    """A client that buffers locally and returns before the broker replies.

    It takes the bytes and loses nothing visibly, which is exactly why its
    return value must not be read as delivery.
    """

    def __init__(self, queue_times: int = 1):
        super().__init__()
        self.queue_times = queue_times

    def publish(self, topic, payload, *, qos, retain):
        acknowledgement = super().publish(topic, payload, qos=qos, retain=retain)
        if self.queue_times:
            self.queue_times -= 1
            return Acknowledgement.QUEUED
        return acknowledgement


class SilentTransport:
    """A transport written against the old contract: it returns nothing."""

    def publish(self, topic, payload, *, qos, retain):
        return None


class SimulatedCrash(RuntimeError):
    """Stands in for the process dying at a chosen point."""


class CrashingSpool(BoundedSpool):
    """A spool whose write never lands, as if the process died reaching it."""

    def append(self, sequence, body, *, now, scope):
        raise SimulatedCrash("process died before the spool write")


class CrashAtEviction(BoundedSpool):
    """A spool that dies at one chosen point inside a single eviction.

    The three points are the boundaries the accounting has to survive: intent
    declared but nothing deleted, deleted but the loss not yet recorded, and
    recorded but the journal not yet cleared.
    """

    def __init__(self, *args, crash_at: str, **kwargs):
        self._crash_at = crash_at
        super().__init__(*args, **kwargs)

    def _write_journal(self, record):
        super()._write_journal(record)
        if self._crash_at == "after_journal":
            raise SimulatedCrash("died with the eviction declared but not performed")

    def _save_counters(self):
        if self._crash_at == "after_unlink":
            raise SimulatedCrash("died after the delete, before the loss was recorded")
        super()._save_counters()
        if self._crash_at == "after_counters":
            raise SimulatedCrash("died after the loss was recorded, before the journal cleared")


class CanonicalTests(unittest.TestCase):
    def test_encoding_is_sorted_compact_and_utf8(self):
        encoded = canonical_bytes({"b": 1, "a": "ö"})
        self.assertEqual(encoded, '{"a":"ö","b":1}'.encode())

    def test_nonfinite_numbers_are_refused(self):
        with self.assertRaises(CanonicalError):
            canonical_bytes({"value": float("nan")})


class FramingTests(unittest.TestCase):
    def test_round_trip(self):
        body = b'{"a":1}'
        self.assertEqual(read_frame(io.BytesIO(encode_frame(body))), body)

    def test_clean_end_of_stream_returns_none(self):
        self.assertIsNone(read_frame(io.BytesIO(b"")))

    def test_encoding_refuses_empty_and_oversized_bodies(self):
        with self.assertRaises(FrameError):
            encode_frame(b"")
        with self.assertRaises(FrameTooLarge):
            encode_frame(b"x" * (MAX_FRAME + 1))

    def test_oversized_declaration_is_refused_without_reading_the_body(self):
        header = (MAX_FRAME + 1).to_bytes(4, "big")
        stream = CountingStream(header + b"x" * 4096)
        with self.assertRaises(FrameTooLarge):
            read_frame(stream)
        # Only the four header bytes were consumed: the body never reached memory.
        self.assertEqual(stream.consumed, 4)

    def test_partial_body_raises_instead_of_yielding_half_a_record(self):
        truncated = encode_frame(b'{"a":1}')[:-2]
        with self.assertRaises(IncompleteFrame):
            read_frame(io.BytesIO(truncated))

    def test_zero_length_declaration_is_refused(self):
        with self.assertRaises(FrameError):
            read_frame(io.BytesIO((0).to_bytes(4, "big")))


class IdentityTests(unittest.TestCase):
    def test_redelivery_reproduces_the_same_event_id(self):
        identity = EventIdentity(PRODUCER, 7)
        self.assertEqual(event_id(identity, an_event()), event_id(identity, an_event()))

    def test_same_timestamp_different_events_stay_distinct(self):
        first = EventIdentity(PRODUCER, 1)
        second = EventIdentity(PRODUCER, 2)
        event = an_event()
        self.assertNotEqual(event_id(first, event), event_id(second, event))

    def test_a_new_boot_changes_the_identity(self):
        other_boot = replace(PRODUCER, boot_id="3f2b0c0e-0000-4000-8000-000000000002")
        self.assertNotEqual(
            event_id(EventIdentity(PRODUCER, 1), an_event()),
            event_id(EventIdentity(other_boot, 1), an_event()),
        )

    def test_ordering_uses_boot_start_before_sequence(self):
        older = EventIdentity(PRODUCER, 9)
        newer = EventIdentity(replace(PRODUCER, boot_started_at=1_700_000_500.0), 1)
        self.assertLess(older.ordering_key(), newer.ordering_key())

    def test_topic_hostile_device_ids_are_refused(self):
        for value in ("a/b", "a+b", "a#b", "a b", "", "x" * 65):
            with self.subTest(value=value), self.assertRaises(IdentityError):
                validate_device_id(value)

    def test_sequence_counter_is_gapless_from_one(self):
        counter = SequenceCounter()
        self.assertEqual([counter.next() for _ in range(3)], [1, 2, 3])


class SpoolTests(unittest.TestCase):
    def spool(self, directory, *, max_bytes=1024, max_age_seconds=60.0):
        return BoundedSpool(Path(directory), max_bytes=max_bytes, max_age_seconds=max_age_seconds)

    def test_byte_bound_evicts_oldest_and_records_the_sequence_range(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = self.spool(directory, max_bytes=200)
            for sequence in (1, 2, 3):
                spool.append(sequence, b"x" * 90, now=10.0, scope=SCOPE)
            pending = spool.pending()
            counters = spool.counters()
            self.assertEqual([entry.sequence for entry in pending], [2, 3])
            self.assertEqual(counters.dropped_events, 1)
            self.assertEqual(counters.dropped_by_bytes, 1)
            self.assertEqual(counters.dropped_by_age, 0)
            loss = counters.loss_for(SCOPE.token)
            self.assertEqual((loss.first_sequence, loss.last_sequence), (1, 1))

    def test_age_bound_evicts_and_is_attributed_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = self.spool(directory, max_age_seconds=5.0)
            spool.append(1, b"old", now=100.0, scope=SCOPE)
            spool.append(2, b"new", now=108.0, scope=SCOPE)
            self.assertEqual([entry.sequence for entry in spool.pending()], [2])
            self.assertEqual(spool.counters().dropped_by_age, 1)
            self.assertEqual(spool.counters().dropped_by_bytes, 0)

    def test_an_entry_larger_than_the_budget_is_refused_not_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = self.spool(directory, max_bytes=64)
            spool.append(1, b"keep", now=1.0, scope=SCOPE)
            self.assertFalse(spool.append(2, b"x" * 65, now=1.0, scope=SCOPE))
            self.assertEqual([entry.sequence for entry in spool.pending()], [1])
            self.assertEqual(spool.counters().rejected_oversize, 1)
            self.assertEqual(spool.counters().dropped_events, 0)

    def test_counters_survive_reopening_the_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.spool(directory, max_bytes=100)
            first.append(1, b"x" * 60, now=1.0, scope=SCOPE)
            first.append(2, b"x" * 60, now=1.0, scope=SCOPE)
            self.assertEqual(first.counters().dropped_events, 1)
            reopened = self.spool(directory, max_bytes=100)
            self.assertEqual(reopened.counters().dropped_events, 1)
            self.assertEqual(reopened.counters().loss_for(SCOPE.token).first_sequence, 1)

    def test_a_loss_is_attributed_to_the_boot_that_produced_the_sequence(self):
        """Sequences restart at one, so a range without its boot means nothing."""
        with tempfile.TemporaryDirectory() as directory:
            spool = self.spool(directory, max_bytes=200)
            spool.append(1, b"x" * 90, now=10.0, scope=SCOPE)
            spool.append(1, b"x" * 90, now=10.0, scope=OTHER_SCOPE)
            spool.append(2, b"x" * 90, now=10.0, scope=OTHER_SCOPE)

            counters = spool.counters()
            self.assertEqual(counters.dropped_events, 1)
            self.assertIsNone(counters.loss_for(OTHER_SCOPE.token))
            first_boot_loss = counters.loss_for(SCOPE.token)
            self.assertEqual(first_boot_loss.dropped_events, 1)
            self.assertEqual(first_boot_loss.boot_id, SCOPE.boot_id)
            self.assertEqual(first_boot_loss.producer_id, SCOPE.producer_id)
            self.assertEqual(spool.scopes()[OTHER_SCOPE.token], OTHER_SCOPE)


class SpoolEvictionCrashTests(unittest.TestCase):
    """The delete and its accounting are one transaction, or the loss is invisible."""

    def filled(self, path, crash_at):
        """A spool loaded to its bound whose next eviction crashes at `crash_at`."""
        spool = CrashAtEviction(path, max_bytes=200, max_age_seconds=60.0, crash_at=crash_at)
        spool.append(1, b"x" * 90, now=10.0, scope=SCOPE)
        spool.append(2, b"x" * 90, now=10.0, scope=SCOPE)
        return spool

    def test_a_crash_between_the_delete_and_the_counter_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            spool = self.filled(path, crash_at="after_unlink")
            with self.assertRaises(SimulatedCrash):
                spool.append(3, b"x" * 90, now=10.0, scope=SCOPE)

            reopened = BoundedSpool(path, max_bytes=200, max_age_seconds=60.0)
            counters = reopened.counters()
            self.assertEqual(counters.dropped_events, 1, "the loss is recorded, not erased with it")
            self.assertEqual(counters.dropped_by_bytes, 1)
            self.assertEqual(counters.loss_for(SCOPE.token).first_sequence, 1)
            self.assertEqual([entry.sequence for entry in reopened.pending()], [2, 3])

    def test_a_crash_before_the_delete_is_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            spool = self.filled(path, crash_at="after_journal")
            with self.assertRaises(SimulatedCrash):
                spool.append(3, b"x" * 90, now=10.0, scope=SCOPE)

            reopened = BoundedSpool(path, max_bytes=200, max_age_seconds=60.0)
            self.assertEqual(reopened.counters().dropped_events, 1)
            self.assertEqual(
                [entry.sequence for entry in reopened.pending()],
                [2, 3],
                "the entry the journal named is gone, exactly as the counter says",
            )

    def test_a_crash_before_the_journal_is_cleared_does_not_double_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            spool = self.filled(path, crash_at="after_counters")
            with self.assertRaises(SimulatedCrash):
                spool.append(3, b"x" * 90, now=10.0, scope=SCOPE)

            reopened = BoundedSpool(path, max_bytes=200, max_age_seconds=60.0)
            self.assertEqual(reopened.counters().dropped_events, 1)
            self.assertEqual(reopened.counters().loss_for(SCOPE.token).dropped_events, 1)

            again = BoundedSpool(path, max_bytes=200, max_age_seconds=60.0)
            self.assertEqual(again.counters().dropped_events, 1, "replay is idempotent")

    def test_recovery_runs_before_the_directory_is_used(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            spool = self.filled(path, crash_at="after_unlink")
            with self.assertRaises(SimulatedCrash):
                spool.append(3, b"x" * 90, now=10.0, scope=SCOPE)
            self.assertTrue((path / JOURNAL_FILENAME).exists())

            reopened = BoundedSpool(path, max_bytes=200, max_age_seconds=60.0)
            self.assertFalse(
                (path / JOURNAL_FILENAME).exists(), "a finished eviction leaves no journal"
            )
            self.assertFalse(reopened.recover(), "nothing is left to recover")


class PublisherTests(unittest.TestCase):
    def publisher(self, directory, transport, **kwargs):
        spool = BoundedSpool(Path(directory), max_bytes=4096, max_age_seconds=3600.0)
        return TelemetryPublisher(transport, spool, PRODUCER, run_id="run-1", **kwargs), spool

    def test_publish_uses_the_per_device_topic_at_qos1_without_retain(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            publisher, _ = self.publisher(directory, transport)
            outcome = publisher.publish(an_event(), now=10.0)
            topic, payload, qos, retain = transport.sent[0]
            self.assertTrue(outcome.broker_ack)
            self.assertIs(outcome.acknowledgement, Acknowledgement.ACKED)
            self.assertEqual(publisher.counters.published, 1)
            self.assertEqual(topic, "omniguard/state/v2/lan-device-07")
            self.assertEqual((qos, retain), (QOS, RETAIN))
            envelope = unwrap(json.loads(payload.decode("utf-8")))
            self.assertEqual(envelope.payload["schema_version"], SCHEMA_VERSION)
            self.assertEqual(envelope.payload["event_id"], outcome.event_id)

    def test_a_hostile_device_id_never_reaches_the_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            publisher, spool = self.publisher(directory, transport)
            outcome = publisher.publish(an_event(device_id="lan/07"), now=10.0)
            self.assertTrue(outcome.rejected)
            self.assertEqual(transport.sent, [])
            self.assertEqual(spool.pending(), [])
            self.assertEqual(publisher.counters.rejected_device_id, 1)

    def test_a_broker_outage_spools_instead_of_raising_into_the_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport(fail_times=1)
            publisher, spool = self.publisher(directory, transport)
            outcome = publisher.publish(an_event(), now=10.0)
            self.assertFalse(outcome.broker_ack)
            self.assertTrue(outcome.spooled)
            self.assertEqual(len(spool.pending()), 1)

    def test_drain_republishes_the_stored_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport(fail_times=1)
            publisher, spool = self.publisher(directory, transport)
            first = publisher.publish(an_event(), now=10.0)
            spooled_bytes = spool.read(spool.pending()[0])
            drained = publisher.drain(now=11.0)
            self.assertEqual([outcome.broker_ack for outcome in drained], [True])
            self.assertEqual(drained[0].event_id, first.event_id)
            self.assertEqual(transport.sent[0][1], spooled_bytes)
            self.assertEqual(spool.pending(), [])

    def test_drain_stops_at_the_first_entry_that_fails_again(self):
        with tempfile.TemporaryDirectory() as directory:
            # Two failures consume the publishes; the third fails the first retry.
            transport = CollectingTransport(fail_times=3)
            publisher, spool = self.publisher(directory, transport)
            publisher.publish(an_event(), now=10.0)
            publisher.publish(an_event(timestamp=1_700_000_124.5), now=10.0)
            self.assertEqual(len(spool.pending()), 2)

            blocked = publisher.drain(now=11.0)
            self.assertEqual([outcome.broker_ack for outcome in blocked], [False])
            self.assertEqual(len(spool.pending()), 2, "a failed retry must not drop the entry")

            recovered = publisher.drain(now=12.0)
            self.assertEqual([outcome.broker_ack for outcome in recovered], [True, True])
            self.assertEqual(spool.pending(), [])

    def test_resubmitting_an_event_within_one_boot_takes_a_second_identity(self):
        """Two submissions of one event consume two sequences, so two identities.

        This is submission accounting only. It injects no fault and reopens no
        state, so it is not crash evidence; the test below covers that.
        """
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            publisher, _ = self.publisher(directory, transport)
            event = an_event()
            first = publisher.publish(event, now=10.0)
            resubmitted = publisher.publish(event, now=10.0)
            self.assertNotEqual(first.event_id, resubmitted.event_id)

    def test_crash_before_the_spool_write_loses_the_event_and_duplicates_it_on_restart(self):
        """Documents the accepted limit in ADR-0003; passing is not a fix.

        The process dies after the sequence is consumed and before the spool
        write lands. Reopening the directory shows the event is gone and that
        nothing recorded its loss, and the restarted producer regenerates it
        under a new boot, so the consumer stores it a second time. KAN-50
        reports how often this window is hit.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            event = an_event()
            # The identity boot one consumed, derived the same way the publisher does.
            lost_event_id = event_id(EventIdentity(PRODUCER, 1), event)

            crashing = CrashingSpool(path, max_bytes=4096, max_age_seconds=3600.0)
            first_boot = TelemetryPublisher(
                CollectingTransport(fail_times=1), crashing, PRODUCER, run_id="run-1"
            )
            with self.assertRaises(SimulatedCrash):
                first_boot.publish(event, now=10.0)

            reopened = BoundedSpool(path, max_bytes=4096, max_age_seconds=3600.0)
            self.assertEqual(reopened.pending(), [], "the crash left nothing durable to retry")
            self.assertEqual(
                reopened.counters().dropped_events, 0, "the loss is not even counted here"
            )

            restarted = ProducerIdentity(
                PRODUCER.producer_id, "3f2b0c0e-0000-4000-8000-000000000002", 1_700_000_500.0
            )
            second_boot = TelemetryPublisher(
                CollectingTransport(), reopened, restarted, run_id="run-1"
            )
            replayed = second_boot.publish(event, now=20.0)
            self.assertTrue(replayed.broker_ack)
            self.assertNotEqual(
                replayed.event_id, lost_event_id, "the regenerated event is a duplicate identity"
            )


class AcknowledgementTests(unittest.TestCase):
    """ADR-0003 section 7: transport acceptance is not a broker acknowledgement."""

    def publisher(self, directory, transport):
        spool = BoundedSpool(Path(directory), max_bytes=4096, max_age_seconds=3600.0)
        return TelemetryPublisher(transport, spool, PRODUCER, run_id="run-1"), spool

    def test_a_queue_only_transport_is_not_counted_as_delivered(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = QueueOnlyTransport()
            publisher, spool = self.publisher(directory, transport)
            outcome = publisher.publish(an_event(), now=10.0)
            self.assertEqual(len(transport.sent), 1, "the transport did take the bytes")
            self.assertFalse(outcome.broker_ack)
            self.assertIs(outcome.acknowledgement, Acknowledgement.QUEUED)
            self.assertTrue(outcome.spooled, "an unacknowledged message keeps its durable copy")
            self.assertEqual(publisher.counters.published, 0)
            self.assertEqual(publisher.counters.queued_unacked, 1)
            self.assertEqual(len(spool.pending()), 1)

    def test_drain_keeps_the_entry_until_the_broker_acknowledges_it(self):
        with tempfile.TemporaryDirectory() as directory:
            # One failure spools the publish; the retry after it is only queued.
            transport = QueueOnlyTransport()
            transport.fail_times = 1
            publisher, spool = self.publisher(directory, transport)
            publisher.publish(an_event(), now=10.0)
            self.assertEqual(len(spool.pending()), 1)

            queued = publisher.drain(now=11.0)
            self.assertEqual([outcome.broker_ack for outcome in queued], [False])
            self.assertIs(queued[0].acknowledgement, Acknowledgement.QUEUED)
            self.assertEqual(len(spool.pending()), 1, "a queued retry is not a delivery")
            self.assertEqual(publisher.counters.drained, 0)

            acknowledged = publisher.drain(now=12.0)
            self.assertEqual([outcome.broker_ack for outcome in acknowledged], [True])
            self.assertEqual(spool.pending(), [])
            self.assertEqual(publisher.counters.drained, 1)

    def test_a_transport_that_returns_nothing_is_a_contract_error(self):
        with tempfile.TemporaryDirectory() as directory:
            publisher, spool = self.publisher(directory, SilentTransport())
            with self.assertRaises(TransportContractError):
                publisher.publish(an_event(), now=10.0)
            self.assertEqual(publisher.counters.published, 0)
            self.assertEqual(spool.pending(), [])

    def test_an_event_too_large_for_the_spool_is_reported_as_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = BoundedSpool(Path(directory), max_bytes=64, max_age_seconds=3600.0)
            publisher = TelemetryPublisher(
                CollectingTransport(fail_times=1), spool, PRODUCER, run_id="run-1"
            )
            outcome = publisher.publish(an_event(), now=10.0)
            self.assertFalse(outcome.broker_ack)
            self.assertFalse(outcome.spooled)
            self.assertTrue(outcome.dropped, "a loss is stated, not inferred from empty fields")
            self.assertEqual(publisher.counters.dropped_unspoolable, 1)
            self.assertEqual(spool.counters().rejected_oversize, 1)


class TopicTests(unittest.TestCase):
    def test_prefix_is_versioned_so_a_new_envelope_takes_a_new_topic(self):
        self.assertEqual(topic_for("dev-1"), "omniguard/state/v2/dev-1")

    def test_the_old_state_topic_is_left_where_it_was(self):
        """ADR-0002: a new envelope takes a new topic, the old one is preserved."""
        self.assertEqual(LEGACY_TOPIC_PREFIX, "omniguard/state/v1")
        self.assertNotEqual(TOPIC_PREFIX, LEGACY_TOPIC_PREFIX)

    def test_both_versions_stay_inside_the_existing_broker_acl(self):
        for prefix in (TOPIC_PREFIX, LEGACY_TOPIC_PREFIX):
            self.assertTrue(prefix.startswith("omniguard/"), prefix)


class EnvelopeTests(unittest.TestCase):
    """ADR-0003 section 5.1: ordering metadata beside a payload that never moves."""

    def envelope(self, sequence=1, producer=PRODUCER):
        payload = {"schema_version": SCHEMA_VERSION, "event_id": "id", "run_id": "run-1"}
        return wrap(EventIdentity(producer, sequence), payload)

    def test_the_payload_is_nested_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            spool = BoundedSpool(Path(directory), max_bytes=4096, max_age_seconds=3600.0)
            publisher = TelemetryPublisher(transport, spool, PRODUCER, run_id="run-1")
            event = an_event()
            outcome = publisher.publish(event, now=10.0)
            envelope = unwrap(json.loads(transport.sent[0][1].decode("utf-8")))

            untouched = TelemetryPayload(SCHEMA_VERSION, "run-1", outcome.event_id, event)
            self.assertEqual(
                envelope.payload, untouched.to_dict(), "0.1.0 is carried verbatim, not widened"
            )
            self.assertEqual(envelope.sequence, 1)

    def test_the_envelope_carries_producer_boot_and_sequence(self):
        envelope = unwrap(self.envelope(sequence=7))
        self.assertEqual(envelope.sequence, 7)
        self.assertEqual(envelope.producer.producer_id, PRODUCER.producer_id)
        self.assertEqual(envelope.producer.boot_id, PRODUCER.boot_id)
        self.assertEqual(envelope.producer.boot_started_at, PRODUCER.boot_started_at)

    def test_an_unknown_envelope_version_is_refused(self):
        document = self.envelope()
        document["envelope_version"] = "99"
        with self.assertRaises(EnvelopeError):
            unwrap(document)

    def test_a_missing_field_is_refused_rather_than_guessed(self):
        for field in ("envelope_version", "producer", "sequence", "payload"):
            document = self.envelope()
            del document[field]
            with self.assertRaises(EnvelopeError):
                unwrap(document)

    def test_ordering_survives_serialisation_and_a_restart(self):
        """The review's ask: order events read back off the wire, across a restart."""
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            spool = BoundedSpool(Path(directory), max_bytes=8192, max_age_seconds=3600.0)

            first_boot = TelemetryPublisher(transport, spool, PRODUCER, run_id="run-1")
            first_boot.publish(an_event(), now=10.0)
            first_boot.publish(an_event(timestamp=1_700_000_124.5), now=11.0)

            restarted = ProducerIdentity(
                PRODUCER.producer_id, "3f2b0c0e-0000-4000-8000-000000000002", 1_700_000_500.0
            )
            second_boot = TelemetryPublisher(transport, spool, restarted, run_id="run-1")
            second_boot.publish(an_event(timestamp=1_700_000_125.5), now=12.0)

            # Read back exactly what a consumer would receive, in a shuffled order.
            wire = [payload for _, payload, _, _ in transport.sent]
            envelopes = [unwrap(json.loads(body.decode("utf-8"))) for body in wire]
            shuffled = [envelopes[2], envelopes[0], envelopes[1]]
            ordered = sorted(shuffled, key=lambda envelope: envelope.ordering_key())

            self.assertEqual([envelope.sequence for envelope in ordered], [1, 2, 1])
            self.assertEqual(
                [envelope.producer.boot_id for envelope in ordered],
                [PRODUCER.boot_id, PRODUCER.boot_id, restarted.boot_id],
                "the restarted boot's sequence 1 sorts after the first boot's sequence 2",
            )

    def test_equal_boot_times_are_broken_deterministically(self):
        twin = replace(PRODUCER, boot_id="3f2b0c0e-0000-4000-8000-00000000000f")
        first = unwrap(self.envelope(sequence=5))
        second = unwrap(self.envelope(sequence=1, producer=twin))
        self.assertEqual(first.producer.boot_started_at, second.producer.boot_started_at)
        # A total order that every consumer computes the same way; not a claim
        # about which boot really started first.
        self.assertLess(first.ordering_key(), second.ordering_key())


class BootLedgerTests(unittest.TestCase):
    """A UTC start time cannot prove restart order on its own; say so out loud."""

    def reference(self, boot_id, boot_started_at, producer_id="gateway-01"):
        return ProducerRef(producer_id, boot_id, boot_started_at)

    def test_a_later_boot_is_ordered(self):
        ledger = BootLedger()
        self.assertIs(ledger.observe(self.reference("boot-1", 100.0)), BootOrder.ORDERED)
        self.assertIs(ledger.observe(self.reference("boot-2", 200.0)), BootOrder.ORDERED)

    def test_a_repeated_boot_is_already_known(self):
        ledger = BootLedger()
        ledger.observe(self.reference("boot-1", 100.0))
        self.assertIs(ledger.observe(self.reference("boot-1", 100.0)), BootOrder.KNOWN)

    def test_a_clock_rollback_is_reported_not_silently_ordered(self):
        ledger = BootLedger()
        ledger.observe(self.reference("boot-1", 200.0))
        self.assertIs(ledger.observe(self.reference("boot-2", 100.0)), BootOrder.UNORDERED)

    def test_an_equal_boot_time_is_reported_too(self):
        ledger = BootLedger()
        ledger.observe(self.reference("boot-1", 100.0))
        self.assertIs(ledger.observe(self.reference("boot-2", 100.0)), BootOrder.UNORDERED)

    def test_producers_are_tracked_apart(self):
        ledger = BootLedger()
        ledger.observe(self.reference("boot-1", 200.0))
        self.assertIs(
            ledger.observe(self.reference("boot-9", 100.0, producer_id="gateway-02")),
            BootOrder.ORDERED,
            "another device's clock says nothing about this one's order",
        )


class StalledTransport:
    """A broker call that does not return until the test releases it."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def publish(self, topic, payload, *, qos, retain):
        self.entered.set()
        self.release.wait(timeout=10.0)
        return Acknowledgement.ACKED


class FailingDiskSpool(BoundedSpool):
    """Every durable write fails, the way a full or broken disk fails."""

    def _write_atomic(self, path, payload):
        raise OSError("disk full")


class HandoffTests(unittest.TestCase):
    """ADR-0002: telemetry loss cannot block enforcement or release."""

    def publisher(self, directory, transport, spool=None):
        if spool is None:
            spool = BoundedSpool(Path(directory), max_bytes=4096, max_age_seconds=3600.0)
        return TelemetryPublisher(transport, spool, PRODUCER, run_id="run-1")

    def test_the_worker_publishes_what_the_producer_handed_over(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            publisher = self.publisher(directory, transport)
            with TelemetryHandoff(publisher, capacity=4) as handoff:
                self.assertIs(handoff.submit(an_event(), now=10.0), HandoffOutcome.ACCEPTED)
            self.assertEqual(len(transport.sent), 1)
            self.assertEqual(publisher.counters.published, 1)
            self.assertEqual(handoff.counters.processed, 1)
            self.assertEqual(handoff.counters.worker_failures, 0)

    def test_submit_returns_at_once_while_the_transport_is_stalled(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = StalledTransport()
            handoff = TelemetryHandoff(self.publisher(directory, transport), capacity=2)
            handoff.start()
            try:
                self.assertIs(handoff.submit(an_event(), now=10.0), HandoffOutcome.ACCEPTED)
                self.assertTrue(transport.entered.wait(timeout=5.0), "the worker took the event")

                # The worker is now blocked inside the broker call and the queue
                # is empty, so the next two fill it and the third has nowhere to go.
                started = time.monotonic()
                outcomes = [handoff.submit(an_event(), now=10.0) for _ in range(3)]
                elapsed = time.monotonic() - started

                self.assertEqual(
                    outcomes,
                    [
                        HandoffOutcome.ACCEPTED,
                        HandoffOutcome.ACCEPTED,
                        HandoffOutcome.OVERFLOWED,
                    ],
                )
                self.assertLess(elapsed, 1.0, "the producer waited on a stalled broker")
                self.assertEqual(handoff.counters.overflowed, 1, "the loss is reported, not hidden")
            finally:
                transport.release.set()
                handoff.stop()

    def test_stop_reports_a_worker_it_could_not_end(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = StalledTransport()
            handoff = TelemetryHandoff(self.publisher(directory, transport), capacity=2)
            handoff.start()
            try:
                handoff.submit(an_event(), now=10.0)
                self.assertTrue(transport.entered.wait(timeout=5.0))
                self.assertFalse(
                    handoff.stop(timeout=0.2),
                    "a transport blocked in a call cannot be claimed as stopped",
                )
            finally:
                transport.release.set()
            self.assertTrue(handoff.stop(timeout=5.0))

    def test_a_failing_disk_stays_inside_the_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = FailingDiskSpool(Path(directory), max_bytes=4096, max_age_seconds=3600.0)
            publisher = self.publisher(directory, CollectingTransport(fail_times=1), spool=spool)
            with TelemetryHandoff(publisher, capacity=4) as handoff:
                self.assertIs(handoff.submit(an_event(), now=10.0), HandoffOutcome.ACCEPTED)
            counters = handoff.counters
            self.assertEqual(counters.worker_failures, 1)
            self.assertIn("disk full", counters.last_failure)
            self.assertEqual(counters.processed, 0, "a command that failed is not a processed one")

    def test_the_publisher_on_its_own_still_reaches_the_caller(self):
        """Why the boundary exists: the publisher itself makes no such promise."""
        with tempfile.TemporaryDirectory() as directory:
            spool = FailingDiskSpool(Path(directory), max_bytes=4096, max_age_seconds=3600.0)
            publisher = self.publisher(directory, CollectingTransport(fail_times=1), spool=spool)
            with self.assertRaises(OSError):
                publisher.publish(an_event(), now=10.0)

    def test_submitting_after_stop_is_refused_not_silently_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            handoff = TelemetryHandoff(self.publisher(directory, CollectingTransport()), capacity=2)
            handoff.start()
            self.assertTrue(handoff.stop())
            self.assertIs(handoff.submit(an_event(), now=10.0), HandoffOutcome.REFUSED)
            self.assertEqual(handoff.counters.refused, 1)

    def test_a_drain_request_runs_on_the_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport(fail_times=1)
            publisher = self.publisher(directory, transport)
            with TelemetryHandoff(publisher, capacity=4) as handoff:
                handoff.submit(an_event(), now=10.0)
                handoff.submit_drain(now=11.0)
            self.assertEqual(publisher.counters.spooled, 1)
            self.assertEqual(publisher.counters.drained, 1)
            self.assertEqual(handoff.counters.processed, 2)


if __name__ == "__main__":
    unittest.main()
