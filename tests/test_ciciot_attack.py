import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data.ciciot2023.build_attack import build


class CICIoTAttackBuildTests(unittest.TestCase):
    @patch("data.ciciot2023.build_attack.build_sample_pack")
    @patch("data.ciciot2023.build_attack.device_map")
    def test_attack_role_is_explicit_and_separate(self, mapping, sample_pack):
        mapping.return_value = ({"192.168.137.7": "aa:bb:cc:dd:ee:ff"}, {})
        sample_pack.return_value = {"totals": {"malicious": 3}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = build(root / "Backdoor_Malware.pcap", root / "out")
        self.assertEqual(result["totals"]["malicious"], 3)
        spec = sample_pack.call_args.args[0][0]
        self.assertEqual(spec.declared_label, "malicious")
        self.assertTrue(spec.group_by_device)
        self.assertIn("not flow-level ground truth", spec.notes)


if __name__ == "__main__":
    unittest.main()
