"""Socket faults and PCAP parity without capture privileges on CI."""

import io
import socket
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import dpkt

from sources.from_pcap import read_pcap
from sources.live import (
    SO_TIMESTAMPNS_NEW,
    CaptureError,
    LiveCapture,
    kernel_timestamp,
)
from sources.packets import PacketError, PacketNormalizer


def frame():
    udp = struct.pack("!HHHH", 1234, 9999, 12, 0) + b"TEST"
    ip = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        32,
        0,
        0,
        64,
        17,
        0,
        bytes((10, 203, 1, 2)),
        bytes((10, 203, 2, 2)),
    )
    return bytes.fromhex("0200000000020200000000010800") + ip + udp


def message(ts=5, nanos=250_000_000, data=None, flags=0, outgoing=False):
    return (
        frame() if data is None else data,
        [(socket.SOL_SOCKET, SO_TIMESTAMPNS_NEW, struct.pack("=qq", ts, nanos))],
        flags,
        ("eth0", 3, 4 if outgoing else 0, 1, bytes(6)),
    )


def normalizer():
    return PacketNormalizer(["10.203.1.0/24"], {"10.203.1.2": "camera"})


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.sock = Mock()
        self.sock.getsockname.return_value = ("eth0", 3, 0, 1, bytes(6))
        self.sock.getsockopt.side_effect = lambda *args: (
            2097152 if len(args) == 2 else struct.pack("=II", 0, 0)
        )
        for target, value in (
            ("sources.live.sys.platform", "linux"),
            ("sources.live.socket.socket", Mock(return_value=self.sock)),
            ("sources.live.socket.CMSG_SPACE", lambda size: size + 16),
            ("sources.live.socket.MSG_TRUNC", 32),
            ("sources.live.socket.MSG_CTRUNC", 8),
        ):
            p = patch(target, value, create=True)
            p.start()
            self.addCleanup(p.stop)

    def test_same_tuple_as_pcap_with_independent_l3_expectation(self):
        self.sock.recvmsg.return_value = message()
        with LiveCapture("eth0", normalizer()) as capture:
            live = capture.read()
        self.sock.bind.assert_called_once_with(("eth0", 3))
        self.sock.close.assert_called_once()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.pcap"
            stream = io.BytesIO()
            dpkt.pcap.Writer(stream, nano=True).writepkt(frame(), ts=5.25)
            path.write_bytes(stream.getvalue())
            self.assertEqual(live, list(read_pcap(path, normalizer()))[0])
        self.assertEqual((live.packet_length, live.src_port, live.dst_port), (32, 1234, 9999))

    def test_loss_is_accumulated_and_capture_remains_failed(self):
        capture = LiveCapture("eth0", normalizer())
        self.sock.recvmsg.return_value = message()
        self.sock.getsockopt.side_effect = [struct.pack("=II", 100, 3)]
        with self.assertRaises(CaptureError):
            capture.read()
        self.assertEqual((capture.stats.kernel_packets, capture.stats.kernel_drops), (100, 3))
        with self.assertRaises(CaptureError):
            capture.read()
        self.sock.recvmsg.assert_called_once()
        capture.close(check_loss=False)

    def test_timeout_checks_loss_but_is_not_a_watermark(self):
        with LiveCapture("eth0", normalizer()) as capture:
            self.sock.recvmsg.side_effect = TimeoutError
            self.assertIsNone(capture.read())
            self.assertEqual(capture.stats.received, 0)

    def test_progress_timeout_uses_pre_receive_cutoff_and_rejects_late_packet(self):
        with LiveCapture("eth0", normalizer()) as capture:
            self.sock.recvmsg.side_effect = [TimeoutError(), message(ts=9)]
            with patch.object(capture, "_sample_clock", side_effect=[10.5, 11.0, 11.0]):
                self.assertEqual(capture.read_progress(), (None, 10.4))
                with self.assertRaises(CaptureError):
                    capture.read_progress()

    def test_filtered_frame_cannot_supply_idle_progress(self):
        with LiveCapture("eth0", normalizer()) as capture:
            self.sock.recvmsg.return_value = message(outgoing=True)
            self.assertEqual(capture.read_progress(), (None, None))

    def test_clock_step_fails_progress(self):
        capture = LiveCapture("eth0", normalizer())
        self.sock.recvmsg.side_effect = TimeoutError
        with (
            patch("sources.live.time.time", side_effect=[100, 110]),
            patch("sources.live.time.monotonic", side_effect=[1, 1, 1.25, 1.25]),
            self.assertRaises(CaptureError),
        ):
            capture.read_progress()
        with self.assertRaises(CaptureError):
            capture.read()
        capture.close(check_loss=False)

    def test_backlogged_packet_fails_pipeline_before_feature_emission(self):
        from gateway.pipeline import WindowFeaturePipeline

        capture = LiveCapture("eth0", normalizer())
        pipeline = WindowFeaturePipeline(5)
        self.sock.recvmsg.return_value = message(ts=5)
        with patch.object(capture, "_sample_clock", side_effect=[10, 10.1]):
            with self.assertRaises(CaptureError):
                pipeline.capture_once(capture)
        self.assertEqual(pipeline.buffered_packets, 0)
        self.assertEqual(pipeline.status, "invalid")
        self.assertGreater(pipeline.reset_generation, 0)
        capture.close(check_loss=False)

    def test_truncated_frame_and_control_data_fail(self):
        for flags in (32, 8):
            with self.subTest(flags=flags):
                capture = LiveCapture("eth0", normalizer())
                self.sock.recvmsg.return_value = message(flags=flags)
                with self.assertRaises(CaptureError):
                    capture.read()
                self.assertEqual(capture.stats.truncated, 1)
                capture.close(check_loss=False)

    def test_timestamp_missing_invalid_or_backward_fails(self):
        for ancillary in (
            [],
            [(socket.SOL_SOCKET, SO_TIMESTAMPNS_NEW, bytes(8))],
            [(socket.SOL_SOCKET, SO_TIMESTAMPNS_NEW, struct.pack("=qq", 1, 1_000_000_000))],
        ):
            with self.assertRaises(CaptureError):
                kernel_timestamp(ancillary)
        capture = LiveCapture("eth0", normalizer())
        self.sock.recvmsg.side_effect = [message(ts=10), message(ts=9)]
        capture.read()
        with self.assertRaises(CaptureError):
            capture.read()
        self.assertEqual(capture.stats.timestamp_errors, 1)
        capture.close(check_loss=False)

    def test_outgoing_and_non_ip_filtered_separately(self):
        with LiveCapture("eth0", normalizer()) as capture:
            self.sock.recvmsg.side_effect = [
                message(outgoing=True),
                message(data=bytes(12) + b"\x08\x06" + bytes(28)),
            ]
            self.assertIsNone(capture.read())
            self.assertIsNone(capture.read())
            self.assertEqual(capture.stats.outgoing_filtered, 1)
            self.assertEqual(capture.normalizer.stats.non_ip, 1)

    def test_malformed_packet_is_not_swallowed(self):
        capture = LiveCapture("eth0", normalizer())
        self.sock.recvmsg.return_value = message(data=b"short")
        with self.assertRaises(PacketError):
            capture.read()
        self.assertEqual(capture.normalizer.stats.malformed, 1)
        capture.close(check_loss=False)

    def test_cleanup_on_unsupported_link_and_setup_failure(self):
        self.sock.getsockname.return_value = ("lo", 3, 0, 772, bytes(6))
        with self.assertRaises(CaptureError):
            LiveCapture("lo", normalizer())
        self.sock.close.assert_called_once()
        self.sock.reset_mock()
        self.sock.bind.side_effect = PermissionError
        with self.assertRaises(PermissionError):
            LiveCapture("eth0", normalizer())
        self.sock.close.assert_called_once()

    def test_shutdown_loss_checked_and_socket_closed_even_on_error(self):
        capture = LiveCapture("eth0", normalizer())
        self.sock.getsockopt.side_effect = [struct.pack("=II", 10, 1)]
        with self.assertRaises(CaptureError):
            capture.close()
        self.sock.close.assert_called_once()
        capture.close()  # idempotent

    def test_platform_and_buffer_validation(self):
        with patch("sources.live.sys.platform", "win32"), self.assertRaises(OSError):
            LiveCapture("eth0", normalizer())
        for size in (0, True, 4095, 67108865):
            with self.subTest(size=size), self.assertRaises(ValueError):
                LiveCapture("eth0", normalizer(), receive_bytes=size)


if __name__ == "__main__":
    unittest.main()
