"""KAN-45: the sealed run must record the budget it ran under and what the budget did."""

import tempfile
import unittest
from pathlib import Path

from measure.kan42_manifest import cgroup_delta, cgroup_limits, cgroup_usage


def cgroup(root: Path, *, cpu="50000 100000", memory="268435456", throttled=0, peak=1000):
    (root / "cpu.max").write_text(cpu + "\n")
    (root / "memory.max").write_text(memory + "\n")
    (root / "cpu.stat").write_text(
        "usage_usec 100\nuser_usec 60\nsystem_usec 40\n"
        f"nr_periods 10\nnr_throttled {throttled}\nthrottled_usec {throttled * 50}\n"
    )
    (root / "memory.peak").write_text(f"{peak}\n")
    (root / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n")


class CgroupRecordingTests(unittest.TestCase):
    def test_a_finite_budget_is_recorded_as_budgeted(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup(Path(directory))
            limits = cgroup_limits(Path(directory))
        self.assertTrue(limits["budgeted"])
        self.assertEqual(limits["cpu_cores"], 0.5)
        self.assertEqual(limits["memory_max_bytes"], 268435456)

    def test_an_unlimited_container_says_so_instead_of_looking_budgeted(self):
        with tempfile.TemporaryDirectory() as directory:
            cgroup(Path(directory), cpu="max 100000", memory="max")
            limits = cgroup_limits(Path(directory))
        self.assertFalse(limits["budgeted"])
        self.assertIsNone(limits["cpu_cores"])
        self.assertIsNone(limits["memory_max_bytes"])

    def test_missing_cgroup_files_are_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIn("unavailable", cgroup_limits(Path(directory)))
            self.assertIn("unavailable", cgroup_usage(Path(directory)))

    def test_the_delta_is_the_throttling_during_the_lab(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cgroup(root, throttled=2, peak=1000)
            before = cgroup_usage(root)
            cgroup(root, throttled=106, peak=5000)
            after = cgroup_usage(root)
        delta = cgroup_delta(before, after)
        self.assertEqual(delta["cpu"]["nr_throttled"], 104)
        self.assertEqual(delta["cpu"]["throttled_usec"], 104 * 50)
        self.assertEqual(delta["memory_peak_bytes"], 5000)
        self.assertEqual(delta["memory_events"]["oom_kill"], 0)

    def test_an_unreadable_side_makes_the_delta_unavailable(self):
        self.assertIn("unavailable", cgroup_delta({"unavailable": "x"}, {"unavailable": "x"}))


if __name__ == "__main__":
    unittest.main()
