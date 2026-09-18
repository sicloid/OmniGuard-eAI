"""KAN-48 deterministic stub -> state -> enforcement integration tests."""

import unittest

from core.schema import DeviceState
from gateway.controller import ControlError, StateEnforcementController
from gateway.detector import CheckedDetector, DetectorSpec
from gateway.enforcer import CommandResult, DeviceBinding, EnforcementAction, EnforcementError, NftEnforcer
from gateway.policy import DevicePolicy
from stubs.fake_detector import FakeDetector
from stubs.fake_features import STUB_FEATURE_ORDER, STUB_FEATURE_VERSION, fake_features


class MemoryNft:
    def __init__(self):
        self.active = set()
        self.fail_add = False

    def __call__(self, argv):
        words = tuple(argv)[5:]
        if words[:2] == ("list", "set"):
            return CommandResult(0)
        if words[:2] == ("get", "element"):
            ip = words[-2]
            if ip in self.active:
                return CommandResult(0, "present", "")
            return CommandResult(1, "", "No such element")
        if words[:2] == ("add", "element"):
            if self.fail_add:
                return CommandResult(1, "", "synthetic add failure")
            self.active.add(words[-4])
            return CommandResult(0)
        if words[:2] == ("delete", "element"):
            self.active.discard(words[-2])
            return CommandResult(0)
        raise AssertionError(f"unexpected command: {argv}")


def checked(scores):
    return CheckedDetector(
        FakeDetector(scores=scores, threshold=0.5),
        DetectorSpec(
            "STUB-NOT-TRAINED",
            "0.1",
            STUB_FEATURE_VERSION,
            STUB_FEATURE_ORDER,
            0.5,
        ),
    )


def build(n, scores, *, lease=10.0):
    runner = MemoryNft()
    policy = DevicePolicy("cam", n=n, lease_seconds=lease, max_lease=20.0)
    enforcer = NftEnforcer(runner=runner)
    controller = StateEnforcementController(
        checked(scores),
        policy,
        enforcer,
        DeviceBinding("cam", "10.203.1.2"),
    )
    return controller, runner


def process(controller, start, *, now=None, mono=None):
    close = start + 5
    return controller.process(
        fake_features("cam", start),
        now=close if now is None else now,
        mono=close if mono is None else mono,
    )


class StateEnforcementE2ETests(unittest.TestCase):
    def test_n_one_two_three_quarantine_exactly_on_nth_anomaly(self):
        for n in (1, 2, 3):
            controller, runner = build(n, (0.9,) * n)
            for index in range(n):
                step = process(controller, 100 + 5 * index)
                expected = DeviceState.QUARANTINED if index == n - 1 else DeviceState.SUSPICIOUS
                self.assertEqual(controller.policy.state, expected)
                self.assertEqual(bool(runner.active), index == n - 1)
            self.assertEqual(step.receipts[-1].action, EnforcementAction.APPLIED)

    def test_invalid_observation_breaks_series_without_kernel_mutation(self):
        controller, runner = build(2, (0.9, 0.9))
        process(controller, 100)
        invalid = controller.invalidate(now=106, mono=106)
        self.assertEqual(invalid.events[-1].new_state, DeviceState.NORMAL)
        self.assertFalse(runner.active)
        process(controller, 105, now=110, mono=110)
        self.assertEqual(controller.policy.state, DeviceState.SUSPICIOUS)
        self.assertFalse(runner.active)

    def test_gap_and_stale_result_do_not_complete_n(self):
        gap, gap_runner = build(2, (0.9, 0.9))
        process(gap, 100)
        process(gap, 110)
        self.assertEqual(gap.policy.state, DeviceState.SUSPICIOUS)
        self.assertEqual(gap.policy.resets["gap"], 1)
        self.assertFalse(gap_runner.active)

        stale, stale_runner = build(1, (0.9,))
        step = process(stale, 100, now=107.6, mono=107.6)
        self.assertEqual(stale.policy.rejections["stale"], 1)
        self.assertEqual(step.receipts, ())
        self.assertFalse(stale_runner.active)

    def test_detector_failure_is_observation_loss_not_normal(self):
        controller, runner = build(2, (0.9,))
        process(controller, 100)
        step = process(controller, 105)
        self.assertIsNone(step.detection)
        self.assertIn("DetectorInferenceError", step.detector_error)
        self.assertEqual(controller.policy.state, DeviceState.NORMAL)
        self.assertEqual(controller.policy.resets["invalidated"], 1)
        self.assertFalse(runner.active)

    def test_explicit_release_and_episode_rearm_are_enforced(self):
        controller, runner = build(1, (0.9, 0.9, 0.9))
        first = process(controller, 100)
        self.assertEqual(first.receipts[-1].action, EnforcementAction.APPLIED)
        released = controller.release(now=106, mono=106)
        self.assertEqual(released.receipts[-1].action, EnforcementAction.RELEASED)
        self.assertFalse(runner.active)

        process(controller, 105, now=110, mono=110)
        self.assertEqual(controller.policy.state, DeviceState.NORMAL)
        self.assertFalse(runner.active)

        controller.rearm()
        again = process(controller, 110, now=115, mono=115)
        self.assertEqual(again.receipts[-1].action, EnforcementAction.APPLIED)
        self.assertTrue(runner.active)

    def test_tick_releases_kernel_state_when_policy_lease_expires(self):
        controller, runner = build(1, (0.9,), lease=5.0)
        process(controller, 100)
        step = controller.tick(now=110, mono=110)
        self.assertEqual(step.events[-1].new_state, DeviceState.NORMAL)
        self.assertEqual(step.receipts[-1].action, EnforcementAction.RELEASED)
        self.assertFalse(runner.active)

    def test_rearm_refuses_a_lingering_kernel_block(self):
        controller, runner = build(1, (0.9,))
        runner.active.add("10.203.1.2")
        with self.assertRaises(ControlError):
            controller.rearm()

    def test_enforcement_failure_is_not_hidden_as_policy_success(self):
        controller, runner = build(1, (0.9,))
        runner.fail_add = True
        with self.assertRaises(EnforcementError):
            process(controller, 100)
        self.assertEqual(controller.policy.state, DeviceState.QUARANTINED)
        self.assertFalse(runner.active)


if __name__ == "__main__":
    unittest.main()
