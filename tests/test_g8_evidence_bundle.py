"""Preserved G8 logs must still match the published index and validator result."""

import hashlib
import json
import unittest
from pathlib import Path

from lab.g8_iot23_kill_validate import validate as validate_kill
from lab.g8_iot23_validate import validate as validate_orderly

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "docs/evidence/G8_2026-09-20.json"


class G8EvidenceBundleTests(unittest.TestCase):
    def test_exact_bytes_and_both_run_verdicts(self):
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        for kind, run in index["runs"].items():
            with self.subTest(kind=kind):
                evidence = ROOT / run["bundled_evidence_directory"]
                for name, expected in run["sha256"].items():
                    if name.startswith("replay-runs/"):
                        paths = list((evidence / "replay-runs").glob("*/manifest.json"))
                        self.assertEqual(len(paths), 1)
                        path = paths[0]
                    else:
                        path = evidence / name
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
                validator = validate_orderly if kind == "orderly" else validate_kill
                self.assertEqual(validator(evidence), run["validation"])


if __name__ == "__main__":
    unittest.main()
