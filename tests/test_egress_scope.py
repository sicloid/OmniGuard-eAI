import json
import socket
import struct
import tempfile
import unittest
from ipaddress import ip_address
from pathlib import Path

import dpkt

from core.schema import Direction
from data.samplepack.build import CaptureSpec, build_sample_pack
from gateway.pipeline import WindowFeaturePipeline
from sources.packets import PacketNormalizer
from sources.scope import stays_on_link

EGRESS, LOCAL = Direction.EGRESS, Direction.LOCAL


def udp4(src, dst, dport=53, length=20):
    udp = dpkt.udp.UDP(sport=1111, dport=dport, data=b"x" * length)
    udp.ulen = len(udp)
    ip = dpkt.ip.IP(src=socket.inet_aton(src), dst=socket.inet_aton(dst), p=17, data=udp)
    ip.len = len(ip)
    return bytes(dpkt.ethernet.Ethernet(src=b"\x02" * 6, dst=b"\x04" * 6, data=ip))


def udp6(src, dst, dport=53, length=20):
    udp = struct.pack("!HHHH", 1111, dport, 8 + length, 0) + b"x" * length
    header = struct.pack("!IHBB", 6 << 28, len(udp), 17, 64)
    ip = header + ip_address(src).packed + ip_address(dst).packed + udp
    return b"\x04" * 6 + b"\x02" * 6 + struct.pack("!H", 0x86DD) + ip


class StaysOnLinkTests(unittest.TestCase):
    def test_multicast_broadcast_link_local_and_unspecified_stay_on_link(self):
        for address in (
            "224.0.0.251",
            "239.255.255.250",
            "255.255.255.255",
            "169.254.10.1",
            "0.0.0.0",
            "ff02::fb",
            "fe80::1",
            "::",
        ):
            with self.subTest(address):
                self.assertTrue(stays_on_link(ip_address(address)))

    def test_routed_destinations_stay_routed_even_if_private_or_all_ones(self):
        for address in ("203.0.113.9", "10.0.0.1", "192.168.2.255", "2001:db8::1", "fd00:2::1"):
            with self.subTest(address):
                self.assertFalse(stays_on_link(ip_address(address)))


class NormalizerDirectionTests(unittest.TestCase):
    def directions(self, lans, devices, frames):
        normalizer = PacketNormalizer(lans, devices)
        return [normalizer.parse(0.0, frame).direction for frame in frames], normalizer.stats

    def test_ipv4_on_link_destinations_and_own_subnet_broadcast_are_local(self):
        src = "192.168.1.5"
        destinations = (
            "239.255.255.250",
            "255.255.255.255",
            "169.254.3.4",
            "192.168.1.255",
            "203.0.113.9",
        )
        result, stats = self.directions(
            ["192.168.1.0/24"], {src: "cam"}, [udp4(src, dst) for dst in destinations]
        )
        self.assertEqual(result, [LOCAL, LOCAL, LOCAL, LOCAL, EGRESS])
        # The subnet broadcast is LOCAL by LAN membership, not by the on-link rule.
        self.assertEqual(stats.on_link, 3)

    def test_ipv4_31_and_32_prefixes_have_no_broadcast_address(self):
        result, stats = self.directions(
            ["10.0.0.0/31"],
            {"10.0.0.0": "a", "10.0.0.1": "b"},
            [
                udp4("10.0.0.0", "10.0.0.1"),
                udp4("10.0.0.1", "10.0.0.0"),
                udp4("10.0.0.1", "10.0.0.255"),
                udp4("10.0.0.1", "255.255.255.255"),
            ],
        )
        self.assertEqual(result, [LOCAL, LOCAL, EGRESS, LOCAL])
        self.assertEqual(stats.on_link, 1)
        result, _ = self.directions(
            ["10.1.1.1/32"],
            {"10.1.1.1": "c"},
            [
                udp4("10.1.1.1", "10.1.1.2"),
                udp4("10.1.1.1", "10.1.1.255"),
                udp4("10.1.1.1", "224.0.0.251"),
            ],
        )
        self.assertEqual(result, [EGRESS, EGRESS, LOCAL])

    def test_ipv6_has_no_broadcast_only_multicast_and_link_local(self):
        src = "fd00:1::2"
        destinations = ("ff02::fb", "fe80::1", "fd00:1::ffff:ffff:ffff:ffff", "2001:db8::1")
        result, stats = self.directions(
            ["fd00:1::/64"], {src: "cam6"}, [udp6(src, dst) for dst in destinations]
        )
        self.assertEqual(result, [LOCAL, LOCAL, LOCAL, EGRESS])
        self.assertEqual(stats.on_link, 2)


class PackLiveParityTests(unittest.TestCase):
    SOURCE = "192.168.1.5"
    LANS = ("192.168.1.0/24",)
    DEVICES = {"192.168.1.5": "cam-1"}
    PACKETS = (
        (100.0, "203.0.113.9"),
        (100.5, "239.255.255.250"),
        (101.0, "255.255.255.255"),
        (102.0, "169.254.3.4"),
        (103.0, "192.168.1.255"),
        (104.0, "198.51.100.4"),
        (106.0, "203.0.113.9"),
        (107.0, "224.0.0.251"),
        (108.0, "0.0.0.0"),
    )

    def test_pack_builder_and_live_pipeline_produce_the_same_egress_windows(self):
        frames = [(ts, udp4(self.SOURCE, dst)) for ts, dst in self.PACKETS]
        with tempfile.TemporaryDirectory() as tmp:
            pcap = Path(tmp) / "mixed.pcap"
            with open(pcap, "wb") as handle:
                writer = dpkt.pcap.Writer(handle)
                for ts, data in frames:
                    writer.writepkt(data, ts=ts)
            spec = CaptureSpec(
                group_id="cap",
                pcap=pcap,
                lan_cidrs=self.LANS,
                devices=self.DEVICES,
                source_url="https://example.invalid/cap",
                license="test fixture",
                declared_label="benign",
            )
            manifest = build_sample_pack([spec], Path(tmp) / "pack")
            rows = (Path(tmp) / "pack" / "windows.jsonl").read_text(encoding="utf-8").splitlines()
        offline = [
            (row["device_id"], row["window_start"], tuple(row["values"]))
            for row in map(json.loads, rows)
        ]

        normalizer = PacketNormalizer(list(self.LANS), self.DEVICES)
        pipeline = WindowFeaturePipeline(100)
        vectors = []
        for ts, data in frames:
            vectors.extend(pipeline.ingest(normalizer.parse(ts, data)))
        vectors.extend(pipeline.advance(110.5))
        live = [(v.device_id, v.window_start, v.values) for v in vectors]

        self.assertEqual(len(offline), 2)
        self.assertEqual(live, offline)
        self.assertEqual(normalizer.stats.on_link, 5)
        self.assertEqual(
            manifest["captures"][0]["packets"]["multicast_or_broadcast"], normalizer.stats.on_link
        )


if __name__ == "__main__":
    unittest.main()
