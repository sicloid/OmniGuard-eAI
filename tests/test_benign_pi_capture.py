import unittest
from pathlib import Path


class BenignPiCaptureScriptTests(unittest.TestCase):
    def test_script_preserves_required_provenance_and_one_hour_floor(self):
        script = Path("sources/capture_benign_pi.sh").read_text()
        for token in (
            "duration must be at least one device-hour",
            "boot_id",
            "pcap_sha256",
            "throttled_before",
            "throttled_after",
            "scenarios.tsv",
            "device wlan0; not gateway transit",
        ):
            self.assertIn(token, script)


if __name__ == "__main__":
    unittest.main()
