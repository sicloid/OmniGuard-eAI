"""Collect a bounded, device-scoped benign-evaluation PCAP on Linux.

This tool is for KAN-66 evaluation evidence. It is separate from ``sources.live``:
it records raw frames (and therefore may contain payload) outside Git so the frozen
detector can later be scored on a controlled scenario. It neither loads a model nor
changes policy, firewall, routing, or interface configuration.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import socket
import struct
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

ETH_P_ALL = 3
PACKET_OUTGOING = 4
SOL_PACKET = 263
PACKET_STATISTICS = 6
SO_TIMESTAMPNS_NEW = 64
ETH_P_IP = 0x0800
ETH_P_IPV6 = 0x86DD
VLAN_TYPES = frozenset({0x8100, 0x88A8, 0x9100})
SCENARIOS = ("idle", "dns_https", "file_download", "reconnect", "update")
MAX_DURATION_SECONDS = 3600


class CapturePlanError(ValueError):
    """A requested benign-evaluation capture would be ambiguous or unsafe."""


@dataclass
class CaptureStats:
    received_frames: int = 0
    device_frames: int = 0
    written_frames: int = 0
    outgoing_frames: int = 0
    non_ip_or_unparseable: int = 0
    kernel_packets: int = 0
    kernel_drops: int = 0


def _kernel_timestamp(ancillary) -> float:
    """Read the Linux time64 SO_TIMESTAMPNS_NEW ancillary value locally.

    The Pi capture tool deliberately does not import ``sources.live`` because the
    project runtime is currently pinned to Python 3.14 while the Pi's system Python
    is 3.13. The UAPI layout is the same checked two signed 64-bit fields.
    """
    stamps = [
        data
        for level, kind, data in ancillary
        if level == socket.SOL_SOCKET and kind == SO_TIMESTAMPNS_NEW
    ]
    if len(stamps) != 1 or len(stamps[0]) != 16:
        raise CapturePlanError("missing or malformed kernel nanosecond timestamp")
    seconds, nanos = struct.unpack("=qq", stamps[0])
    if seconds < 0 or not 0 <= nanos < 1_000_000_000:
        raise CapturePlanError("invalid kernel timestamp value")
    return seconds + nanos / 1_000_000_000


def _ethernet_ip_addresses(frame: bytes) -> tuple[str, str] | None:
    """Return Ethernet-carried IP source/destination text without parsing payload."""
    if len(frame) < 14:
        return None
    ethertype = struct.unpack("!H", frame[12:14])[0]
    offset = 14
    while ethertype in VLAN_TYPES:
        if len(frame) < offset + 4:
            return None
        ethertype = struct.unpack("!H", frame[offset + 2 : offset + 4])[0]
        offset += 4
    if ethertype == ETH_P_IP:
        if len(frame) < offset + 20 or frame[offset] >> 4 != 4:
            return None
        return str(ipaddress.IPv4Address(frame[offset + 12 : offset + 16])), str(
            ipaddress.IPv4Address(frame[offset + 16 : offset + 20])
        )
    if ethertype == ETH_P_IPV6:
        if len(frame) < offset + 40 or frame[offset] >> 4 != 6:
            return None
        return str(ipaddress.IPv6Address(frame[offset + 8 : offset + 24])), str(
            ipaddress.IPv6Address(frame[offset + 24 : offset + 40])
        )
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _boot_id() -> str | None:
    try:
        value = Path("/proc/sys/kernel/random/boot_id").read_text("utf-8").strip()
    except OSError:
        return None
    return value or None


def _restore_invoking_owner(paths: tuple[Path, ...]) -> None:
    """Return root-created evidence files to the user who invoked sudo, if known."""
    if os.geteuid() != 0:
        return
    uid, gid = os.environ.get("SUDO_UID"), os.environ.get("SUDO_GID")
    if uid is None or gid is None or not uid.isdecimal() or not gid.isdecimal():
        return
    for path in paths:
        if path.exists():
            os.chown(path, int(uid), int(gid))


def _write_global_header(handle) -> None:
    """Write a little-endian classic-PCAP header for Ethernet frames."""
    handle.write(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1))


def _write_record(handle, frame: bytes, timestamp_ns: int) -> None:
    seconds, nanos = divmod(timestamp_ns, 1_000_000_000)
    handle.write(struct.pack("<IIII", seconds, nanos // 1000, len(frame), len(frame)))
    handle.write(frame)


def _manifest(
    *,
    args,
    status: str,
    stats: CaptureStats,
    start_unix: float,
    start_mono: float,
    pcap: Path,
    partial: bool,
    error: str | None = None,
) -> dict:
    ended_unix = time.time()
    return {
        "schema": "omniguard-benign-evaluation-capture/1",
        "status": status,
        "run_id": str(uuid.uuid4()),
        "scenario": args.scenario,
        "label": "benign",
        "label_source": "controlled-scenario",
        "label_limit": (
            "The operator controlled the named scenario; this is not a flow-level ground-truth "
            "label and must not silently enter model training."
        ),
        "interface": args.interface,
        "lan_cidrs": args.lan,
        "device_ip": str(args.device_ip),
        "device_id": args.device_id,
        "host": {"boot_id": _boot_id(), "platform": sys.platform},
        "clock": {
            "started_unix": start_unix,
            "ended_unix": ended_unix,
            "elapsed_monotonic_seconds": time.monotonic() - start_mono,
        },
        "pcap": {
            "path": pcap.name,
            "sha256": _sha256(pcap) if pcap.exists() else None,
            "partial": partial,
            "contains_raw_frames": True,
        },
        "stats": asdict(stats),
        "error": error,
    }


def _validate_args(args) -> None:
    if sys.platform != "linux":
        raise CapturePlanError("benign evaluation capture requires Linux AF_PACKET")
    if not args.interface or args.interface == "lo":
        raise CapturePlanError("interface must name a non-loopback Ethernet interface")
    if not 1 <= args.duration <= MAX_DURATION_SECONDS:
        raise CapturePlanError(f"duration must be between 1 and {MAX_DURATION_SECONDS} seconds")
    if not args.device_id.strip():
        raise CapturePlanError("device_id must be nonempty")
    networks = [ipaddress.ip_network(value, strict=False) for value in args.lan]
    if not any(args.device_ip in network for network in networks):
        raise CapturePlanError("device_ip must belong to one declared LAN CIDR")
    if args.out.exists() and any(args.out.iterdir()):
        raise CapturePlanError(
            "output directory already contains evidence; choose a new run directory"
        )


def _check_loss(sock, stats: CaptureStats) -> None:
    """Accumulate Linux reset-on-read packet counters and reject any socket loss."""
    raw = sock.getsockopt(SOL_PACKET, PACKET_STATISTICS, 8)
    if len(raw) != 8:
        raise CapturePlanError("unexpected packet statistics layout")
    packets, drops = struct.unpack("=II", raw)
    stats.kernel_packets += packets
    stats.kernel_drops += drops
    if drops:
        raise CapturePlanError("packet socket dropped traffic; capture is incomplete")


def collect(args) -> dict:
    _validate_args(args)
    args.out.mkdir(parents=True, exist_ok=True)
    partial = args.out / "capture.pcap.partial"
    completed = args.out / "capture.pcap"
    manifest_path = args.out / "manifest.json"
    stats = CaptureStats()
    start_unix = time.time()
    start_mono = time.monotonic()
    status, error, is_partial = "completed", None, False
    sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
    try:
        sock.bind((args.interface, 0))
        sock.setsockopt(socket.SOL_SOCKET, SO_TIMESTAMPNS_NEW, 1)
        sock.settimeout(min(0.5, args.duration))
        with open(partial, "xb") as handle:
            _write_global_header(handle)
            deadline = start_mono + args.duration
            while (remaining := deadline - time.monotonic()) > 0:
                sock.settimeout(min(0.5, remaining))
                try:
                    frame, ancillary, flags, address = sock.recvmsg(65535, socket.CMSG_SPACE(16))
                except TimeoutError:
                    _check_loss(sock, stats)
                    continue
                stats.received_frames += 1
                _check_loss(sock, stats)
                if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC):
                    raise CapturePlanError("truncated frame or timestamp control data")
                addresses = _ethernet_ip_addresses(frame)
                if addresses is None:
                    stats.non_ip_or_unparseable += 1
                    continue
                if str(args.device_ip) not in addresses:
                    continue
                stats.device_frames += 1
                if address[2] == PACKET_OUTGOING:
                    stats.outgoing_frames += 1
                _write_record(handle, frame, round(_kernel_timestamp(ancillary) * 1_000_000_000))
                stats.written_frames += 1
        _check_loss(sock, stats)
        if stats.written_frames == 0:
            raise CapturePlanError("no frames matched device_ip; capture is not valid evidence")
        partial.replace(completed)
        pcap, is_partial = completed, False
    except KeyboardInterrupt:
        status, error, pcap, is_partial = (
            "interrupted",
            "operator interrupted capture",
            partial,
            True,
        )
    except Exception as exc:
        status, error, pcap, is_partial = "failed", f"{type(exc).__name__}: {exc}", partial, True
    finally:
        sock.close()
    manifest = _manifest(
        args=args,
        status=status,
        stats=stats,
        start_unix=start_unix,
        start_mono=start_mono,
        pcap=pcap,
        partial=is_partial,
        error=error,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _restore_invoking_owner((pcap, manifest_path))
    if status != "completed":
        raise CapturePlanError(f"capture {status}; see {manifest_path}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--lan", action="append", required=True)
    parser.add_argument("--device-ip", type=ipaddress.ip_address, required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--scenario", choices=SCENARIOS, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(collect(args), indent=2, sort_keys=True))
    except (CapturePlanError, OSError) as exc:
        parser.exit(2, f"benign capture rejected: {exc}\n")


if __name__ == "__main__":
    main()
