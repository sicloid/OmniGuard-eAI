import json
import tempfile
import unittest
from pathlib import Path

from core.schema import Classification, DetectionResult
from model.nlease_run import (
    SPEC,
    SweepSpecError,
    load_spec,
    malicious_overlap_seconds,
    replay_device,
    select_cell,
    trimmed_report,
)

REPLAY = {"decision_delay_seconds": 0.5, "max_result_age": 2.5, "max_lease_seconds": 600}
SPEC_STUB = {"replay": REPLAY}


def result(start: float, *, anomalous: bool, device: str = "cam-1") -> DetectionResult:
    score = 0.99 if anomalous else 0.1
    return DetectionResult(
        device,
        start,
        "rf-iot23",
        "0.1.0-seed1-kan19",
        score,
        Classification.ANOMALOUS if anomalous else Classification.NORMAL,
        0.98,
    )


def stream(pattern: str, *, first: float = 0.0):
    """One result per character: 'a' anomalous, 'n' normal, '.' a missing window."""
    rows = []
    for index, mark in enumerate(pattern):
        if mark == ".":
            continue
        start = first + index * 5
        rows.append((start, result(start, anomalous=mark == "a")))
    return rows


class ReplayTests(unittest.TestCase):
    def test_quarantine_happens_on_the_nth_consecutive_anomaly(self):
        for n, pattern, expected in ((1, "a", 1), (2, "aa", 1), (2, "a", 0), (3, "aa", 0)):
            with self.subTest(n=n, pattern=pattern):
                outcome = replay_device(stream(pattern), n=n, lease_seconds=60, spec=SPEC_STUB)
                self.assertEqual(outcome["quarantines"], expected)

    def test_a_missing_window_breaks_the_series(self):
        # "a.a" is two anomalies with a gap between them: the policy resets, so N=2
        # is never reached, and the gap is counted rather than hidden.
        gapped = replay_device(stream("a.a"), n=2, lease_seconds=60, spec=SPEC_STUB)
        contiguous = replay_device(stream("aa"), n=2, lease_seconds=60, spec=SPEC_STUB)
        self.assertEqual(gapped["quarantines"], 0)
        self.assertEqual(gapped["resets"]["gap"], 1)
        self.assertEqual(contiguous["quarantines"], 1)

    def test_a_benign_window_between_anomalies_breaks_the_series(self):
        outcome = replay_device(stream("ana"), n=2, lease_seconds=60, spec=SPEC_STUB)
        self.assertEqual(outcome["quarantines"], 0)

    def test_a_single_burst_is_blocked_for_the_lease_bounded_by_observation(self):
        # One anomaly, then quiet: the lease alone decides how long the device stays
        # blocked, and observation stops before a 300 s lease can run out.
        burst = stream("a" + "n" * 199)
        short = replay_device(burst, n=1, lease_seconds=30, spec=SPEC_STUB)
        longer = replay_device(burst, n=1, lease_seconds=300, spec=SPEC_STUB)
        self.assertEqual(short["blocked_seconds"], 30.0)
        self.assertGreater(longer["blocked_seconds"], short["blocked_seconds"])
        last = burst[-1][0] + 5 + REPLAY["decision_delay_seconds"]
        for outcome in (short, longer):
            self.assertTrue(all(e["end"] is not None for e in outcome["episodes"]))
            self.assertTrue(all(e["end"] <= last for e in outcome["episodes"]))

    def test_against_a_continuous_attack_the_lease_changes_episodes_not_exposure(self):
        # The device is re-quarantined as soon as each lease expires, so the blocked
        # total saturates at the observation window and only the episode count moves.
        attack = stream("a" * 200)
        short = replay_device(attack, n=1, lease_seconds=30, spec=SPEC_STUB)
        longer = replay_device(attack, n=1, lease_seconds=300, spec=SPEC_STUB)
        self.assertGreater(short["quarantines"], longer["quarantines"])
        self.assertEqual(short["blocked_seconds"], longer["blocked_seconds"])
        last = attack[-1][0] + 5 + REPLAY["decision_delay_seconds"]
        self.assertLessEqual(short["blocked_seconds"], last)

    def test_a_short_lease_requarantines_a_device_that_keeps_attacking(self):
        outcome = replay_device(stream("a" * 200), n=1, lease_seconds=30, spec=SPEC_STUB)
        self.assertGreater(outcome["quarantines"], 1)
        starts = [episode["start"] for episode in outcome["episodes"]]
        self.assertEqual(starts, sorted(starts))

    def test_a_lease_ends_at_its_deadline_even_when_the_device_goes_silent(self):
        # Two anomalies, then 100 missing windows (500 s of silence), then one more
        # window. The replay only notices the expiry at that last window, but the
        # kernel element expired at start + lease; the episode must say so.
        outcome = replay_device(
            stream("aa" + "." * 100 + "n"), n=1, lease_seconds=30, spec=SPEC_STUB
        )
        first = outcome["episodes"][0]
        self.assertEqual(first["end"] - first["start"], 30.0)
        self.assertTrue(all(e["end"] - e["start"] <= 30.0 for e in outcome["episodes"]))

    def test_an_episode_open_at_the_end_is_closed_not_dropped(self):
        outcome = replay_device(stream("aa"), n=1, lease_seconds=300, spec=SPEC_STUB)
        episode = outcome["episodes"][0]
        self.assertIsNotNone(episode["end"])
        self.assertIn("capture ended", episode["ended_by"])


class OverlapTests(unittest.TestCase):
    def test_blocking_at_the_wrong_time_is_not_containment(self):
        # 800 s blocked, but entirely after the only malicious window: a comparison of
        # totals would report full containment; the overlap is zero.
        episodes = [{"start": 100.0, "end": 900.0}]
        self.assertEqual(malicious_overlap_seconds(episodes, [0.0]), 0.0)

    def test_overlap_counts_only_the_shared_seconds(self):
        episodes = [{"start": 2.0, "end": 12.0}]
        # Windows [0,5) and [5,10) and [10,15): overlap 3 + 5 + 2.
        self.assertEqual(malicious_overlap_seconds(episodes, [0.0, 5.0, 10.0]), 10.0)

    def test_overlap_never_exceeds_malicious_time(self):
        episodes = [{"start": 0.0, "end": 1000.0}]
        self.assertEqual(malicious_overlap_seconds(episodes, [0.0, 5.0]), 10.0)


class SelectionTests(unittest.TestCase):
    def cell(self, n, lease, benign_quarantines, contained):
        return {
            "n": n,
            "lease_seconds": lease,
            "captures": {
                "benign-1": {"quarantines": benign_quarantines},
                "malware-1": {"malicious_time_blocked_fraction": contained},
            },
        }

    def test_smallest_clean_n_then_smallest_lease_that_contains(self):
        cells = [
            self.cell(1, 30, 4, 0.99),
            self.cell(1, 60, 4, 0.99),
            self.cell(2, 30, 0, 0.5),
            self.cell(2, 60, 0, 0.95),
            self.cell(3, 30, 0, 0.99),
        ]
        decision = select_cell(cells, {"malware-1"}, containment_floor=0.9)
        self.assertEqual(
            (decision["status"], decision["n"], decision["lease_seconds"]), ("selected", 2, 60)
        )

    def test_no_n_without_a_false_quarantine_selects_nothing(self):
        cells = [self.cell(1, 30, 2, 1.0), self.cell(2, 30, 1, 1.0)]
        decision = select_cell(cells, {"malware-1"}, containment_floor=0.9)
        self.assertEqual((decision["status"], decision["n"]), ("no_clean_n", None))

    def test_the_floor_is_the_one_passed_in(self):
        cells = [self.cell(2, 30, 0, 0.92), self.cell(2, 60, 0, 0.995)]
        self.assertEqual(
            select_cell(cells, {"malware-1"}, containment_floor=0.9)["lease_seconds"], 30
        )
        self.assertEqual(
            select_cell(cells, {"malware-1"}, containment_floor=0.99)["lease_seconds"], 60
        )

    def test_a_clean_n_that_never_contains_is_reported_not_relaxed(self):
        cells = [self.cell(2, 30, 0, 0.3), self.cell(2, 60, 0, 0.5)]
        decision = select_cell(cells, {"malware-1"}, containment_floor=0.9)
        self.assertEqual(
            (decision["status"], decision["n"], decision["lease_seconds"]),
            ("no_lease_contains", 2, None),
        )


class SpecTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write(self, **changes) -> Path:
        spec = json.loads(SPEC.read_text(encoding="utf-8")) | changes
        path = self.dir / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def test_committed_spec_is_valid_and_declares_its_rule(self):
        spec = load_spec(SPEC)
        self.assertEqual(spec["selection_rule"]["containment_floor"], 0.9)
        self.assertEqual(spec["grid"]["n"], [1, 2, 3, 5])
        self.assertIn("smallest N", spec["selection_rule"]["n"])
        self.assertEqual(spec["frozen_policy"]["threshold"], 0.9798815486832)

    def test_spec_rules_are_enforced(self):
        bad = (
            {"feature_schema_version": "features-0"},
            {"development_pack_windows_sha256": "nope"},
            {"grid": {"n": [1, 1], "lease_seconds": [30]}},
            {"grid": {"n": [0], "lease_seconds": [30]}},
            {"grid": {"n": [1.5], "lease_seconds": [30]}},
            {"grid": {"n": [1], "lease_seconds": []}},
            {"grid": {"n": [1], "lease_seconds": [900]}},
            {"frozen_policy": {"model_sha256": "0" * 64}},
            {"replay": REPLAY | {"decision_delay_seconds": 9}},
            {"selection_rule": {}},
            {"selection_rule": {"n": "x", "containment_floor": 0}},
            {"selection_rule": {"n": "x", "containment_floor": 1.5}},
            {"selection_rule": {"n": "x", "containment_floor": True}},
            {"selection_rule": {"n": "x"}},
        )
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(SweepSpecError):
                load_spec(self.write(**changes))


class TrimTests(unittest.TestCase):
    def test_trimmed_report_is_derived_by_code(self):
        episodes = [{"start": float(i), "end": float(i) + 1, "ended_by": "x"} for i in range(9)]
        report = {
            "spec": {"path": "/home/someone/model/nlease_spec.json"},
            "pack": {"path": "/home/someone/data/windows.jsonl"},
            "artifact": {"path": "/home/someone/runs/kan19/operating"},
            "cells": [{"captures": {"c": {"episodes": episodes, "quarantines": 9}}}],
        }
        trimmed = trimmed_report(report)
        capture = trimmed["cells"][0]["captures"]["c"]
        self.assertNotIn("episodes", capture)
        self.assertEqual(len(capture["first_episodes"]), 3)
        self.assertEqual(capture["quarantines"], 9)
        self.assertEqual(trimmed["pack"]["path"], "windows.jsonl")
        self.assertEqual(len(report["cells"][0]["captures"]["c"]["episodes"]), 9)


if __name__ == "__main__":
    unittest.main()
