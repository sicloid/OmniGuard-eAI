import json
import tempfile
import unittest
from pathlib import Path

from data.holdout.selection import (
    MANIFEST,
    Candidate,
    SelectionError,
    check,
    is_primary_capture,
    select,
)

DEVELOPMENT = ("Muhstik", "Hakai", "Mirai")


def candidate(number, family, pcap_bytes, *, label=1000, pcap=None):
    return Candidate(
        f"CTU-IoT-Malware-Capture-{number}-1",
        family,
        pcap or f"2019-01-{number % 28 + 1:02d}-10-00-00-192.168.1.{number}.pcap",
        pcap_bytes,
        None if label is None else "bro/conn.log.labeled",
        label,
    )


def run(candidates, *, order=("Torii", "Okiru", "Gagfyt"), budget=10_000, excluded=None):
    return select(
        candidates,
        seen_family="Mirai",
        unseen_order=order,
        unseen_needed=2,
        budget_bytes=budget,
        excluded=excluded or {},
        development_families=DEVELOPMENT,
    )


def scenarios(picks):
    return [p.candidate.scenario.removeprefix("CTU-IoT-Malware-Capture-") for p in picks]


class RecordedManifestTests(unittest.TestCase):
    def test_recorded_manifest_reproduces_its_selection(self):
        picks, notes = check(MANIFEST)
        self.assertEqual(scenarios(picks), ["48-1", "20-1", "36-1"])
        self.assertEqual([p.role for p in picks], ["seen_family", "unseen_family", "unseen_family"])
        total = sum(p.candidate.download_bytes for p in picks)
        self.assertEqual(total, 4_586_579_990)
        self.assertLessEqual(total, 10_000_000_000)
        self.assertEqual(notes, [])

    def test_hand_edited_selection_or_total_fails_the_check(self):
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        edits = {
            "selection swapped": lambda d: d["selection"][0].update(
                scenario="CTU-IoT-Malware-Capture-44-1"
            ),
            "total changed": lambda d: d.update(download_bytes_total=1),
            "budget lowered": lambda d: d["rule"].update(budget_bytes=1_000_000),
            "pattern loosened": lambda d: d["rule"].update(primary_capture_pattern=".*"),
        }
        for name, edit in edits.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                changed = json.loads(json.dumps(document))
                edit(changed)
                path = Path(tmp) / "selection.json"
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.assertRaises(SelectionError):
                    check(path)


class PrimaryCaptureTests(unittest.TestCase):
    def test_full_captures_are_primary_and_derived_excerpts_are_not(self):
        for name in (
            "2019-02-28-19-15-13-192.168.1.200.pcap",
            "2018-05-09-192.168.100.103.pcap",
        ):
            with self.subTest(name):
                self.assertTrue(is_primary_capture(name))
        for name in (
            "2018-07-25-10-53-16-192.168.100.111-only5000.pcap",
            "2018-09-06-11-43-12-192.168.100.111.only15000000.pcap",
            "telnet.pcap",
            "104.248.160.24-80.pcap",
            "85.217.225.181.23.pcap",
            "malware-capture-35-1-port-23.pcap",
        ):
            with self.subTest(name):
                self.assertFalse(is_primary_capture(name))


class RuleTests(unittest.TestCase):
    def base(self):
        return [
            candidate(48, "Mirai", 100),
            candidate(44, "Mirai", 300),
            candidate(20, "Torii", 50),
            candidate(36, "Okiru", 70),
            candidate(60, "Gagfyt", 20),
        ]

    def test_smallest_capture_per_family_in_the_fixed_order(self):
        picks, notes = run(self.base())
        self.assertEqual(scenarios(picks), ["48-1", "20-1", "36-1"])
        self.assertEqual(notes, [])

    def test_equal_sizes_go_to_the_smaller_numeric_scenario_id(self):
        tied = [candidate(17, "Torii", 50), candidate(9, "Torii", 50), *self.base()[:1]]
        tied.append(candidate(36, "Okiru", 70))
        picks, _ = run(tied)
        self.assertEqual(scenarios(picks)[1], "9-1")  # lexical order would pick 17-1

    def test_a_family_that_does_not_fit_the_budget_is_skipped_for_the_next(self):
        items = self.base()
        items[3] = candidate(36, "Okiru", 20_000)
        picks, notes = run(items)
        self.assertEqual(scenarios(picks), ["48-1", "20-1", "60-1"])
        self.assertEqual(len(notes), 1)
        self.assertIn("Okiru", notes[0])

    def test_ineligible_captures_are_never_selected_even_when_smaller(self):
        items = [
            *self.base(),
            candidate(21, "Torii", 1, label=None),
            candidate(35, "Mirai", 1, pcap="malware-capture-35-1-port-23.pcap"),
            candidate(43, "Mirai", 2),
        ]
        excluded = {"CTU-IoT-Malware-Capture-43-1": "excluded for the test"}
        picks, _ = run(items, excluded=excluded)
        self.assertEqual(scenarios(picks), ["48-1", "20-1", "36-1"])

    def test_rules_that_would_leak_or_cannot_be_met_are_rejected(self):
        cases = {
            "unseen order lists a development family": dict(order=("Hakai", "Torii", "Okiru")),
            "too few unseen families fit": dict(order=("Torii",)),
            "seen family does not fit the budget": dict(budget=90),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(SelectionError):
                run(self.base(), **kwargs)
        with self.assertRaises(SelectionError):
            run([*self.base(), candidate(20, "Torii", 51)])
        with self.assertRaises(SelectionError):
            select(
                self.base(),
                seen_family="Torii",
                unseen_order=("Okiru", "Gagfyt"),
                unseen_needed=2,
                budget_bytes=10_000,
                excluded={},
                development_families=DEVELOPMENT,
            )

    def test_candidate_records_are_validated(self):
        for kwargs in (
            dict(pcap_bytes=0),
            dict(label=0),
        ):
            with self.subTest(kwargs), self.assertRaises(SelectionError):
                candidate(20, "Torii", kwargs.get("pcap_bytes", 5), label=kwargs.get("label", 1))
        with self.assertRaises(SelectionError):
            Candidate("no-number", "Torii", "x.pcap", 5, None, None)
        with self.assertRaises(SelectionError):
            Candidate("CTU-IoT-Malware-Capture-20-1", "Torii", "x.pcap", 5, "bro/x", None)


if __name__ == "__main__":
    unittest.main()
