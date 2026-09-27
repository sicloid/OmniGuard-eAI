import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import dpkt

from data.samplepack.build import BENIGN_LABEL, CaptureSpec, build_sample_pack


class CiciotBenignContractTests(unittest.TestCase):
    def test_external_benign_groups_are_device_disjoint(self):
        spec = CaptureSpec(
            "capture-a",
            Path("capture.pcap"),
            ("192.168.137.0/24",),
            {"192.168.137.2": "aa:bb:cc:dd:ee:ff"},
            "https://example.invalid",
            "research",
            declared_label=BENIGN_LABEL,
            group_by_device=True,
        )
        self.assertTrue(spec.group_by_device)
        self.assertFalse(replace(spec, group_by_device=False).group_by_device)

    def test_same_device_in_two_captures_has_one_split_group(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            captures = []
            for index in range(2):
                path = root / f"capture-{index}.pcap"
                with path.open("wb") as stream:
                    writer = dpkt.pcap.Writer(stream)
                    packet = dpkt.ip.IP(
                        src=b"\xc0\xa8\x89\x02",
                        dst=b"\x08\x08\x08\x08",
                        p=17,
                        data=dpkt.udp.UDP(sport=1234, dport=53, data=b"x"),
                    )
                    packet.len = len(packet)
                    frame = dpkt.ethernet.Ethernet(
                        src=b"\xaa\xbb\xcc\xdd\xee\xff",
                        dst=b"\x00\x11\x22\x33\x44\x55",
                        type=dpkt.ethernet.ETH_TYPE_IP,
                        data=packet,
                    )
                    writer.writepkt(bytes(frame), ts=100 + index * 10)
                    writer.close()
                captures.append(
                    CaptureSpec(
                        f"capture-{index}",
                        path,
                        ("192.168.137.0/24",),
                        {"192.168.137.2": "aa:bb:cc:dd:ee:ff"},
                        "https://example.invalid",
                        "research",
                        declared_label=BENIGN_LABEL,
                        group_by_device=True,
                    )
                )
            out = root / "out"
            build_sample_pack(captures, out)
            groups = {
                json.loads(line)["group"]
                for line in (out / "windows.jsonl").read_text().splitlines()
            }
        self.assertEqual(groups, {"device:aa:bb:cc:dd:ee:ff"})


if __name__ == "__main__":
    unittest.main()
