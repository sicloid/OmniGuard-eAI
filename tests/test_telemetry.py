"""ADR-0003 framing, identity, spool and publisher behaviour.

A fake transport proves the fault behaviour, not delivery. Real broker and
database evidence is a separate Compose run under KAN-50.
"""

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from core.schema import SCHEMA_VERSION, DeviceState, StateEvent
from telemetry.canonical import CanonicalError, canonical_bytes
from telemetry.framing import (
    MAX_FRAME,
    FrameError,
    FrameTooLarge,
    IncompleteFrame,
    encode_frame,
    read_frame,
)
from telemetry.identity import (
    EventIdentity,
    IdentityError,
    ProducerIdentity,
    SequenceCounter,
    event_id,
    validate_device_id,
)
from telemetry.publisher import (
    QOS,
    RETAIN,
    TelemetryPublisher,
    TransportError,
    topic_for,
)
from telemetry.spool import BoundedSpool

PRODUCER = ProducerIdentity("gateway-01", "3f2b0c0e-0000-4000-8000-000000000001", 1_700_000_000.0)


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
    def __init__(self, fail_times: int = 0):
        self.sent: list[tuple[str, bytes, int, bool]] = []
        self.fail_times = fail_times

    def publish(self, topic, payload, *, qos, retain):
        if self.fail_times:
            self.fail_times -= 1
            raise TransportError("broker unavailable")
        self.sent.append((topic, payload, qos, retain))


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
                spool.append(sequence, b"x" * 90, now=10.0)
            pending = spool.pending()
            counters = spool.counters()
            self.assertEqual([entry.sequence for entry in pending], [2, 3])
            self.assertEqual(counters.dropped_events, 1)
            self.assertEqual(counters.dropped_by_bytes, 1)
            self.assertEqual(counters.dropped_by_age, 0)
            self.assertEqual(counters.first_dropped_sequence, 1)
            self.assertEqual(counters.last_dropped_sequence, 1)

    def test_age_bound_evicts_and_is_attributed_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = self.spool(directory, max_age_seconds=5.0)
            spool.append(1, b"old", now=100.0)
            spool.append(2, b"new", now=108.0)
            self.assertEqual([entry.sequence for entry in spool.pending()], [2])
            self.assertEqual(spool.counters().dropped_by_age, 1)
            self.assertEqual(spool.counters().dropped_by_bytes, 0)

    def test_an_entry_larger_than_the_budget_is_refused_not_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = self.spool(directory, max_bytes=64)
            spool.append(1, b"keep", now=1.0)
            self.assertFalse(spool.append(2, b"x" * 65, now=1.0))
            self.assertEqual([entry.sequence for entry in spool.pending()], [1])
            self.assertEqual(spool.counters().rejected_oversize, 1)
            self.assertEqual(spool.counters().dropped_events, 0)

    def test_counters_survive_reopening_the_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self.spool(directory, max_bytes=100)
            first.append(1, b"x" * 60, now=1.0)
            first.append(2, b"x" * 60, now=1.0)
            self.assertEqual(first.counters().dropped_events, 1)
            reopened = self.spool(directory, max_bytes=100)
            self.assertEqual(reopened.counters().dropped_events, 1)
            self.assertEqual(reopened.counters().first_dropped_sequence, 1)


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
            self.assertEqual(topic, "omniguard/state/v1/lan-device-07")
            self.assertEqual((qos, retain), (QOS, RETAIN))
            document = json.loads(payload.decode("utf-8"))
            self.assertEqual(document["schema_version"], SCHEMA_VERSION)
            self.assertEqual(document["event_id"], outcome.event_id)

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

    def test_crash_before_the_spool_write_produces_a_duplicate(self):
        """Documents the accepted limit in ADR-0003; passing is not a fix.

        A sequence consumed but lost before it reached the spool is not
        reproduced, so the regenerated event carries a different identity and the
        consumer stores it twice. KAN-50 reports how often this happens.
        """
        with tempfile.TemporaryDirectory() as directory:
            transport = CollectingTransport()
            publisher, _ = self.publisher(directory, transport)
            event = an_event()
            first = publisher.publish(event, now=10.0)
            resubmitted = publisher.publish(event, now=10.0)
            self.assertNotEqual(first.event_id, resubmitted.event_id)


class TopicTests(unittest.TestCase):
    def test_prefix_is_versioned_so_a_new_envelope_takes_a_new_topic(self):
        self.assertEqual(topic_for("dev-1"), "omniguard/state/v1/dev-1")


if __name__ == "__main__":
    unittest.main()
