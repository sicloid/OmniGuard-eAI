"""Prevent an optimized interpreter from reporting an unchecked platform PASS."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class SmokeOptimizationTests(unittest.TestCase):
    def test_optimized_smoke_fails_before_external_commands(self):
        script = Path(__file__).resolve().parents[1] / "platform" / "smoke.py"
        result = subprocess.run(
            [sys.executable, "-O", str(script)],
            env={**os.environ, "PATH": ""},
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Smoke requires assertions", result.stderr)
        self.assertNotIn("PASS", result.stdout)
