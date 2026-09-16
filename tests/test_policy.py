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
        for age in (0, -1):
            with self.assertRaises(ValueError):
                DevicePolicy("cam", n=1, lease_seconds=10, max_lease=20, max_result_age=age)

    def test_release_on_normal_is_rejected_without_disarming(self):
        p = self.policy()
        with self.assertRaises(ValueError):
            p.release(now=100, mono=100)
        self.assertTrue(p.armed)
        self.feed(p, 100)
        events = self.feed(p, 105)
        self.assertEqual(events[-1].new_state, DeviceState.QUARANTINED)

    def test_release_at_expiry_returns_only_expiry_event(self):
        p = self.policy(1)
        self.feed(p, 100)
        events = p.release(now=120, mono=120)
        self.assertEqual([event.reason for event in events], ["lease expired; not a clean bill"])

    def test_reconcile_exits_active_quarantine_after_clock_regression(self):
        p = self.policy(1)
        self.feed(p, 100)
        for call in (p.tick, p.release, p.invalidate):
            with self.subTest(call=call.__name__), self.assertRaises(ValueError):
                call(now=106, mono=50)
        events = p.reconcile(now=106, mono=50)
        self.assertEqual(events[-1].new_state, DeviceState.NORMAL)
        self.assertIn("reconciled", events[-1].reason)
        self.assertIsNone(p.deadline)
        self.assertFalse(p.armed)
        p.rearm()
        self.assertEqual(p.tick(now=107, mono=51), ())

    def test_rejected_clock_does_not_mutate_series(self):
        p = self.policy(3)
        self.feed(p, 100)
        self.feed(p, 105)
        with self.assertRaises(ValueError):
            p.tick(now=111, mono=100)
        self.assertEqual((p.count, p.state), (2, DeviceState.SUSPICIOUS))

    def test_composed_freshness_budget_and_diagnostics(self):
        p = self.policy()
        p.observe(result(100), now=107.0, mono=107.0)
        events = p.observe(result(105), now=112.0, mono=112.0)
        self.assertEqual(events[-1].new_state, DeviceState.QUARANTINED)
        self.assertEqual(p.rejections["stale"], 0)

        stale = self.policy()
        stale.observe(result(100), now=107.6, mono=107.6)
        self.assertEqual((stale.count, stale.rejections["stale"]), (0, 1))

    def test_rejection_and_reset_reasons_are_counted(self):
        p = self.policy(3)
        self.feed(p, 100)
        p.observe(result(101), now=106, mono=106)
        p.observe(result(120), now=110, mono=110)
        self.feed(p, 105)
        self.feed(p, 105)
        self.feed(p, 115)
        self.feed(p, 120, version="2")
        p.invalidate(now=126, mono=126)
        self.assertEqual(
            p.rejections,
            {"misaligned": 1, "future": 1, "stale": 0, "duplicate": 1},
        )
        self.assertEqual(
            p.resets,
            {"gap": 1, "model_change": 1, "invalidated": 1},
        )

    def test_max_lease_is_retained(self):
        self.assertEqual(self.policy().max_lease, 20)
