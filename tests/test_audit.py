import socket
import tempfile
import unittest
from pathlib import Path

import dpkt

from data.audit import summarize_pcap


def eth_ip(src: str, dst: str, proto: int = 17) -> bytes:
    udp = dpkt.udp.UDP(sport=1234, dport=53, data=b"x")
    udp.ulen = len(udp)
    ip = dpkt.ip.IP(src=socket.inet_aton(src), dst=socket.inet_aton(dst), p=proto, data=udp)
    ip.len = len(ip)
    return bytes(dpkt.ethernet.Ethernet(src=b"\x02" * 6, dst=b"\x04" * 6, data=ip))


def arp() -> bytes:
    return bytes(
        dpkt.ethernet.Ethernet(
            src=b"\x02" * 6, dst=b"\xff" * 6, type=dpkt.ethernet.ETH_TYPE_ARP, data=dpkt.arp.ARP()
        )
    )


class AuditTests(unittest.TestCase):
    def write(self, frames):
        tmp = tempfile.NamedTemporaryFile(suffix=".pcap", delete=False)
        writer = dpkt.pcap.Writer(tmp)
        for ts, frame in frames:
            writer.writepkt(frame, ts=ts)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_directions_relative_to_lan(self):
        path = self.write(
            [
                (10.0, eth_ip("192.168.1.2", "8.8.8.8")),  # EGRESS
                (11.0, eth_ip("8.8.8.8", "192.168.1.2")),  # INGRESS
                (12.0, eth_ip("192.168.1.2", "192.168.1.3")),  # LOCAL
                (13.0, eth_ip("1.1.1.1", "8.8.8.8")),  # OUTSIDE
            ]
        )
        s = summarize_pcap(path, ["192.168.1.0/24"])
        self.assertEqual(s.packets, 4)
        self.assertEqual(s.ip_packets, 4)
        self.assertEqual(s.direction_counts, {"EGRESS": 1, "INGRESS": 1, "LOCAL": 1, "OUTSIDE": 1})
        self.assertEqual((s.first_ts, s.last_ts), (10.0, 13.0))
        self.assertEqual(s.protocols, {17: 4})

    def test_non_ip_frames_are_counted_but_not_classified(self):
        s = summarize_pcap(
            self.write([(1.0, arp()), (2.0, eth_ip("10.0.0.5", "10.0.0.9"))]), ["10.0.0.0/24"]
        )
        self.assertEqual((s.packets, s.ip_packets), (2, 1))
        self.assertEqual(s.direction_counts, {"LOCAL": 1})

    def test_top_pairs_are_ordered_by_count(self):
        frames = [(float(i), eth_ip("10.0.0.5", "10.0.0.9")) for i in range(3)]
        frames.append((9.0, eth_ip("10.0.0.7", "10.0.0.9")))
        s = summarize_pcap(self.write(frames), ["10.0.0.0/24"])
        self.assertEqual(s.top_pairs[0], ("10.0.0.5", "10.0.0.9", 3))

    def test_empty_capture(self):
        s = summarize_pcap(self.write([]), ["10.0.0.0/24"])
        self.assertEqual((s.packets, s.first_ts, s.last_ts), (0, None, None))

    def test_rejects_pcapng(self):
        path = self.write([])
        path.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 24)
        with self.assertRaises(ValueError):
            summarize_pcap(path, ["10.0.0.0/24"])


if __name__ == "__main__":
    unittest.main()
