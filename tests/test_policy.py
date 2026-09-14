import unittest

from core.schema import Classification, DetectionResult, DeviceState
from gateway.policy import DevicePolicy


def result(t, anomalous=True, device="cam", version="1"):
    return DetectionResult(
        device,
        t,
        "model",
        version,
        1.0 if anomalous else 0.0,
        Classification.ANOMALOUS if anomalous else Classification.NORMAL,
        0.5,
    )


class PolicyTests(unittest.TestCase):
    def policy(self, n=2):
        return DevicePolicy("cam", n=n, lease_seconds=10, max_lease=20)

    def feed(self, p, t, **kw):
        return p.observe(result(t, **kw), now=t + 5, mono=t + 5)

    def test_n_one_two_three(self):
        for n in (1, 2, 3):
            p = self.policy(n)
            for i in range(n):
                events = self.feed(p, 100 + 5 * i)
                self.assertEqual(
                    p.state, DeviceState.QUARANTINED if i == n - 1 else DeviceState.SUSPICIOUS
                )
            self.assertEqual(events[-1].expires_at, 115 + 5 * (n - 1))

    def test_gap_benign_invalid_and_model_change_break_series(self):
        for kind in ("gap", "benign", "invalid", "model"):
            p = self.policy(3)
            self.feed(p, 100)
            self.feed(p, 105)
            if kind == "gap":
                self.feed(p, 115)
            elif kind == "benign":
                self.feed(p, 110, anomalous=False)
            elif kind == "invalid":
                p.invalidate(now=115, mono=115)
            else:
                self.feed(p, 110, version="2")
            self.assertLess(p.count, 3)
            self.assertNotEqual(p.state, DeviceState.QUARANTINED)

    def test_duplicate_future_stale_do_not_quarantine(self):
        for t, now in ((100, 105), (110, 110), (105, 120)):
            p = self.policy()
            self.feed(p, 100)
            p.observe(result(t), now=now, mono=120)
            self.assertEqual(p.count, 0)
            self.assertNotEqual(p.state, DeviceState.QUARANTINED)

    def test_lease_does_not_renew_and_expires_without_inference(self):
        p = self.policy(1)
        self.feed(p, 100)
        self.feed(p, 105)
        self.assertEqual(p.deadline, 115)
        events = p.tick(now=50, mono=115)  # UTC rollback cannot extend duration
        self.assertEqual(events[-1].new_state, DeviceState.NORMAL)
        self.assertFalse(p.armed)
        self.feed(p, 115)
        self.assertEqual(p.state, DeviceState.NORMAL)

    def test_release_and_rearm_cannot_reuse_old_window(self):
        p = self.policy(1)
        self.feed(p, 100)
        p.release(now=106, mono=106)
        p.rearm()
        p.observe(result(100), now=106, mono=106)
        self.assertEqual(p.state, DeviceState.NORMAL)
        self.feed(p, 105)
        self.assertEqual(p.state, DeviceState.QUARANTINED)

    def test_fault_does_not_extend_lease(self):
        p = self.policy(1)
        self.feed(p, 100)
        p.invalidate(now=110, mono=110)
        self.assertEqual(p.deadline, 115)
        with self.assertRaises(ValueError):
            p.tick(now=111, mono=100)
        self.assertEqual(p.deadline, 115)
        p.tick(now=120, mono=120)
        self.assertEqual(p.state, DeviceState.NORMAL)

    def test_device_and_config_rejected(self):
        p = self.policy()
        with self.assertRaises(ValueError):
            self.feed(p, 100, device="other")
        for n in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                self.policy(n)
        with self.assertRaises(ValueError):
            DevicePolicy("cam", n=1, lease_seconds=30, max_lease=20)
