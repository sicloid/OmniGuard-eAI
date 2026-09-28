import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from data.ciciot2023.inventory import inventory


class CiciotInventoryTests(unittest.TestCase):
    def test_inventory_hashes_every_pcap_and_keeps_folder_role(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attack = root / "DDoS-UDP_Flood"
            benign = root / "Benign_Final"
            attack.mkdir()
            benign.mkdir()
            (attack / "a.pcap").write_bytes(b"attack")
            (benign / "b.pcap").write_bytes(b"benign")
            result = inventory(root)
        self.assertEqual(result["capture_count"], 2)
        self.assertEqual(result["total_bytes"], 12)
        self.assertEqual(result["captures"][0]["attack_or_role"], "Benign_Final")
        self.assertEqual(result["captures"][1]["sha256"], hashlib.sha256(b"attack").hexdigest())
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
