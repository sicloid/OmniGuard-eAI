"""Linux Ethernet ingress capture into the same PacketTuple as classic PCAP.

Requires CAP_NET_RAW in the target namespace. No model or enforcement code runs
here. Frames briefly include payload in memory; only normalized metadata leaves
the adapter. No background application queue or capture-file writer is created.
"""

import argparse
import json
import socket
import struct
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from core.schema import PacketTuple, nonempty, number
from sources.packets import PacketError, PacketNormalizer

# Linux UAPI values absent from some Python builds; NEW uses two signed 64-bit
# fields on both 32/64-bit userspace. Require Linux with time64 socket support.
SOL_PACKET = 263
PACKET_STATISTICS = 6
PACKET_IGNORE_OUTGOING = 23
SO_TIMESTAMPNS_NEW = 64
ETH_P_ALL = 3
PACKET_OUTGOING = 4
MAX_FRAME = 131072


class CaptureError(RuntimeError):
    """Capture integrity failed; earlier output must not imply complete observation."""


@dataclass
class CaptureStats:
    received: int = 0
    kernel_packets: int = 0
    kernel_drops: int = 0
    outgoing_filtered: int = 0
    truncated: int = 0
    timestamp_errors: int = 0
    receive_buffer_bytes: int = 0


def kernel_timestamp(ancillary) -> float:
    stamps = [
        data
        for level, kind, data in ancillary
        if level == socket.SOL_SOCKET and kind == SO_TIMESTAMPNS_NEW
    ]
    if len(stamps) != 1 or len(stamps[0]) != 16:
        raise CaptureError("missing or malformed kernel nanosecond timestamp")
    seconds, nanos = struct.unpack("=qq", stamps[0])
    if seconds < 0 or not 0 <= nanos < 1_000_000_000:
        raise CaptureError("invalid kernel timestamp value")
    return seconds + nanos / 1_000_000_000


class LiveCapture:
    """Single-reader, bounded socket buffer; fail on detected socket loss.

    read() returning None means timeout or a filtered frame, not a healthy idle
    watermark. Capture statistics cover this socket, not NIC/driver/upstream loss.
    Strict order is the default. With strict_order=False, a bounded ordering
    adapter must sort original timestamps before any window/policy consumer.
    """

    def __init__(
        self,
        interface: str,
        normalizer: PacketNormalizer,
        *,
        receive_bytes: int = 1048576,
        strict_order: bool = True,
    ):
        if sys.platform != "linux":
            raise OSError("live capture requires Linux")
        nonempty(interface, "interface")
        if type(receive_bytes) is not int or not 4096 <= receive_bytes <= 67108864:
            raise ValueError("receive_bytes must be an integer from 4096 to 64 MiB")
        if type(strict_order) is not bool:
            raise ValueError("strict_order must be a boolean")
        self.normalizer = normalizer
        self.strict_order = strict_order
        self.stats = CaptureStats()
        self._last_timestamp = -1.0
        self._failed = False
        self._closed = False
        self._timed_out = False
        self._clock_offset = None
        # Protocol zero prevents collecting other interfaces before explicit bind.
        self._socket = socket.socket(getattr(socket, "AF_PACKET", 17), socket.SOCK_RAW, 0)
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, receive_bytes)
            self.stats.receive_buffer_bytes = self._socket.getsockopt(
                socket.SOL_SOCKET, socket.SO_RCVBUF
            )
            self._socket.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS_NEW, 1)
            self._socket.setsockopt(SOL_PACKET, PACKET_IGNORE_OUTGOING, 1)
            self._socket.bind((interface, ETH_P_ALL))
            if self._socket.getsockname()[3] != 1:  # ARPHRD_ETHER
                raise CaptureError("only Ethernet interfaces supported; not loopback/cooked")
        except BaseException:
            self._socket.close()
            self._closed = True
            raise

    def check_loss(self) -> None:
        """Accumulate reset-on-read Linux PACKET_STATISTICS and reject any loss."""
        raw = self._socket.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)
        if len(raw) != 8:
            self._failed = True
            raise CaptureError("unexpected packet statistics layout")
        packets, drops = struct.unpack("=II", raw)
        self.stats.kernel_packets += packets
        self.stats.kernel_drops += drops
        if drops:
            self._failed = True
            raise CaptureError("packet socket dropped traffic; observation is incomplete")

    def read(self, timeout: float = 0.25) -> PacketTuple | None:
        self._timed_out = False
        if self._closed or self._failed:
            raise CaptureError("capture closed or failed; start a new observation session")
        number(timeout, "timeout")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        try:
            self._socket.settimeout(timeout)
            try:
                frame, ancillary, flags, address = self._socket.recvmsg(
                    MAX_FRAME, socket.CMSG_SPACE(16)
                )
            except TimeoutError:
                self.check_loss()
                self._timed_out = True
                return None
            self.stats.received += 1
            self.check_loss()
            if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                self.stats.truncated += 1
                raise CaptureError("truncated frame or timestamp control data")
            if address[2] == PACKET_OUTGOING:
                self.stats.outgoing_filtered += 1
                return None
            try:
                timestamp = kernel_timestamp(ancillary)
                if self.strict_order and timestamp < self._last_timestamp:
                    raise CaptureError(
                        "kernel timestamps moved backward/out of order: "
                        f"previous={self._last_timestamp:.9f} current={timestamp:.9f} "
                        f"delta={self._last_timestamp - timestamp:.9f}s"
                    )
            except CaptureError:
                self.stats.timestamp_errors += 1
                raise
            self._last_timestamp = max(self._last_timestamp, timestamp)
            return self.normalizer.parse(timestamp, frame, 1)
        except CaptureError, PacketError, OSError:
            self._failed = True
            raise

    def read_progress(self, timeout: float = 0.25) -> tuple[PacketTuple | None, float | None]:
        """Ordered socket progress; only a real empty receive supplies idle time.

        The cutoff precedes recvmsg, so a queued packet is read before advancing.
        A 100 ms clock-offset guard is subtracted from idle progress. Any observed
        offset drift beyond it fails the session. In strict mode a later packet
        below the cutoff is fatal; in non-strict mode the ordering wrapper must
        reject it before the window/policy boundary.
        It does not certify NIC/upstream completeness.
        """
        try:
            before = self._sample_clock()
            packet = self.read(timeout)
            after = self._sample_clock()
            if after < before:
                raise CaptureError("UTC clock moved backward during receive")
            if packet is not None and not -0.1 <= after - packet.timestamp <= 1.0:
                raise CaptureError("packet timestamp is stale or in the future")
            if self._timed_out:
                cutoff = max(self._last_timestamp, before - 0.1, 0.0)
                self._last_timestamp = cutoff
                return None, cutoff
            return packet, None
        except CaptureError, OSError, ValueError:
            self._failed = True
            raise

    def _sample_clock(self) -> float:
        mono_before = time.monotonic()
        utc = time.time()
        mono_after = time.monotonic()
        number(utc, "UTC")
        if not 0 <= mono_after - mono_before <= 0.01:
            raise CaptureError("clock sample scheduling uncertainty")
        offset = utc - (mono_before + mono_after) / 2
        if self._clock_offset is None:
            self._clock_offset = offset
        if abs(offset - self._clock_offset) > 0.1:
            raise CaptureError("UTC/monotonic clock offset changed")
        return utc

    def close(self, *, check_loss: bool = True) -> None:
        if self._closed:
            return
        try:
            if check_loss:
                self.check_loss()
        finally:
            self._socket.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close(check_loss=exc_type is None)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--lan", action="append", required=True)
    parser.add_argument("--devices", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--receive-bytes", type=int, default=1048576)
    args = parser.parse_args()
    capture = normalizer = None
    try:
        number(args.duration, "duration")
        if args.duration <= 0:
            raise ValueError("duration must be positive")
        normalizer = PacketNormalizer(args.lan, json.loads(args.devices.read_text("utf-8")))
        with LiveCapture(args.interface, normalizer, receive_bytes=args.receive_bytes) as capture:
            print(
                json.dumps({"ready": True, "interface": args.interface}),
                file=sys.stderr,
                flush=True,
            )
            deadline = time.monotonic() + args.duration
            while (remaining := deadline - time.monotonic()) > 0:
                packet = capture.read(timeout=min(remaining, 0.25))
                if packet is not None:
                    print(json.dumps(asdict(packet), allow_nan=False), flush=True)
    except (OSError, ValueError, CaptureError) as exc:
        parser.exit(2, f"live capture rejected: {exc}\n")
    except KeyboardInterrupt:
        parser.exit(130, "capture interrupted; final interval is incomplete\n")
    finally:
        if normalizer is not None:
            print(
                json.dumps(
                    {
                        "normalizer": asdict(normalizer.stats),
                        "capture": asdict(capture.stats) if capture else None,
                    }
                ),
                file=sys.stderr,
                flush=True,
            )


if __name__ == "__main__":
    main()
