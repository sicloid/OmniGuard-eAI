import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from data.pi_benign_pack import build


def manifest(pcap: Path) -> dict:
    return {
        "schema": "omniguard.benign-pi-capture/1",
        "duration_seconds": 3600,
        "tcpdump_exit": 0,
        "device_frames": 10,
        "throttled_before": "throttled=0x0",
        "throttled_after": "throttled=0x0",
        "pcap": pcap.name,
        "pcap_sha256": hashlib.sha256(pcap.read_bytes()).hexdigest(),
        "interface_address": "wlan0 UP 192.168.4.7/24",
        "device_ip": "192.168.4.7",
        "boot_id": "boot-1",
    }


class PiBenignPackTests(unittest.TestCase):
    @patch("data.pi_benign_pack.build_sample_pack")
    @patch("data.pi_benign_pack.device_map")
    def test_requires_and_preserves_device_identity(self, mapping, sample_pack):
        mapping.return_value = ({"192.168.4.7": "aa:bb:cc:dd:ee:ff"}, {})
        sample_pack.return_value = {"totals": {"benign": 3}}
        with tempfile.TemporaryDirectory() as directory:
            evidence, output = Path(directory) / "evidence", Path(directory) / "out"
            evidence.mkdir()
            pcap = evidence / "capture.pcap"
            pcap.write_bytes(b"pcap")
            source_bytes = json.dumps(manifest(pcap)).encode()
            (evidence / "manifest.json").write_bytes(source_bytes)
            result = build(evidence, output)
            copied_source = (output / "source_manifest.json").read_bytes()
            provenance = json.loads((output / "pack_provenance.json").read_text())
        self.assertEqual(result["totals"]["benign"], 3)
        self.assertEqual(mapping.call_args.kwargs["lan"], "192.168.4.0/24")
        spec = sample_pack.call_args.args[0][0]
        self.assertEqual(spec.devices, {"192.168.4.7": "aa:bb:cc:dd:ee:ff"})
        self.assertTrue(spec.group_by_device)
        self.assertEqual(copied_source, source_bytes)
        self.assertEqual(provenance["source_directory"], "evidence")
        self.assertEqual(
            provenance["source_manifest_sha256"], hashlib.sha256(source_bytes).hexdigest()
        )

    def test_rejects_throttled_capture_before_reading_pcap(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory)
            pcap = evidence / "capture.pcap"
            pcap.write_bytes(b"pcap")
            document = manifest(pcap)
            document["throttled_after"] = "throttled=0x50005"
            (evidence / "manifest.json").write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "throttling"):
                build(evidence, evidence / "out")


if __name__ == "__main__":
    unittest.main()
