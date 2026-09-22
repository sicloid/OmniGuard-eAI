import json
import tempfile
import unittest
from pathlib import Path

from core.schema import Classification, DetectionResult
from model.leakage_plot import PlotError, points, render
from model.leakage_run import (
    SPEC,
    LeakageSpecError,
    activity_segments,
    bootstrap_interval,
    cell_metrics,
    load_spec,
    percentile,
    resample_series,
    stitch,
    test_role_allowed,
    time_blocks,
)

COMMITTED = load_spec(SPEC)


def row(start, *, anomalous, malicious, device="capture-x"):
    result = DetectionResult(
        device,
        float(start),
        "rf-iot23",
        "0.1.0-seed1-kan19",
        0.99 if anomalous else 0.1,
        Classification.ANOMALOUS if anomalous else Classification.NORMAL,
        0.98,
    )
    return (float(start), result, malicious)


def series(pattern, *, malicious=False):
    """One row per character: 'a' anomalous, '.' normal, '_' a window never observed."""
    rows, clock = [], 0
    for mark in pattern:
        if mark != "_":
            rows.append(row(clock, anomalous=mark == "a", malicious=malicious))
        clock += 5
    return rows


class SpecTests(unittest.TestCase):
    def test_the_committed_spec_pins_the_frozen_policy(self):
        frozen = COMMITTED["frozen_policy"]
        self.assertEqual(frozen["threshold"], 0.9798815486832)
        self.assertEqual(
            (frozen["operating_point"]["n"], frozen["operating_point"]["lease_seconds"]), (2, 300)
        )
        self.assertEqual(COMMITTED["data_roles"]["primary"], "validation")

    def test_an_operating_point_outside_the_grid_is_refused(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        spec["frozen_policy"]["operating_point"]["lease_seconds"] = 450
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(LeakageSpecError):
                load_spec(path)

    def test_the_test_split_stays_shut_until_an_approval_is_recorded(self):
        self.assertIsNone(COMMITTED["data_roles"]["test_approval"])
        self.assertFalse(test_role_allowed(COMMITTED))
        approved = json.loads(json.dumps(COMMITTED))
        approved["data_roles"]["test_approval"] = {
            "card": "KAN-52",
            "approved_by": "Lead",
            "date": "2026-09-23",
        }
        self.assertTrue(test_role_allowed(approved))

    def test_an_approval_for_another_card_does_not_open_the_test_split(self):
        borrowed = json.loads(json.dumps(COMMITTED))
        borrowed["data_roles"]["test_approval"] = {
            "card": "KAN-51",
            "approved_by": "Lead",
            "date": "2026-09-23",
        }
        self.assertFalse(test_role_allowed(borrowed))


class ActivityTests(unittest.TestCase):
    def test_segments_and_silences_are_counted_from_the_window_starts(self):
        activity = activity_segments(series("aa__aaa"))
        self.assertEqual(activity["segments"], 2)
        self.assertEqual(activity["gaps"], 1)
        self.assertEqual(activity["silent_seconds"], 10)
        self.assertEqual(activity["longest_segment_seconds"], 15)

    def test_a_capture_without_a_gap_is_one_segment(self):
        activity = activity_segments(series("...."))
        self.assertEqual((activity["segments"], activity["gaps"]), (1, 0))
        self.assertEqual(activity["silent_seconds"], 0)


class BootstrapTests(unittest.TestCase):
    def test_a_block_keeps_its_silence_as_well_as_its_windows(self):
        # Two windows, then 30 s of nothing, then one more: the second block is mostly
        # silent and the third holds the late window.
        blocks = time_blocks(series("aa______a"), 15)
        self.assertEqual([len(rows) for _, rows in blocks], [2, 0, 1])
        self.assertEqual([origin for origin, _ in blocks], [0, 15, 30])

    def test_stitching_preserves_span_density_and_alignment(self):
        blocks = time_blocks(series("aa______a"), 15)
        rebuilt = stitch(blocks + blocks, 15)
        # Six blocks of 15 s. The late window sits 10 s into its own block and keeps
        # that offset in both copies, so the silence around it survives the join.
        self.assertEqual([start for start, _, _ in rebuilt], [0, 5, 40, 45, 50, 85])
        self.assertEqual(rebuilt[-1][0] + 5, 6 * 15)
        self.assertTrue(all(result.window_ts == start for start, result, _ in rebuilt))
        self.assertTrue(all(start % 5 == 0 for start, _, _ in rebuilt))

    def test_a_resample_keeps_the_span_and_is_reproducible(self):
        rows = series("a." * 60)
        first = resample_series(rows, block_seconds=60, resamples=3, seed=52)
        again = resample_series(rows, block_seconds=60, resamples=3, seed=52)
        self.assertEqual(len(first), 3)
        self.assertTrue(all(sample["span_seconds"] == 600 for sample in first))
        self.assertEqual(
            [[start for start, _, _ in sample["rows"]] for sample in first],
            [[start for start, _, _ in sample["rows"]] for sample in again],
        )

    def test_a_block_longer_than_the_capture_is_one_block(self):
        rows = series("aaa")
        sample = resample_series(rows, block_seconds=600, resamples=1, seed=52)[0]
        self.assertEqual(len(sample["rows"]), len(rows))
        self.assertEqual(sample["span_seconds"], 600)

    def test_percentile_returns_a_measured_value(self):
        values = [0.0, 1.0, 2.0, 3.0]
        self.assertEqual(percentile(values, 0.0), 0.0)
        self.assertEqual(percentile(values, 0.975), 3.0)
        self.assertIn(percentile(values, 0.5), values)


class CellTests(unittest.TestCase):
    def test_leakage_is_the_malicious_time_left_unblocked(self):
        # Twenty contiguous malicious windows: at N=2 the first quarantine is decided
        # 10.5 s in and a 300 s lease then covers the rest of the capture.
        rows = [row(5 * i, anomalous=True, malicious=True) for i in range(20)]
        metrics = cell_metrics(rows, n=2, lease_seconds=300, spec=COMMITTED, infected=True)
        self.assertEqual(metrics["quarantines"], 1)
        self.assertAlmostEqual(metrics["containment_leakage"], 10.5 / 100, places=3)
        self.assertEqual(metrics["detection_delay_seconds"], 10.5)

    def test_isolated_anomalies_never_quarantine_at_n_two(self):
        rows = [row(10 * i, anomalous=True, malicious=False) for i in range(10)]
        metrics = cell_metrics(rows, n=2, lease_seconds=300, spec=COMMITTED, infected=False)
        self.assertEqual(metrics["quarantines"], 0)
        self.assertEqual(metrics["quarantines_per_observed_hour"], 0.0)
        self.assertIsNone(metrics["containment_leakage"])

    def test_benign_windows_inside_an_infected_capture_are_kept_apart(self):
        rows = [row(0, anomalous=True, malicious=False), row(5, anomalous=True, malicious=True)]
        metrics = cell_metrics(rows, n=2, lease_seconds=30, spec=COMMITTED, infected=True)
        self.assertEqual(metrics["benign_windows_inside_infected_capture"], 1)
        self.assertEqual(metrics["benign_windows_inside_infected_capture_flagged"], 1)

    def test_every_statistic_carries_its_measurement_spread_and_bias(self):
        rows = [row(5 * i, anomalous=i % 7 < 2, malicious=True) for i in range(120)]
        measured = cell_metrics(rows, n=2, lease_seconds=30, spec=COMMITTED, infected=True)
        samples = resample_series(rows, block_seconds=600, resamples=8, seed=52)
        summary = bootstrap_interval(
            samples, measured, n=2, lease_seconds=30, spec=COMMITTED, infected=True
        )
        rate = summary["quarantines_per_observed_hour"]
        self.assertEqual(rate["measured"], measured["quarantines_per_observed_hour"])
        self.assertLessEqual(rate["interval"][0], rate["interval"][1])
        self.assertLessEqual(rate["resample_spread"][0], rate["resample_spread"][1])
        leak = summary["containment_leakage"]
        self.assertTrue(0 <= leak["interval"][0] <= leak["interval"][1] <= 1)

    def test_the_interval_is_centred_on_the_measurement_not_on_the_resamples(self):
        """A statistic the blocks cannot reproduce must not be bracketed away from it.

        The reflected interval keeps the measurement inside whenever the resample
        spread is wider than the bias, which the percentile spread alone did not.
        """
        pattern = [row(5 * i, anomalous=i % 20 < 3, malicious=True) for i in range(720)]
        rows = [r for r in pattern if r[0] % 60 < 30]  # half the timeline is silence
        measured = cell_metrics(rows, n=2, lease_seconds=30, spec=COMMITTED, infected=True)
        samples = resample_series(rows, block_seconds=600, resamples=40, seed=52)
        summary = bootstrap_interval(
            samples, measured, n=2, lease_seconds=30, spec=COMMITTED, infected=True
        )
        leak = summary["containment_leakage"]
        self.assertTrue(
            leak["interval"][0] <= leak["measured"] <= leak["interval"][1],
            f"{leak['measured']} outside {leak['interval']}",
        )
        self.assertIn("bias", leak)


def report_of(cells, *, benign="benign-1", infected="malware-1"):
    return {
        "benign_captures": [benign],
        "infected_captures": [infected],
        "evaluated_split": "validation",
        "operating_point": {"n": 2, "lease_seconds": 300},
        "observed": {benign: {"observed_hours": 1.4}, infected: {"observed_hours": 13.5}},
        "cells": cells,
    }


def cell(n, lease, *, rate, leakage):
    return {
        "n": n,
        "lease_seconds": lease,
        "captures": {
            "benign-1": {
                "quarantines_per_observed_hour": rate,
                "containment_leakage": None,
                "bootstrap": {
                    "quarantines_per_observed_hour": {"interval": [0.0, rate + 1]},
                },
            },
            "malware-1": {
                "quarantines_per_observed_hour": 4.0,
                "containment_leakage": leakage,
                "bootstrap": {
                    "quarantines_per_observed_hour": {"interval": [3.0, 5.0]},
                    "containment_leakage": {"interval": [max(0.0, leakage - 0.05), leakage + 0.05]},
                },
            },
        },
    }


class PlotTests(unittest.TestCase):
    def test_every_measured_cell_becomes_one_point(self):
        report = report_of(
            [cell(1, 30, rate=9.2, leakage=0.16), cell(2, 300, rate=0.0, leakage=0.075)]
        )
        drawn = points(report)
        self.assertEqual([(p["n"], p["lease_seconds"]) for p in drawn], [(1, 30), (2, 300)])
        self.assertEqual(drawn[1]["x"], 0.0)

    def test_the_figure_names_the_frozen_point_and_the_captures(self):
        svg = render(report_of([cell(2, 300, rate=0.0, leakage=0.075)]))
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("frozen: N=2, 300 s", svg)
        self.assertIn("benign-1", svg)
        self.assertIn("never pooled", svg)
        self.assertIn("not zero risk", svg)

    def test_a_report_without_a_benign_capture_cannot_be_plotted(self):
        report = report_of([cell(2, 300, rate=0.0, leakage=0.075)])
        report["benign_captures"] = []
        with self.assertRaises(PlotError):
            points(report)


if __name__ == "__main__":
    unittest.main()
