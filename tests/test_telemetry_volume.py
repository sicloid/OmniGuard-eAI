import io
import socket
import threading
import unittest
from pathlib import Path

from lab.kan43_sealed_run import policy_events
from lab.mqtt_wire_counter import MqttWireCounter
from telemetry.accounting import (
    MQTT_APPLICATION,
    MQTT_PUBLISH_PACKET,
    PAYLOAD_JSON,
    UDS_FRAME,
    CountingAdapter,
    CountingStream,
    CountingTransport,
    VolumeError,
    VolumeLedger,
    mqtt_publish_packet_bytes,
)
from telemetry.canonical import canonical_bytes
from telemetry.framing import HEADER_SIZE, encode_frame, read_frame
from telemetry.outcomes import HandoffOutcome
from telemetry.publisher import Acknowledgement, TransportError

PAYLOAD = {
    "schema_version": "0.1.0",
    "run_id": "run-1",
    "event_id": "0c8c393e-8b98-5162-9afe-bec21f5d1345",
    "event": {
        "device_id": "cam-1",
        "previous_state": "NORMAL",
        "new_state": "QUARANTINED",
        "reason": "consecutive eligible anomalies",
        "timestamp": 1789910095.159,
        "expires_at": 1789910125.159,
    },
}


ENVELOPE = {
    "envelope_version": "1",
    "payload": PAYLOAD,
    "producer": {
        "boot_id": "boot-1",
        "boot_started_at": 1789910000.0,
        "producer_id": "gateway-1",
    },
    "sequence": 1,
}


class FakeTransport:
    def __init__(self, acknowledgement=Acknowledgement.ACKED, error=None):
        self.acknowledgement = acknowledgement
        self.error = error
        self.calls = []

    def publish(self, topic, payload, *, qos, retain):
        self.calls.append((topic, payload, qos, retain))
        if self.error is not None:
            raise self.error
        return self.acknowledgement


class LedgerTests(unittest.TestCase):
    def test_a_boundary_nobody_observed_is_absent_and_named(self):
        ledger = VolumeLedger("run-1")
        ledger.record(UDS_FRAME, 120)
        summary = ledger.summary()
        self.assertEqual(list(summary["boundaries"]), [UDS_FRAME])
        self.assertEqual(
            summary["not_observed"], [PAYLOAD_JSON, MQTT_APPLICATION, MQTT_PUBLISH_PACKET]
        )
        self.assertNotIn(PAYLOAD_JSON, summary["boundaries"])

    def test_sizes_are_kept_per_observation_not_only_as_a_total(self):
        ledger = VolumeLedger("run-1")
        for size in (100, 300, 200):
            ledger.record(UDS_FRAME, size)
        boundary = ledger.summary()["boundaries"][UDS_FRAME]
        self.assertEqual(boundary["observations"], 3)
        self.assertEqual(boundary["bytes_total"], 600)
        self.assertEqual((boundary["bytes_min"], boundary["bytes_max"]), (100, 300))
        self.assertEqual(boundary["bytes_mean"], 200)

    def test_a_byte_count_that_cannot_describe_traffic_is_refused(self):
        ledger = VolumeLedger("run-1")
        for bad in (-1, True, 1.5, "120"):
            with self.subTest(bad=bad), self.assertRaises(VolumeError):
                ledger.record(UDS_FRAME, bad)
        with self.assertRaises(VolumeError):
            ledger.record("wire", 10)
        with self.assertRaises(VolumeError):
            VolumeLedger("  ")

    def test_the_payload_is_sized_in_the_encoding_the_wire_would_use(self):
        ledger = VolumeLedger("run-1")
        size = ledger.record_payload(PAYLOAD)
        self.assertEqual(size, len(canonical_bytes(PAYLOAD)))
        self.assertEqual(ledger.summary()["boundaries"][PAYLOAD_JSON]["bytes_total"], size)

    def test_a_uds_frame_includes_its_length_prefix(self):
        ledger = VolumeLedger("run-1")
        body = canonical_bytes(PAYLOAD["event"])
        self.assertEqual(ledger.record_uds_frame(body), HEADER_SIZE + len(body))
        self.assertEqual(len(encode_frame(body)), HEADER_SIZE + len(body))
        with self.assertRaises(VolumeError):
            ledger.record_uds_frame("not bytes")

    def test_the_derived_boundary_says_so(self):
        ledger = VolumeLedger("run-1")
        ledger.record(MQTT_PUBLISH_PACKET, 200)
        ledger.record(MQTT_APPLICATION, 180)
        boundaries = ledger.summary()["boundaries"]
        self.assertTrue(boundaries[MQTT_PUBLISH_PACKET]["derived"])
        self.assertFalse(boundaries[MQTT_APPLICATION]["derived"])


class PublishPacketTests(unittest.TestCase):
    def test_a_small_publish_is_fixed_header_topic_packet_id_and_body(self):
        topic = "omniguard/state/v2/cam-1"
        payload = b"x" * 10
        variable = 2 + len(topic) + 2 + len(payload)
        self.assertEqual(mqtt_publish_packet_bytes(topic, payload), 1 + 1 + variable)

    def test_the_remaining_length_field_grows_with_the_body(self):
        topic = "t"
        # Remaining length uses one byte below 128, two below 16384, three beyond.
        head = 2 + len(topic) + 2
        small = mqtt_publish_packet_bytes(topic, b"x" * (127 - head))
        large = mqtt_publish_packet_bytes(topic, b"x" * (128 - head))
        self.assertEqual(small, 1 + 1 + 127)
        self.assertEqual(large, 1 + 2 + 128)
        huge = mqtt_publish_packet_bytes(topic, b"x" * (16384 - head))
        self.assertEqual(huge, 1 + 3 + 16384)

    def test_qos0_spends_no_packet_id(self):
        topic = "omniguard/state/v2/cam-1"
        with_id = mqtt_publish_packet_bytes(topic, b"x" * 10, qos=1)
        without = mqtt_publish_packet_bytes(topic, b"x" * 10, qos=0)
        self.assertEqual(with_id - without, 2)

    def test_a_multibyte_topic_is_counted_in_utf8_bytes(self):
        self.assertEqual(
            mqtt_publish_packet_bytes("ö", b"x") - mqtt_publish_packet_bytes("o", b"x"), 1
        )


class CountingTransportTests(unittest.TestCase):
    def setUp(self):
        self.ledger = VolumeLedger("run-1")
        self.topic = "omniguard/state/v2/cam-1"
        self.body = canonical_bytes(ENVELOPE)

    def publish(self, transport):
        return CountingTransport(transport, self.ledger).publish(
            self.topic, self.body, qos=1, retain=False
        )

    def test_the_wrapper_records_without_changing_what_the_transport_sees(self):
        transport = FakeTransport()
        self.assertIs(self.publish(transport), Acknowledgement.ACKED)
        self.assertEqual(transport.calls, [(self.topic, self.body, 1, False)])
        boundaries = self.ledger.summary()["boundaries"]
        self.assertEqual(
            boundaries[MQTT_APPLICATION]["bytes_total"], len(self.topic) + len(self.body)
        )
        self.assertEqual(
            boundaries[MQTT_PUBLISH_PACKET]["bytes_total"],
            mqtt_publish_packet_bytes(self.topic, self.body),
        )

    def test_only_an_acknowledged_publish_counts_as_acknowledged(self):
        self.publish(FakeTransport(Acknowledgement.QUEUED))
        events = self.ledger.summary()["events"]
        self.assertEqual(events["offered_to_transport"], 1)
        self.assertEqual(events["broker_acknowledged"], 0)

    def test_a_failed_publish_keeps_the_bytes_it_offered_and_is_not_swallowed(self):
        with self.assertRaises(TransportError):
            self.publish(FakeTransport(error=TransportError("broker down")))
        summary = self.ledger.summary()
        self.assertEqual(summary["boundaries"][MQTT_APPLICATION]["observations"], 1)
        self.assertEqual(summary["events"]["transport_failures"], 1)
        self.assertEqual(summary["events"]["broker_acknowledged"], 0)

    def test_the_nested_payload_is_sized_where_it_actually_sits(self):
        self.publish(FakeTransport())
        boundaries = self.ledger.summary()["boundaries"]
        self.assertEqual(boundaries[PAYLOAD_JSON]["bytes_total"], len(canonical_bytes(PAYLOAD)))
        # The envelope costs more than the document it carries, and the difference
        # is what wrapping added rather than an estimate of it.
        self.assertGreater(
            boundaries[MQTT_APPLICATION]["bytes_total"], boundaries[PAYLOAD_JSON]["bytes_total"]
        )

    def test_a_body_with_no_nested_payload_is_counted_not_passed_over(self):
        CountingTransport(FakeTransport(), self.ledger).publish(
            self.topic, b"not an envelope", qos=1, retain=False
        )
        summary = self.ledger.summary()
        self.assertEqual(summary["events"]["bodies_without_a_nested_payload"], 1)
        self.assertNotIn(PAYLOAD_JSON, summary["boundaries"])
        self.assertIn(PAYLOAD_JSON, summary["not_observed"])

    def test_sizing_the_nested_payload_can_be_turned_off(self):
        CountingTransport(FakeTransport(), self.ledger, size_nested_payload=False).publish(
            self.topic, self.body, qos=1, retain=False
        )
        summary = self.ledger.summary()
        self.assertIn(PAYLOAD_JSON, summary["not_observed"])
        self.assertEqual(summary["events"]["bodies_without_a_nested_payload"], 0)

    def test_the_ledger_must_be_a_ledger(self):
        with self.assertRaises(VolumeError):
            CountingTransport(FakeTransport(), {})


class CountingStreamTests(unittest.TestCase):
    def test_it_counts_the_framed_bytes_a_reader_consumed(self):
        body = canonical_bytes(PAYLOAD)
        stream = CountingStream(io.BytesIO(encode_frame(body)))
        self.assertEqual(read_frame(stream), body)
        self.assertEqual(stream.bytes_read, HEADER_SIZE + len(body))

    def test_an_empty_stream_reads_nothing(self):
        stream = CountingStream(io.BytesIO(b""))
        self.assertIsNone(read_frame(stream))
        self.assertEqual(stream.bytes_read, 0)


class RefusingSink:
    def __init__(self, outcome=HandoffOutcome.ACCEPTED):
        self.outcome = outcome
        self.events = []

    def submit(self, event, *, now):
        self.events.append(event)
        return self.outcome


class CountingAdapterTests(unittest.TestCase):
    """The stream half needs no socket, so the counting is proved on every platform."""

    def adapter(self, sink, ledger):
        return CountingAdapter(
            Path("unused.sock"),
            sink,
            clock=lambda: 10.0,
            require_peer_credentials=False,
            ledger=ledger,
        )

    def event_body(self) -> bytes:
        return canonical_bytes(PAYLOAD["event"])

    def test_every_frame_is_counted_with_its_length_prefix(self):
        ledger = VolumeLedger("run-1")
        sink = RefusingSink()
        body = self.event_body()
        self.adapter(sink, ledger).serve_stream(io.BytesIO(encode_frame(body) * 2))
        boundary = ledger.summary()["boundaries"][UDS_FRAME]
        self.assertEqual(boundary["observations"], 2)
        self.assertEqual(boundary["bytes_total"], 2 * (HEADER_SIZE + len(body)))
        self.assertEqual(len(sink.events), 2)

    def test_a_frame_the_sink_refused_still_crossed_the_socket(self):
        ledger = VolumeLedger("run-1")
        sink = RefusingSink(HandoffOutcome.OVERFLOWED)
        body = self.event_body()
        adapter = self.adapter(sink, ledger)
        adapter.serve_stream(io.BytesIO(encode_frame(body)))
        self.assertEqual(ledger.summary()["boundaries"][UDS_FRAME]["observations"], 1)
        self.assertEqual(adapter.counters.refused_by_sink, 1)
        self.assertEqual(adapter.counters.accepted, 0)

    def test_an_undecodable_body_is_counted_as_traffic_too(self):
        ledger = VolumeLedger("run-1")
        adapter = self.adapter(RefusingSink(), ledger)
        adapter.serve_stream(io.BytesIO(encode_frame(b"{not json")))
        self.assertEqual(ledger.summary()["boundaries"][UDS_FRAME]["observations"], 1)
        self.assertEqual(adapter.counters.undecodable_bodies, 1)

    def test_the_ledger_must_be_a_ledger(self):
        with self.assertRaises(VolumeError):
            self.adapter(RefusingSink(), {})


class EchoServer:
    """The smallest thing that can be on the other end of a counted connection."""

    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.listen(4)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.socket.getsockname()[1]

    def _serve(self) -> None:
        while True:
            try:
                connection, _ = self.socket.accept()
            except OSError:
                return
            threading.Thread(target=self._echo, args=(connection,), daemon=True).start()

    def _echo(self, connection: socket.socket) -> None:
        with connection:
            while True:
                try:
                    chunk = connection.recv(65536)
                except OSError:
                    return
                if not chunk:
                    return
                connection.sendall(chunk)

    def stop(self) -> None:
        self.socket.close()


class WireCounterTests(unittest.TestCase):
    def setUp(self):
        self.echo = EchoServer()
        self.addCleanup(self.echo.stop)
        self.counter = MqttWireCounter(("127.0.0.1", 0), ("127.0.0.1", self.echo.port))
        self.counter.start()
        self.addCleanup(self.counter.stop)

    def connect(self) -> socket.socket:
        connection = socket.create_connection(("127.0.0.1", self.counter.port), timeout=5)
        connection.settimeout(5)
        self.addCleanup(connection.close)
        return connection

    def read_exactly(self, connection: socket.socket, count: int) -> bytes:
        chunks = b""
        while len(chunks) < count:
            chunk = connection.recv(count - len(chunks))
            if not chunk:
                break
            chunks += chunk
        return chunks

    def test_it_counts_both_directions_of_a_real_connection(self):
        connection = self.connect()
        connection.sendall(b"a" * 200)
        self.assertEqual(len(self.read_exactly(connection, 200)), 200)
        report = self.counter.report()
        self.assertEqual(report["to_broker"]["total"], 200)
        self.assertEqual(report["from_broker"]["total"], 200)
        self.assertEqual(report["connections"], 1)

    def test_marks_keep_handshake_bytes_apart_from_per_event_bytes(self):
        connection = self.connect()
        connection.sendall(b"c" * 50)
        self.read_exactly(connection, 50)
        self.counter.mark("publish")
        connection.sendall(b"p" * 120)
        self.read_exactly(connection, 120)
        segments = self.counter.report()["to_broker"]["segments"]
        self.assertEqual(segments["connect"], 50)
        self.assertEqual(segments["publish"], 120)

    def test_a_segment_name_must_be_usable(self):
        for bad in ("", "   ", 3):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.counter.mark(bad)

    def test_the_report_names_what_it_does_not_count(self):
        report = self.counter.report()
        self.assertIn("IP/TCP headers", report["not_counted"])
        self.assertIn("TCP payload bytes", report["counted"])


class SealedRunScheduleTests(unittest.TestCase):
    """The sealed run's events come from the real policy; the schedule must reach N."""

    def test_each_cycle_quarantines_and_expires_through_the_real_policy(self):
        events = policy_events(3, 43, end=1_790_000_000.0)
        transitions = [(e.previous_state.value, e.new_state.value) for e in events]
        cycle = [("NORMAL", "SUSPICIOUS"), ("SUSPICIOUS", "QUARANTINED"), ("QUARANTINED", "NORMAL")]
        self.assertEqual(transitions, cycle * 3)
        self.assertTrue(all(e.expires_at for e in events[1::3]))

    def test_no_timestamp_is_later_than_the_run_that_sends_it(self):
        events = policy_events(20, 43, end=1_790_000_000.0)
        self.assertLess(max(e.timestamp for e in events), 1_790_000_000.0)

    def test_the_schedule_is_reproducible_from_its_seed(self):
        first = policy_events(2, 43, end=1_790_000_000.0)
        self.assertEqual(first, policy_events(2, 43, end=1_790_000_000.0))
        self.assertNotEqual(first, policy_events(2, 44, end=1_790_000_000.0))


if __name__ == "__main__":
    unittest.main()
