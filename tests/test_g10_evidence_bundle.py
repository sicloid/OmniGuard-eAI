"""Recheck the exact copied real G10 outage evidence in every checkout."""

import hashlib
import runpy
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "docs/evidence/G10_2026-09-20_raw"


class G10EvidenceBundleTests(unittest.TestCase):
    def test_raw_files_match_pins_and_bounded_correlation(self):
        for line in (BUNDLE / "SHA256SUMS").read_text().splitlines():
            expected, relative = line.split(maxsplit=1)
            path = ROOT / relative
            with self.subTest(path=path.name):
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

        verify = runpy.run_path(str(BUNDLE / "verify.py"))["verify"]
        report = verify(BUNDLE, BUNDLE)
        self.assertEqual(report["status"], "local_correlation_and_completeness_verified")
        self.assertEqual(report["counts"]["db_rows"], 2)
        self.assertEqual(report["counts"]["drop_or_unacked"], 0)
        self.assertEqual([row["sequence"] for row in report["correlation"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
