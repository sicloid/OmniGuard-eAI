import json
import socket
import tempfile
import unittest
from pathlib import Path

import dpkt

from data.samplepack.build import CaptureSpec, SamplePackError, build_sample_pack, read_windows

HEADER = (
    "#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\t"
    "service\tduration\tlabel\tdet_label\n"
)


def conn_row(ts, orig, oport, resp, rport, duration, label):
    return "\t".join(
        [str(ts), "uid", orig, str(oport), resp, str(rport), "udp", "-", str(duration), label, "-"]
    )


def frame(src, dst, sport=1111, dport=53, length=20):
    udp = dpkt.udp.UDP(sport=sport, dport=dport, data=b"x" * length)
    udp.ulen = len(udp)
    ip = dpkt.ip.IP(src=socket.inet_aton(src), dst=socket.inet_aton(dst), p=17, data=udp)
    ip.len = len(ip)
    return bytes(dpkt.ethernet.Ethernet(src=b"\x02" * 6, dst=b"\x04" * 6, data=ip))


class SamplePackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def pcap(self, name, packets):
        path = self.dir / name
        with open(path, "wb") as handle:
            writer = dpkt.pcap.Writer(handle)
            for ts, data in packets:
                writer.writepkt(data, ts=ts)
        return path

    def conn_log(self, name, rows):
        path = self.dir / name
        path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
        return path

    def spec(self, **changes):
        base = dict(
            group_id="cap-1",
            pcap=self.pcap(
                "a.pcap",
                [
                    (100.0, frame("192.168.1.5", "203.0.113.9")),
                    (101.0, frame("192.168.1.5", "203.0.113.9")),
                    (106.0, frame("192.168.1.5", "198.51.100.4", dport=80)),
                ],
            ),
            lan_cidrs=("192.168.1.0/24",),
            devices={"192.168.1.5": "cam-1"},
            conn_log=self.conn_log(
                "a.labeled",
                [
                    conn_row(100.0, "192.168.1.5", 1111, "203.0.113.9", 53, 5.0, "Benign"),
                    conn_row(105.5, "192.168.1.5", 1111, "198.51.100.4", 80, 2.0, "Malicious"),
                ],
            ),
            source_url="https://example.invalid/cap-1",
            license="CC BY-NC-SA 4.0",
        )
        return CaptureSpec(**base | changes)

    def build(self, specs=None, **kwargs):
        out = self.dir / "pack"
        manifest = build_sample_pack(specs or [self.spec()], out, **kwargs)
        return manifest, out

    def test_windows_are_grouped_per_device_and_five_seconds(self):
        manifest, out = self.build()
        rows = [json.loads(line) for line in (out / "windows.jsonl").read_text().splitlines()]
        self.assertEqual([r["window_start"] for r in rows], [100.0, 105.0])
        self.assertTrue(all(r["group"] == "cap-1" and r["device_id"] == "cam-1" for r in rows))
        self.assertEqual(rows[0]["values"][0], 2.0)  # pkt_count of the first window

    def test_window_is_malicious_when_any_packet_belongs_to_a_malicious_flow(self):
        _, out = self.build()
        rows = [json.loads(line) for line in (out / "windows.jsonl").read_text().splitlines()]
        self.assertEqual([r["label"] for r in rows], ["benign", "malicious"])

    def test_unmatched_packets_make_a_window_unknown_not_benign(self):
        spec = self.spec(
            conn_log=self.conn_log(
                "b.labeled",
                [conn_row(100.0, "192.168.1.5", 1111, "203.0.113.9", 53, 5.0, "Benign")],
            )
        )
        manifest, out = self.build([spec])
        rows = [json.loads(line) for line in (out / "windows.jsonl").read_text().splitlines()]
        self.assertEqual([r["label"] for r in rows], ["benign", "unknown"])
        self.assertEqual(manifest["captures"][0]["windows"]["unknown"], 1)
        self.assertEqual(manifest["captures"][0]["packets"]["unmatched_packets"], 1)

    def test_malicious_windows_that_hide_unmatched_packets_are_counted(self):
        spec = self.spec(
            pcap=self.pcap(
                "x.pcap",
                [
                    (106.0, frame("192.168.1.5", "198.51.100.4", dport=80)),
                    (107.0, frame("192.168.1.5", "203.0.113.1", dport=99)),
                ],
            )
        )
        manifest, out = self.build([spec])
        rows = [json.loads(line) for line in (out / "windows.jsonl").read_text().splitlines()]
        self.assertEqual([r["label"] for r in rows], ["malicious"])
        capture = manifest["captures"][0]
        self.assertEqual(capture["windows"]["malicious_with_unmatched_packets"], 1)
        self.assertEqual(capture["packets"]["unmatched_packets"], 1)

    def test_unknown_windows_are_excluded_from_training_data(self):
        spec = self.spec(
            conn_log=self.conn_log(
                "c.labeled",
                [conn_row(100.0, "192.168.1.5", 1111, "203.0.113.9", 53, 5.0, "Benign")],
            )
        )
        _, out = self.build([spec])
        windows = read_windows(out / "windows.jsonl")
        self.assertEqual(len(windows), 1)
        self.assertFalse(windows[0].malicious)
        self.assertEqual(windows[0].group_id, "cap-1")

    def test_multicast_and_broadcast_are_not_outbound(self):
        spec = self.spec(
            pcap=self.pcap(
                "m.pcap",
                [
                    (200.0, frame("192.168.1.5", "239.255.255.250", dport=1900)),
                    (201.0, frame("192.168.1.5", "255.255.255.255", dport=67)),
                ],
            )
        )
        manifest, out = self.build([spec])
        self.assertEqual((out / "windows.jsonl").read_text(), "")
        self.assertEqual(manifest["captures"][0]["packets"]["multicast_or_broadcast"], 2)

    def test_capture_cut_mid_record_keeps_earlier_windows_and_drops_the_last(self):
        path = self.pcap(
            "t.pcap",
            [
                (100.0, frame("192.168.1.5", "203.0.113.9")),
                (106.0, frame("192.168.1.5", "203.0.113.9")),
                (107.0, frame("192.168.1.5", "203.0.113.9")),
            ],
        )
        with open(path, "r+b") as handle:  # cut the final record in half
            handle.truncate(path.stat().st_size - 20)
        manifest, out = self.build([self.spec(pcap=path)])
        rows = [json.loads(line) for line in (out / "windows.jsonl").read_text().splitlines()]
        self.assertEqual([r["window_start"] for r in rows], [100.0])  # 105 was still open
        capture = manifest["captures"][0]
        self.assertTrue(capture["truncated_tail"])
        self.assertEqual(capture["windows"]["dropped_truncated_tail"], 1)

    def test_declared_label_is_recorded_as_an_assumption(self):
        spec = self.spec(conn_log=None, declared_label="benign")
        manifest, out = self.build([spec])
        rows = [json.loads(line) for line in (out / "windows.jsonl").read_text().splitlines()]
        self.assertTrue(all(r["label"] == "benign" for r in rows))
        capture = manifest["captures"][0]
        self.assertEqual(capture["label_source"], "declared")
        self.assertIn("assumption", capture["notes"].lower())

    def test_manifest_records_provenance_and_is_reproducible(self):
        manifest, out = self.build()
        capture = manifest["captures"][0]
        self.assertEqual(capture["source_url"], "https://example.invalid/cap-1")
        self.assertEqual(capture["license"], "CC BY-NC-SA 4.0")
        self.assertEqual(capture["lan_cidrs"], ["192.168.1.0/24"])
        self.assertEqual(capture["devices"], {"192.168.1.5": "cam-1"})
        self.assertEqual(len(capture["pcap_sha256"]), 64)
        self.assertEqual(len(capture["conn_log_sha256"]), 64)
        self.assertEqual(manifest["feature_schema_version"], "features-1")
        self.assertEqual(manifest["window_seconds"], 5)
        self.assertEqual(manifest["flow_match_tolerance_s"], 1.0)
        self.assertIn("224.0.0.0/4", manifest["egress_exclusions"])
        second = build_sample_pack([self.spec()], self.dir / "pack2")
        self.assertEqual(manifest["windows_sha256"], second["windows_sha256"])

    def test_labels_outside_the_vocabulary_are_rejected_not_read_as_benign(self):
        _, out = self.build()
        path = out / "windows.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[0]["label"] = "UNRECOGNIZED"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaises(SamplePackError):
            read_windows(path)

    def test_reader_errors_other_than_a_truncated_record_fail_the_build(self):
        pcapng = self.dir / "n.pcap"
        pcapng.write_bytes(b"\x0a\x0d\x0d\x0a" + b"\x00" * 28)
        wifi = self.dir / "w.pcap"
        with open(wifi, "wb") as handle:
            dpkt.pcap.Writer(handle, linktype=105).writepkt(b"\x00" * 40, ts=100.0)
        bad_ipv4 = b"\x04" * 6 + b"\x02" * 6 + b"\x08\x00" + b"\x45\x00\x00\x05" + b"\x00" * 16
        broken = self.pcap("b.pcap", [(100.0, bad_ipv4)])
        for path in (pcapng, wifi, broken):
            with self.subTest(capture=path.name), self.assertRaises(ValueError):
                build_sample_pack([self.spec(pcap=path)], self.dir / f"out-{path.stem}")


if __name__ == "__main__":
    unittest.main()
