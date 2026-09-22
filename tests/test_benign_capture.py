import ipaddress
import socket
import struct
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sources.benign_capture import (
    CapturePlanError,
    _ethernet_ip_addresses,
    _kernel_timestamp,
    _validate_args,
    _write_global_header,
    _write_record,
)


def ethernet_ipv4(source="192.168.1.2", destination="8.8.8.8"):
    return (
        b"\x00" * 12
        + struct.pack("!H", 0x0800)
        + b"\x45\x00\x00\x14\x00\x00\x00\x00\x40\x11\x00\x00"
        + ipaddress.IPv4Address(source).packed
        + ipaddress.IPv4Address(destination).packed
    )


class BenignCaptureTests(unittest.TestCase):
    def args(self, out):
        return Namespace(
            interface="wlan0",
            lan=["192.168.1.0/24"],
            device_ip=ipaddress.ip_address("192.168.1.2"),
            device_id="pi5-benign",
            duration=300,
            out=Path(out),
        )

    def test_extracts_ipv4_addresses_from_ethernet(self):
        self.assertEqual(_ethernet_ip_addresses(ethernet_ipv4()), ("192.168.1.2", "8.8.8.8"))

    def test_rejects_truncated_and_non_ip_frames(self):
        self.assertIsNone(_ethernet_ip_addresses(b"\x00" * 13))
        self.assertIsNone(_ethernet_ip_addresses(b"\x00" * 12 + struct.pack("!H", 0x0806)))

    def test_reads_the_linux_time64_timestamp_shape(self):
        ancillary = [(socket.SOL_SOCKET, 64, struct.pack("=qq", 3, 250_000_000))]
        self.assertEqual(_kernel_timestamp(ancillary), 3.25)
        with self.assertRaisesRegex(CapturePlanError, "missing"):
            _kernel_timestamp([])

    def test_writes_classic_pcap_headers(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "capture.pcap"
            with open(path, "xb") as handle:
                _write_global_header(handle)
                _write_record(handle, ethernet_ipv4(), 1_250_000_000)
            raw = path.read_bytes()
            self.assertEqual(raw[:4], b"\xd4\xc3\xb2\xa1")
            self.assertEqual(len(raw), 24 + 16 + len(ethernet_ipv4()))

    def test_rejects_output_reuse_and_ip_outside_lan(self):
        with TemporaryDirectory() as temporary:
            out = Path(temporary) / "run"
            out.mkdir()
            (out / "old.json").write_text("{}", encoding="utf-8")
            with patch("sources.benign_capture.sys.platform", "linux"):
                with self.assertRaisesRegex(CapturePlanError, "already contains"):
                    _validate_args(self.args(out))
                args = self.args(Path(temporary) / "new")
                args.device_ip = ipaddress.ip_address("10.0.0.1")
                with self.assertRaisesRegex(CapturePlanError, "must belong"):
                    _validate_args(args)
