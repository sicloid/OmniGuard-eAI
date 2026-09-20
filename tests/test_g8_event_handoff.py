"""The G10 event tap must stay optional on the telemetry-off G8 core path."""

import unittest
from unittest.mock import patch

from core.schema import DeviceState, StateEvent
from gateway.controller import ControlStep
from gateway.event_bridge import BridgeOutcome
from lab.g8_core import _record_step


class FakeBridge:
    def __init__(self):
        self.events = []

    def submit(self, event):
        self.events.append(event)
        return BridgeOutcome.ACCEPTED


class G8EventHandoffTests(unittest.TestCase):
    def test_real_controller_event_is_offered_only_when_bridge_is_enabled(self):
        event = StateEvent(
            "camera", DeviceState.SUSPICIOUS, DeviceState.QUARANTINED, "N anomalies", 10.0, 16.0
        )
        step = ControlStep(None, (event,), ())
        bridge = FakeBridge()
        with patch("lab.g8_core._record") as record:
            _record_step(step)
            self.assertEqual(record.call_count, 1)
            _record_step(step, bridge)
        self.assertEqual(bridge.events, [event])
        self.assertEqual(record.call_args_list[-1].args, ("event_handoff",))
        self.assertEqual(record.call_args_list[-1].kwargs, {"outcome": "ACCEPTED"})


if __name__ == "__main__":
    unittest.main()
