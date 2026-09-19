"""KAN-33 leakage accounting tests."""

# Ruff cannot infer the flat-layout `measure` package consistently here; keep the
# explicit project import and suppress only import-section sorting for this test.
# ruff: noqa: I001

import unittest

import measure.leakage as leakage


BOOT = "boot-1"


def delivery(timestamp, size):
    return leakage.SinkDelivery(BOOT, timestamp, size)


def source_window(begin=90, end=240):
    return leakage.MonotonicInterval(BOOT, begin, end, "source attempts")


def sink_window(begin=80, end=250):
    return leakage.MonotonicInterval(BOOT, begin, end, "independent sink observation")


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
            source_attempt_window=source_window(),
            sink_window=sink_window(),
            source_attempted_after_ack=True,
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
            source_attempt_window=source_window(),
            sink_window=sink_window(),
            source_attempted_after_ack=None,
            censor_reason="detector_miss",
        )

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(result.censor_reason, "detector_miss,no_containment_ack")
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

    def test_multiple_censor_causes_are_preserved(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        result = leakage.summarize_leakage(
            t0,
            None,
            [delivery(120, 20)],
            sink_complete=False,
            source_attempt_window=source_window(),
            sink_window=sink_window(),
            source_attempted_after_ack=None,
            censor_reason="detector_miss",
        )

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(
            result.censor_reason,
            "detector_miss,sink_incomplete,no_containment_ack",
        )
        self.assertEqual(result.uncontained_after_t0.packets, 1)

    def test_incomplete_sink_never_becomes_a_zero_leakage_claim(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [],
            sink_complete=False,
            source_attempt_window=source_window(),
            sink_window=sink_window(),
            source_attempted_after_ack=True,
        )

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
            source_attempt_window=source_window(),
            sink_window=sink_window(),
            source_attempted_after_ack=True,
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
                source_attempt_window=source_window(),
                sink_window=sink_window(),
                source_attempted_after_ack=True,
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
                source_attempt_window=source_window(),
                sink_window=sink_window(),
                source_attempted_after_ack=True,
            )

    def test_missing_source_evidence_censors_empty_zero_result(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [],
            sink_complete=True,
            source_attempt_window=None,
            sink_window=sink_window(),
            source_attempted_after_ack=None,
        )

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(result.censor_reason, "no_source_attempts")
        self.assertIsNone(result.lower_bound)

    def test_sink_window_must_cover_source_attempt_window(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [],
            sink_complete=True,
            source_attempt_window=source_window(),
            sink_window=sink_window(end=210),
            source_attempted_after_ack=True,
        )

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(result.censor_reason, "sink_window_short")

    def test_source_must_attempt_after_containment_ack(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 110, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [],
            sink_complete=True,
            source_attempt_window=source_window(end=210),
            sink_window=sink_window(),
            source_attempted_after_ack=False,
        )

        self.assertEqual(result.status, leakage.LeakageStatus.CENSORED)
        self.assertEqual(result.censor_reason, "source_inactive_after_ack")

    def test_overlap_is_explicit_when_lower_bound_is_structurally_empty(self):
        t0 = leakage.MonotonicInterval(BOOT, 100, 210, "reference submission")
        apply = leakage.MonotonicInterval(BOOT, 200, 220, "enforcer call + readback")
        result = leakage.summarize_leakage(
            t0,
            apply,
            [],
            sink_complete=True,
            source_attempt_window=source_window(),
            sink_window=sink_window(),
            source_attempted_after_ack=True,
        )

        self.assertTrue(result.intervals_overlapped)
        self.assertEqual(result.lower_bound, leakage.LeakageBucket())


if __name__ == "__main__":
    unittest.main()
