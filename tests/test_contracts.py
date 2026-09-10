import json
import unittest
from dataclasses import replace

from core.schema import (
    SCHEMA_VERSION,
    Classification,
    DetectionResult,
    DeviceState,
    Direction,
    PacketTuple,
    StateEvent,
    TelemetryPayload,
)
from stubs.fake_detector import FakeDetector
from stubs.fake_features import fake_features
from stubs.fake_telemetry import fake_telemetry


class ContractTests(unittest.TestCase):
    def packet(self):
        return PacketTuple(
            1.0,
            "device-1",
            None,
            "192.168.1.2",
            50000,
            "198.51.100.1",
            443,
            6,
            2,
            60,
            Direction.EGRESS,
        )

    def test_packet_rejects_invalid_network_metadata(self):
        for field, value in (
            ("timestamp", float("nan")),
            ("src_ip", "not-an-ip"),
            ("src_port", 65536),
            ("dst_port", -1),
            ("protocol", 256),
            ("packet_length", 0),
            ("packet_length", True),
            ("direction", "EGRESS"),
            ("protocol", 17),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                replace(self.packet(), **{field: value})

    def test_icmp_allows_absent_ports(self):
        packet = replace(self.packet(), protocol=1, tcp_flags=0, src_port=None, dst_port=None)
        self.assertEqual(packet.packet_length, 60)

    def test_packet_identity_fields_are_text(self):
        for field, value in (("src_mac", []), ("src_ip", 1), ("dst_ip", b"abcd")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                replace(self.packet(), **{field: value})

    def test_features_reject_ambiguous_or_nonfinite_values(self):
        for changes in (
            {"feature_order": ("duplicate", "duplicate")},
            {"values": (1.0,)},
            {"values": (float("nan"), 1.0)},
            {"values": (float("inf"), 1.0)},
            {"window_end": 0},
            {"values": [1.0, 2.0]},
            {"feature_order": ("", "other")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(fake_features(), **changes)

    def test_threshold_boundary_and_model_only_result(self):
        result = FakeDetector(scores=(0.5,)).predict(fake_features())
        self.assertEqual(result.classification, Classification.ANOMALOUS)
        self.assertFalse(hasattr(result, "new_state"))
        with self.assertRaises(ValueError):
            replace(result, classification=Classification.NORMAL)

    def test_score_rejects_invalid_probability(self):
        for score in (-0.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(score=score), self.assertRaises(ValueError):
                DetectionResult("d", 0, "m", "v", score, Classification.NORMAL, 0.5)

    def test_state_expiry_and_enum_validation(self):
        event = StateEvent("d", DeviceState.SUSPICIOUS, DeviceState.QUARANTINED, "test", 10, 40)
        for changes in (
            {"expires_at": 10},
            {"timestamp": float("nan")},
            {"new_state": DeviceState.SUSPICIOUS},
            {"previous_state": "SUSPICIOUS"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(event, **changes)

    def test_telemetry_roundtrip_preserves_state_and_identity(self):
        payload = fake_telemetry()[1]
        wire = json.loads(json.dumps(payload.to_dict(), allow_nan=False))
        self.assertEqual(wire["event"]["new_state"], "QUARANTINED")
        event = wire.pop("event")
        event["previous_state"] = DeviceState(event["previous_state"])
        event["new_state"] = DeviceState(event["new_state"])
        self.assertEqual(TelemetryPayload(**wire, event=StateEvent(**event)), payload)
        with self.assertRaises(ValueError):
            replace(payload, schema_version="unknown")
        with self.assertRaises(ValueError):
            replace(payload, event={})
        self.assertEqual(payload.schema_version, SCHEMA_VERSION)

    def test_deterministic_stubs_and_exhaustion(self):
        def sequence():
            detector = FakeDetector()
            return [detector.predict(fake_features(window_start=i * 5)) for i in range(5)]

        self.assertEqual(sequence(), sequence())
        self.assertEqual(fake_telemetry(), fake_telemetry())
        detector = FakeDetector(scores=(0.1,))
        detector.predict(fake_features())
        with self.assertRaises(StopIteration):
            detector.predict(fake_features())


if __name__ == "__main__":
    unittest.main()
