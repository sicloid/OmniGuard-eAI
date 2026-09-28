import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from measure.compute_budget import read_limits, run


class ComputeBudgetTests(unittest.TestCase):
    def cgroup(self, root: Path, *, cpu="50000 100000", memory="268435456"):
        (root / "cgroup.controllers").write_text("cpu memory pids\n")
        (root / "cpu.max").write_text(cpu + "\n")
        (root / "memory.max").write_text(memory + "\n")
        (root / "cpu.stat").write_text(
            "usage_usec 100\nnr_periods 10\nnr_throttled 2\nthrottled_usec 50\n"
        )
        (root / "memory.peak").write_text("1048576\n")
        (root / "memory.events").write_text("low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n")

    def test_finite_limits_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.cgroup(root)
            limits = read_limits(root)
        self.assertEqual(limits["cpu_cores"], 0.5)
        self.assertEqual(limits["memory_max_bytes"], 268435456)

    def test_unlimited_runs_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.cgroup(root, cpu="max 100000")
            with self.assertRaisesRegex(RuntimeError, "finite"):
                read_limits(root)

    @unittest.skipUnless(os.name == "posix", "Linux resource accounting only")
    def test_run_seals_result_and_names_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.cgroup(root)
            output = root / "report.json"
            source = root / "input.jsonl"
            source.write_text("{}\n")
            status = run(
                ["sh", "-c", "exit 0"],
                output,
                root,
                inputs=[source],
                container_image_digest="sha256:test",
                workload_scope="test fixture",
            )
            report = json.loads(output.read_text())
            digest = output.with_suffix(".json.sha256").read_text()
        self.assertEqual(status, 0)
        self.assertEqual(report["claim"], "controlled compute budget; not router emulation")
        self.assertEqual(report["schema"], "omniguard.compute-budget/2")
        self.assertEqual(report["cgroup_observation"]["memory_peak_bytes"], 1048576)
        self.assertEqual(report["provenance"]["container_image_digest"], "sha256:test")
        self.assertEqual(
            report["provenance"]["inputs"][0]["sha256"],
            hashlib.sha256(b"{}\n").hexdigest(),
        )
        self.assertIn(output.name, digest)


if __name__ == "__main__":
    unittest.main()
