"""KAN-34 gateway-side UDS framing and non-blocking handoff tests."""

import threading
import time
import unittest
from io import BytesIO

from core.schema import DeviceState, StateEvent
from gateway.event_bridge import (
    BridgeOutcome,
    GatewayEventBridge,
    state_event_document,
    state_event_frame,
)
from telemetry.framing import read_frame


def event(reason="anomaly series started"):
    return StateEvent(
        "camera-1",
        DeviceState.NORMAL,
        DeviceState.SUSPICIOUS,
        reason,
        1_700_000_000.0,
        None,
    )


class RecordingTransport:
    def __init__(self):
        self.events = []
        self.failure = None

    def send(self, item):
        if self.failure is not None:
            raise RuntimeError(self.failure)
        self.events.append(item)


class BlockingTransport:
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()

    def send(self, _item):
        self.entered.set()
        self.release.wait(2)


def wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


class FramingTests(unittest.TestCase):
    def test_gateway_body_contains_exactly_the_six_approved_fields(self):
        document = state_event_document(event())
        self.assertEqual(
            set(document),
            {
                "device_id",
                "previous_state",
                "new_state",
                "reason",
                "timestamp",
                "expires_at",
            },
        )
        self.assertNotIn("event_id", document)
        self.assertNotIn("run_id", document)

    def test_frame_round_trips_through_the_shared_framing_contract(self):
        frame = state_event_frame(event("iki anomali penceresi"))
        body = read_frame(BytesIO(frame))
        self.assertIsNotNone(body)
        self.assertIn("iki anomali penceresi".encode(), body)
        self.assertIsNone(read_frame(BytesIO(b"")))

    def test_frame_is_deterministic_for_the_same_state_event(self):
        self.assertEqual(state_event_frame(event()), state_event_frame(event()))


class QueueTests(unittest.TestCase):
    def test_submit_to_a_stopped_bridge_is_refused_without_transport_io(self):
        transport = RecordingTransport()
        bridge = GatewayEventBridge(transport, capacity=1)
        self.assertEqual(bridge.submit(event()), BridgeOutcome.REFUSED)
        self.assertEqual(transport.events, [])
        self.assertEqual(bridge.counters.refused, 1)

    def test_worker_delivers_accepted_event(self):
        transport = RecordingTransport()
        with GatewayEventBridge(transport, capacity=2) as bridge:
            self.assertEqual(bridge.submit(event()), BridgeOutcome.ACCEPTED)
            wait_until(lambda: bridge.counters.delivered == 1)
        self.assertEqual(transport.events, [event()])

    def test_transport_failure_is_counted_and_does_not_escape_submit(self):
        transport = RecordingTransport()
        transport.failure = "host socket unavailable"
        with GatewayEventBridge(transport, capacity=2) as bridge:
            self.assertEqual(bridge.submit(event()), BridgeOutcome.ACCEPTED)
            wait_until(lambda: bridge.counters.failures == 1)
        self.assertEqual(bridge.counters.last_failure, "RuntimeError: host socket unavailable")

    def test_full_queue_overflow_is_reported_without_waiting_for_transport(self):
        transport = BlockingTransport()
        bridge = GatewayEventBridge(transport, capacity=1)
        bridge.start()
        try:
            self.assertEqual(bridge.submit(event("first")), BridgeOutcome.ACCEPTED)
            self.assertTrue(transport.entered.wait(1))
            self.assertEqual(bridge.submit(event("second")), BridgeOutcome.ACCEPTED)
            started = time.monotonic()
            self.assertEqual(bridge.submit(event("third")), BridgeOutcome.OVERFLOWED)
            self.assertLess(time.monotonic() - started, 0.1)
        finally:
            transport.release.set()
            self.assertTrue(bridge.stop())
        self.assertEqual(bridge.counters.overflowed, 1)


if __name__ == "__main__":
    unittest.main()
