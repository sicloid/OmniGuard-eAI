import io
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

import dpkt

from core.schema import Direction
from sources.from_pcap import read_pcap
from sources.packets import PacketError, PacketNormalizer, UnsupportedLinkType


def ipv4(src=b"\x0a\xcb\x01\x02", dst=b"\x0a\xcb\x02\x02", proto=6, fragment=0):
    # Independent struct-built oracle: 20-byte IPv4 + 20-byte TCP SYN = 40 L3 bytes.
    tcp = struct.pack("!HHIIBBHHH", 12345, 443, 0, 0, 0x50, 2, 4096, 0, 0)
    header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 40, 1, fragment, 64, proto, 0, src, dst)
    return header + tcp


def ethernet(raw, ethertype=0x0800):
    return b"\x02\x00\x00\x00\x00\x02\x02\x00\x00\x00\x00\x01" + struct.pack("!H", ethertype) + raw


class PcapTests(unittest.TestCase):
    def normalizer(self):
        return PacketNormalizer(
            ["10.203.1.0/24", "fd00:1::/64"],
            {"10.203.1.2": "camera-1", "fd00:1::2": "camera-v6"},
        )

    def test_independent_oracle_l3_length_and_no_payload_fields(self):
        result = self.normalizer().parse(5, ethernet(ipv4()) + bytes(30))
        self.assertEqual(result.packet_length, 40)
        self.assertEqual((result.src_port, result.dst_port, result.tcp_flags), (12345, 443, 2))
        self.assertEqual(result.direction, Direction.EGRESS)
        self.assertEqual(result.device_id, "camera-1")
        self.assertEqual(result.src_mac, "02:00:00:00:00:01")
        self.assertNotIn("payload", asdict(result))

    def test_ingress_and_local_identity(self):
        ingress = self.normalizer().parse(
            0, ethernet(ipv4(src=b"\x0a\xcb\x02\x02", dst=b"\x0a\xcb\x01\x02"))
        )
        self.assertEqual(ingress.direction, Direction.INGRESS)
        self.assertEqual(ingress.device_id, "camera-1")
        local = self.normalizer().parse(0, ethernet(ipv4(dst=b"\x0a\xcb\x01\x03")))
        self.assertEqual(local.direction, Direction.LOCAL)

    def test_filtered_records_are_accounted_for(self):
        n = self.normalizer()
        self.assertIsNone(n.parse(0, ethernet(bytes(28), 0x0806)))
        self.assertIsNone(n.parse(0, ethernet(ipv4(src=b"\x0a\xcb\x02\x03"))))
        self.assertIsNone(n.parse(0, ethernet(ipv4(src=b"\x0a\xcb\x01\x03"))))
        self.assertEqual(
            (n.stats.records, n.stats.non_ip, n.stats.outside_lan, n.stats.unmapped_device),
            (3, 1, 1, 1),
        )

    def test_single_and_double_vlan(self):
        for tag in (b"\x00\x01\x08\x00", b"\x00\x01\x81\x00\x00\x02\x08\x00"):
            self.assertEqual(
                self.normalizer().parse(0, ethernet(tag + ipv4(), 0x8100)).packet_length, 40
            )

    def test_noninitial_fragment_does_not_invent_ports(self):
        result = self.normalizer().parse(0, ethernet(ipv4(fragment=1)))
        self.assertIsNone(result.src_port)
        self.assertIsNone(result.dst_port)
        self.assertEqual(result.tcp_flags, 0)

    def test_cooked_and_raw_linktypes(self):
        for linktype, frame in (
            (101, ipv4()),
            (12, ipv4()),
            (113, bytes(14) + b"\x08\x00" + ipv4()),
            (276, b"\x08\x00" + bytes(18) + ipv4()),
        ):
            result = self.normalizer().parse(0, frame, linktype)
            self.assertIsNone(result.src_mac)
            self.assertEqual(result.packet_length, 40)
        with self.assertRaises(UnsupportedLinkType):
            self.normalizer().parse(0, b"", 999)

    def test_ipv6_udp_and_noninitial_fragment(self):
        from ipaddress import IPv6Address

        src = IPv6Address("fd00:1::2").packed
        dst = IPv6Address("fd00:2::2").packed
        udp = struct.pack("!HHHH", 1234, 53, 8, 0)
        header = struct.pack("!IHBB16s16s", 6 << 28, 8, 17, 64, src, dst)
        result = self.normalizer().parse(0, ethernet(header + udp, 0x86DD))
        self.assertEqual((result.packet_length, result.src_port, result.dst_port), (48, 1234, 53))
        fragment = struct.pack("!BBHI", 17, 0, 8, 1)
        header = struct.pack("!IHBB16s16s", 6 << 28, 16, 44, 64, src, dst)
        result = self.normalizer().parse(0, ethernet(header + fragment + udp, 0x86DD))
        self.assertEqual((result.packet_length, result.protocol, result.src_port), (56, 17, None))

    def test_malformed_is_fail_fast_with_counter(self):
        for frame in (
            b"",
            ethernet(ipv4()[:-1]),
            ethernet(b"\x44" + ipv4()[1:]),
            ethernet(ipv4()[:20] + bytes(20)),
        ):
            n = self.normalizer()
            with self.subTest(frame=frame), self.assertRaises(PacketError):
                n.parse(0, frame)
            self.assertEqual(n.stats.malformed, 1)

    def test_capture_roundtrip_and_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oracle.pcap"
            buffer = io.BytesIO()
            writer = dpkt.pcap.Writer(buffer, nano=True)
            writer.writepkt(ethernet(ipv4()), ts=5.25)
            writer.writepkt(ethernet(bytes(28), 0x0806), ts=6)
            path.write_bytes(buffer.getvalue())
            n = self.normalizer()
            packets = list(read_pcap(path, n))
            self.assertEqual(len(packets), 1)
            self.assertEqual(packets[0].timestamp, 5.25)
            self.assertEqual(n.stats.records, 2)
            devices = Path(directory) / "devices.json"
            devices.write_text('{"10.203.1.2":"camera-1"}', encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sources.from_pcap",
                    str(path),
                    "--lan",
                    "10.203.1.0/24",
                    "--devices",
                    str(devices),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertEqual(json.loads(result.stdout)["packet_length"], 40)
            self.assertEqual(json.loads(result.stderr)["statistics"]["emitted"], 1)

    def test_reject_pcapng_and_truncated_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.pcap"
            for raw in (b"\x0a\x0d\x0d\x0a", b"\x00\x00"):
                path.write_bytes(raw)
                with self.assertRaises((ValueError, dpkt.UnpackError)):
                    list(read_pcap(path, self.normalizer()))

    def test_reject_oversized_record_before_read_and_missing_padding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.pcap"
            header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
            for length, frame in ((2**31, b""), (64, ethernet(ipv4()))):
                path.write_bytes(header + struct.pack("<IIII", 0, 0, length, length) + frame)
                with self.assertRaises(ValueError):
                    list(read_pcap(path, self.normalizer()))


if __name__ == "__main__":
    unittest.main()
