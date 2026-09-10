"""Replay input, scheduling and failure evidence without network privileges."""

import hashlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import dpkt

from lab.replay import audit, mac_bytes, replay, snapshot, transmit, verify_lab


def frame(dst=bytes((10, 203, 2, 2)), checksum=True):
    udp = struct.pack("!HHHH", 39028, 39027, 12, 0) + b"TEST"
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 32, 0, 0, 64, 17, 0, bytes((10, 203, 1, 2)), dst)
    if checksum:
        ip = ip[:10] + struct.pack("!H", dpkt.in_cksum(ip)) + ip[12:]
    return bytes.fromhex("0200000000020200000000010800") + ip + udp


def capture(path, rows=None):
    rows = rows if rows is not None else [(5, frame()), (5.2, frame()), (5.5, frame())]
    with path.open("wb") as stream:
        writer = dpkt.pcap.Writer(stream, nano=True)
        for ts, data in rows:
            writer.writepkt(data, ts=ts)


class Clock:
    def __init__(self):
        self.now = 1000

    def monotonic_ns(self):
        self.now += 1000
        return self.now

    def time_ns(self):
        return 1_700_000_000_000_000_000

    def sleep(self, duration):
        self.now += int(duration * 1e9)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "oracle.pcap"
        capture(self.path)

    def test_snapshot_hash_and_immutable_input(self):
        original = self.path.read_bytes()
        with snapshot(self.path, 4096) as (stream, digest, size):
            self.path.write_bytes(b"changed after snapshot")
            self.assertEqual(stream.read(), original)
            self.assertEqual(digest, hashlib.sha256(original).hexdigest())
            self.assertEqual(size, len(original))

    def test_audit_preserves_packet_count_and_time_range(self):
        with snapshot(self.path, 4096) as (stream, _, _):
            result = audit(stream, 1500, 1)
        self.assertEqual(result["packets"], 3)
        self.assertEqual(float(result["first_capture_ts"]), 5)
        self.assertEqual(float(result["last_capture_ts"]), 5.5)

    def test_invalid_input_rejected_including_late_bad_record(self):
        cases = [
            [(5, frame()), (6, frame(dst=bytes((198, 51, 100, 1))))],
            [(5, frame()), (4, frame())],
            [(5, frame(checksum=False))],
            [(5, frame()[:-1])],
            [(5, frame() + bytes(10))],
            [],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                capture(self.path, rows)
                with snapshot(self.path, 4096) as (stream, _, _), self.assertRaises(ValueError):
                    audit(stream, 1500, 5)

    def test_snapshot_duration_and_mtu_bounds(self):
        with self.assertRaises(ValueError), snapshot(self.path, 24):
            pass
        for mtu, duration in ((31, 5), (1500, 0.1)):
            with snapshot(self.path, 4096) as (stream, _, _), self.assertRaises(ValueError):
                audit(stream, mtu, duration)

    def test_scaled_schedule_reference_and_clock_mapping(self):
        log, sent = io.StringIO(), []
        with snapshot(self.path, 4096) as (stream, _, _):
            result = transmit(
                stream,
                lambda data: sent.append(data) or len(data),
                log,
                first_timestamp="5",
                speed=2,
                reference_record=2,
                clock=Clock(),
            )
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        returns = [event for event in events if event["type"] == "send_return"]
        origin = result["clock_mapping"]["monotonic_after_ns"]
        self.assertEqual(
            [e["scheduled_ns"] - origin for e in returns], [0, 100_000_000, 250_000_000]
        )
        self.assertEqual(result["reference_t0"]["record"], 2)
        self.assertEqual(result["sent_packets"], 3)
        self.assertEqual(sent, [frame()] * 3)
        self.assertEqual(events[0]["type"], "clock_mapping")
        self.assertTrue(
            all(e["scheduled_ns"] <= e["send_begin_ns"] <= e["send_return_ns"] for e in returns)
        )

    def test_failed_send_retains_intent_not_false_success(self):
        log = io.StringIO()
        with snapshot(self.path, 4096) as (stream, _, _), self.assertRaises(OSError):
            transmit(
                stream,
                lambda _: 0,
                log,
                first_timestamp="5",
                speed=1,
                reference_record=1,
                clock=Clock(),
            )
        events = [json.loads(line) for line in log.getvalue().splitlines()]
        self.assertEqual([e["type"] for e in events], ["clock_mapping", "send_begin"])

    def test_invalid_capture_never_opens_sender_and_has_failed_manifest(self):
        capture(self.path, [(5, frame()), (6, frame(checksum=False))])
        with (
            patch("lab.replay.verify_lab", return_value=(bytes(6), bytes(6), 1500, {})),
            patch("lab.replay.socket.socket") as factory,
            self.assertRaises(ValueError),
        ):
            replay(self.path, self.root / "runs", {"source": "unit fixture", "transformations": []})
        factory.assert_not_called()
        manifests = list((self.root / "runs").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(json.loads(manifests[0].read_text())["status"], "failed")

    def test_two_runs_have_distinct_ids_and_same_prepared_hash(self):
        mock_socket = Mock()
        mock_socket.__enter__ = Mock(return_value=mock_socket)
        mock_socket.__exit__ = Mock(return_value=False)
        mock_socket.send.side_effect = len
        with (
            patch("lab.replay.verify_lab", return_value=(bytes(6), bytes(6), 1500, {})),
            patch("lab.replay.socket.socket", return_value=mock_socket),
        ):
            results = [
                replay(
                    self.path,
                    self.root / "runs",
                    {"source": "unit fixture", "transformations": []},
                    speed=100,
                )
                for _ in range(2)
            ]
        self.assertNotEqual(results[0]["run_id"], results[1]["run_id"])
        self.assertEqual(results[0]["prepared_pcap_sha256"], results[1]["prepared_pcap_sha256"])
        self.assertTrue(all(r["status"] == "complete" for r in results))

    def test_host_platform_guard_and_mac_validation(self):
        with patch("lab.replay.sys.platform", "win32"), self.assertRaises(PermissionError):
            verify_lab()
        for address in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "broken"):
            with self.assertRaises(ValueError):
                mac_bytes(address)
        self.assertEqual(mac_bytes("02:00:00:00:00:01"), bytes((2, 0, 0, 0, 0, 1)))


if __name__ == "__main__":
    unittest.main()
