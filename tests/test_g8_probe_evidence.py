"""A silent sink is not proof of blocking unless a source tried to send."""

import tempfile
import unittest
from pathlib import Path

from lab.g8_probe_evidence import assess_protocol


class ProbeEvidenceTests(unittest.TestCase):
    def test_requires_attempts_during_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tcp-sink.log").write_text(
                "100\n200\n300\n5000006000\n5000006100\n5000006200\n"
            )
            (root / "tcp-source.log").write_text("100\n200\n300\n")
            with self.assertRaisesRegex(ValueError, "attempts"):
                assess_protocol(
                    root,
                    "tcp",
                    applied_ns=500,
                    blocked_begin_ns=800,
                    blocked_end_ns=4000,
                    release_ns=4_000_000_000,
                )
            (root / "tcp-source.log").write_text("100\n200\n300\n1000\n2000\n3000\n")
            result = assess_protocol(
                root,
                "tcp",
                applied_ns=500,
                blocked_begin_ns=800,
                blocked_end_ns=4000,
                release_ns=4_000_000_000,
            )
            self.assertEqual(result["attempts_during_block"], 3)
            self.assertEqual(result["blocked"], 0)
            self.assertEqual(result["first_post_release_delivery_seconds"], 1.000006)


if __name__ == "__main__":
    unittest.main()
