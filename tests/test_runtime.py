"""Exercise the actual extractor/RF/state path without claiming the G8 gate."""

import tempfile
import unittest
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import DeviceState, Direction, PacketTuple
from gateway.controller import StateEnforcementController
from gateway.detector import CheckedDetector, DetectorSpec
from gateway.enforcer import CommandResult, DeviceBinding, NftEnforcer
from gateway.pipeline import WindowFeaturePipeline
from gateway.policy import DevicePolicy
from gateway.real_detector import RandomForestDetector
from gateway.runtime import GatewayCore
from model.artifact import LoadedArtifact, build_metadata


class MemoryNft:
    def __init__(self):
        self.active = set()

    def __call__(self, argv):
        words = tuple(argv)[5:]
        ip = words[-2] if words[:2] in (("get", "element"), ("delete", "element")) else None
        if words[:2] == ("list", "set"):
            return CommandResult(0)
        if words[:2] == ("get", "element"):
            return (
                CommandResult(0, "present")
                if ip in self.active
                else CommandResult(1, "", "No such element")
            )
        if words[:2] == ("add", "element"):
            self.active.add(words[-4])
            return CommandResult(0)
        if words[:2] == ("delete", "element"):
            self.active.discard(ip)
            return CommandResult(0)
        raise AssertionError(argv)


class Clock:
    now = 100.0


class Capture:
    def __init__(self, clock, items):
        self.clock = clock
        self.items = iter(items)

    def read_progress(self, timeout):
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            self.clock.now = item[1]
            return item
        self.clock.now = item.timestamp
        return item, None


def packet(timestamp):
    return PacketTuple(
        timestamp,
        "camera",
        None,
        "10.203.1.2",
        39028,
        "10.203.2.2",
        39027,
        17,
        0,
        60,
        Direction.EGRESS,
    )


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        from sklearn.ensemble import RandomForestClassifier

        # Distinguishable synthetic packet counts test wiring, not model quality.
        def row(count):
            return [count] + [0.0] * (len(FEATURE_ORDER) - 1)

        model = RandomForestClassifier(n_estimators=40, random_state=1, n_jobs=1)
        model.fit([row(1), row(2), row(10), row(11)] * 20, [0, 0, 1, 1] * 20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.joblib"
            path.write_bytes(b"synthetic-test-only")
            meta = build_metadata(
                path,
                model_id="rf-synthetic",
                model_version="test",
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_order=FEATURE_ORDER,
                threshold=0.5,
                training_manifest_sha256="a" * 64,
            )
        detector = CheckedDetector(
            RandomForestDetector(LoadedArtifact(meta, model)),
            DetectorSpec(
                meta.model_id,
                meta.model_version,
                meta.feature_schema_version,
                meta.feature_order,
                meta.threshold,
            ),
        )
        self.clock = Clock()
        self.clock.now = 100.0
        self.nft = MemoryNft()
        self.controller = StateEnforcementController(
            detector,
            DevicePolicy("camera", n=2, lease_seconds=3, max_lease=10),
            NftEnforcer(runner=self.nft),
            DeviceBinding("camera", "10.203.1.2"),
        )
        self.runtime = GatewayCore(
            WindowFeaturePipeline(100),
            self.controller,
            utc_clock=lambda: self.clock.now,
            monotonic_clock=lambda: self.clock.now,
        )

    def test_two_real_rf_windows_apply_then_timer_releases(self):
        items = [packet(100.1 + i * 0.04) for i in range(10)]
        items += [packet(105.1 + i * 0.04) for i in range(10)]
        items += [packet(110.1)]
        capture = Capture(self.clock, items)
        decisions = []
        for _ in items:
            decisions.extend(self.runtime.poll(capture).windows)
        self.assertEqual(len(decisions), 2)
        self.assertTrue(all(step.detection.score >= 0.5 for step in decisions))
        self.assertEqual(self.controller.policy.state, DeviceState.QUARANTINED)
        self.assertEqual(self.nft.active, {"10.203.1.2"})
        self.clock.now = 113.2
        step = self.runtime.poll(Capture(self.clock, [(None, 113.2)]))
        self.assertEqual(step.tick.events[-1].new_state, DeviceState.NORMAL)
        self.assertFalse(self.nft.active)

    def test_capture_failure_invalidates_anomaly_series(self):
        items = [packet(100.1 + i * 0.04) for i in range(10)] + [packet(105.1)]
        capture = Capture(self.clock, items)
        for _ in items:
            self.runtime.poll(capture)
        self.assertEqual(self.controller.policy.state, DeviceState.SUSPICIOUS)
        with self.assertRaises(OSError):
            self.runtime.poll(Capture(self.clock, [OSError("capture lost")]))
        self.assertEqual(self.controller.policy.state, DeviceState.NORMAL)
        self.assertEqual(self.controller.policy.resets["invalidated"], 1)
        self.assertFalse(self.nft.active)

    def test_expiry_and_loss_are_recorded_before_capture_failure(self):
        records = []
        self.runtime.on_control_step = records.append
        self.controller.policy.state = DeviceState.QUARANTINED
        self.controller.policy.deadline = 102.0
        self.nft.active.add("10.203.1.2")
        self.clock.now = 103.0
        self.runtime.pipeline.reset_generation += 1
        with self.assertRaisesRegex(OSError, "capture lost"):
            self.runtime.poll(Capture(self.clock, [OSError("capture lost")]))
        self.assertTrue(any(step.receipts for step in records))
        self.assertTrue(any(step.detector_error for step in records))
        self.assertFalse(self.nft.active)


if __name__ == "__main__":
    unittest.main()
