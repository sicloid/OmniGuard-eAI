"""KAN-33 leakage accounting tests."""

import unittest
from measure import leakage


BOOT = "boot-1"


def delivery(timestamp, size):
    return leakage.SinkDelivery(BOOT, timestamp, size)


class LeakageTests(unittest.TestCase):
    def test_complete_run_reports_bounds_and_keeps_post_ack_separate(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [
                delivery(90, 10),
                delivery(100, 11),
                delivery(105, 12),
                delivery(150, 13),
                delivery(200, 14),
                delivery(210, 15),
                delivery(230, 16),
            ],
            sink_complete=True,
        )

        self.assertEqual(result.status, leakage.LeakageStatus.COMPLETE)
        self.assertEqual((result.before_t0.packets, result.before_t0.l3_bytes), (1, 10))
        self.assertEqual((result.t0_uncertain.packets, result.t0_uncertain.l3_bytes), (2, 23))
        self.assertEqual(
            (result.definite_pre_apply.packets, result.definite_pre_apply.l3_bytes),
            (1, 13),
        )
        self.assertEqual(
            (result.apply_uncertain.packets, result.apply_uncertain.l3_bytes),
            (2, 29),
        )
        self.assertEqual((result.post_ack.packets, result.post_ack.l3_bytes), (1, 16))
        self.assertEqual((result.lower_bound.packets, result.lower_bound.l3_bytes), (1, 13))
        self.assertEqual((result.upper_bound.packets, result.upper_bound.l3_bytes), (5, 65))

    def test_no_containment_is_censored_but_observed_traffic_is_preserved(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        result = leakage.summarize_leakage(
            t0,
            None,
            [delivery(105, 10), delivery(120, 20), delivery(130, 30)],
            sink_complete=True,
            censor_reason="detector_miss",
        )

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(result.censor_reason, "detector_miss")
        self.assertIsNone(result.lower_bound)
        self.assertIsNone(result.upper_bound)
        self.assertEqual(
            (result.uncontained_after_t0.packets, result.uncontained_after_t0.l3_bytes),
            (2, 50),
        )
        self.assertEqual(
            (result.observed_after_t0.packets, result.observed_after_t0.l3_bytes),
            (2, 50),
        )

    def test_incomplete_sink_never_becomes_a_zero_leakage_claim(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(t0, apply, [], sink_complete=False)

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(result.censor_reason, "sink_incomplete")
        self.assertIsNone(result.lower_bound)
        self.assertIsNone(result.upper_bound)

    def test_post_ack_delivery_is_not_folded_into_pre_containment_upper_bound(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [delivery(230, 99)],
            sink_complete=True,
        )

        self.assertEqual(result.upper_bound.packets, 0)
        self.assertEqual(result.post_ack.packets, 1)
        self.assertEqual(result.post_ack.l3_bytes, 99)

    def test_cross_boot_evidence_is_rejected(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        with self.assertRaises(ValueError):
            leakage.summarize_leakage(
                t0,
                apply,
                [leakage.SinkDelivery("other-boot", 150, 10)],
                sink_complete=True,
            )

    def test_invalid_intervals_and_sizes_are_rejected(self):
        with self.assertRaises(ValueError):
            leakage.MonotonicInterval(BOOT, 200, 100, "bad")
        with self.assertRaises(ValueError):
            leakage.SinkDelivery(BOOT, 100, 0)
        with self.assertRaises(ValueError):
            leakage.summarize_leakage(
                leakage.MonotonicInterval(BOOT, 100, 110, "t0"),
                leakage.MonotonicInterval(BOOT, 90, 95, "apply"),
                [],
                sink_complete=True,
            )


if __name__ == "__main__":
    unittest.main()
