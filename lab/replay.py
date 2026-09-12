"""Audited, prepared Ethernet/IPv4 PCAP replay in the owned og-a namespace only."""

import argparse
import hashlib
import json
import math
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import dpkt

from sources.from_pcap import _BoundedCaptureStream
from sources.packets import PacketNormalizer


def command(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=10).stdout


def mac_bytes(address):
    parts = address.split(":")
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        raise ValueError("expected Ethernet MAC")
    value = bytes(int(part, 16) for part in parts)
    if value[0] & 1 or value == bytes(6):
        raise ValueError("expected nonzero unicast MAC")
    return value


def verify_lab():
    """Read-only ownership/topology check; no interface/firewall mutations."""
    if sys.platform != "linux" or os.geteuid() != 0:
        raise PermissionError("replay requires root inside the isolated Linux lab")
    state = Path("/run/omniguard-lab")
    if (
        state.is_symlink()
        or state.stat().st_uid != 0
        or stat.S_IMODE(state.stat().st_mode) != 0o700
    ):
        raise PermissionError("unsafe lab ownership directory")
    with os.fdopen(os.open(state / "owned", os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != 0 or not stat.S_ISREG(info.st_mode):
            raise PermissionError("unsafe ownership record")
        owned = dict(line.split() for line in stream)
    if set(owned) != {"og-a", "og-b", "og-c"}:
        raise PermissionError("expected complete owned A/B/C lab")
    expected = {"og-a": {"lo", "og-a0"}, "og-b": {"lo", "og-b0", "og-b1"}, "og-c": {"lo", "og-c0"}}
    links = {}
    for ns in expected:
        info = Path(f"/run/netns/{ns}").stat()
        if owned[ns] != f"{info.st_dev}:{info.st_ino}":
            raise PermissionError("namespace identity differs from ownership record")
        links[ns] = json.loads(command("ip", "-n", ns, "-j", "link"))
        if {link["ifname"] for link in links[ns]} != expected[ns]:
            raise PermissionError("unexpected interface in replay lab")
        for family in ("-4", "-6"):
            if json.loads(command("ip", family, "-n", ns, "-j", "route", "show", "default")):
                raise PermissionError("default route forbidden in replay lab")
    current = Path("/proc/self/ns/net").stat()
    if owned["og-a"] != f"{current.st_dev}:{current.st_ino}":
        raise PermissionError("run via ip netns exec og-a; host/gateway replay refused")
    source = next(link["address"] for link in links["og-a"] if link["ifname"] == "og-a0")
    gateway = next(link["address"] for link in links["og-b"] if link["ifname"] == "og-b0")
    mtu = next(link["mtu"] for link in links["og-a"] if link["ifname"] == "og-a0")
    return mac_bytes(source), mac_bytes(gateway), mtu, owned


@contextmanager
def snapshot(path, limit):
    """Validate and transmit the same immutable private snapshot, with bounded I/O."""
    if type(limit) is not int or limit < 24:
        raise ValueError("snapshot byte limit must be >= 24")
    digest, total = hashlib.sha256(), 0
    with open(path, "rb") as source, tempfile.TemporaryFile("w+b") as target:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("capture input must be a regular file")
        while chunk := source.read(min(1048576, limit - total + 1)):
            total += len(chunk)
            if total > limit:
                raise ValueError("capture exceeds configured snapshot byte limit")
            digest.update(chunk)
            target.write(chunk)
        target.seek(0)
        yield target, digest.hexdigest(), total


def frames(stream):
    stream.seek(0)
    reader = dpkt.pcap.Reader(_BoundedCaptureStream(stream))
    if reader.datalink() != 1:
        raise ValueError("prepared replay requires classic Ethernet PCAP")
    for timestamp, frame in reader:
        yield Decimal(str(timestamp)), frame


def audit(stream, mtu, max_seconds):
    """Reject the entire input before opening the send socket; never silently filter."""
    normalizer = PacketNormalizer(["10.203.1.0/24"], {"10.203.1.2": "replay-source"})
    first = last = None
    count = 0
    for timestamp, frame in frames(stream):
        if not timestamp.is_finite() or timestamp < 0 or (last is not None and timestamp < last):
            raise ValueError("capture times must be finite, nonnegative and ordered")
        if first is None:
            first = timestamp
        if timestamp - first > Decimal(str(max_seconds)):
            raise ValueError("capture duration exceeds configured limit")
        # No hidden VLAN/IP rewrite, fragments or truncation. Dataset preparation
        # must explicitly map traffic to this fixed lab before this command.
        if len(frame) < 34 or frame[12:14] != b"\x08\x00" or frame[14] != 0x45:
            raise ValueError("prepared replay requires untagged IPv4 without IP options")
        packet = normalizer.parse(float(timestamp), frame)
        if packet is None or packet.src_ip != "10.203.1.2" or packet.dst_ip != "10.203.2.2":
            raise ValueError("prepared IP addresses must be 10.203.1.2 -> 10.203.2.2")
        if packet.packet_length > mtu or len(frame) != 14 + packet.packet_length:
            raise ValueError("frame must have exact L3 length within source MTU")
        if int.from_bytes(frame[20:22], "big") & 0x3FFF:
            raise ValueError("fragmented replay requires a separate preparation policy")
        if dpkt.in_cksum(frame[14:34]) != 0:
            raise ValueError("invalid IPv4 checksum")
        count += 1
        last = timestamp
    if not count:
        raise ValueError("empty capture")
    return {"packets": count, "first_capture_ts": str(first), "last_capture_ts": str(last)}


def save_manifest(path, manifest):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def transmit(stream, send, log, *, first_timestamp, speed, reference_record, clock=time):
    """Log scheduled, call-begin and call-return times; return is not sink receipt."""
    before = clock.monotonic_ns()
    utc = clock.time_ns()
    after = clock.monotonic_ns()
    origin = after
    mapping = {"utc_ns": utc, "monotonic_before_ns": before, "monotonic_after_ns": after}
    log.write(json.dumps({"type": "clock_mapping", **mapping}) + "\n")
    log.flush()
    sent, reference, maximum_lag = 0, None, 0
    for index, (timestamp, frame) in enumerate(frames(stream), 1):
        offset = int(
            (timestamp - Decimal(first_timestamp)) * Decimal(1_000_000_000) / Decimal(str(speed))
        )
        target = origin + offset
        while (remaining := target - clock.monotonic_ns()) > 0:
            clock.sleep(min(remaining / 1e9, 0.1))
        intent = clock.monotonic_ns()
        # Record intent before send: interruption/failure cannot look like unsent
        # work with no trace. A begin without return has unknown submission status.
        entry = {
            "record": index,
            "capture_ts": str(timestamp),
            "scheduled_ns": target,
            "intent_ns": intent,
            "l3_bytes": len(frame) - 14,
        }
        log.write(json.dumps({"type": "send_begin", **entry}) + "\n")
        log.flush()
        begin = clock.monotonic_ns()
        entry["send_begin_ns"] = begin
        length = send(frame)
        returned = clock.monotonic_ns()
        if length != len(frame):
            raise OSError("short frame send")
        entry["send_return_ns"] = returned
        log.write(json.dumps({"type": "send_return", **entry}) + "\n")
        log.flush()
        if index == reference_record:
            reference = entry
        sent += 1
        maximum_lag = max(maximum_lag, begin - target)
    return {
        "sent_packets": sent,
        "clock_mapping": mapping,
        "reference_t0": reference,
        "max_schedule_lag_ns": maximum_lag,
    }


def replay(
    path,
    output_root,
    provenance,
    *,
    speed=1.0,
    reference_record=1,
    attack_start=False,
    max_bytes=268435456,
    max_seconds=3600,
):
    if isinstance(speed, bool) or not math.isfinite(speed) or not 0 < speed <= 100:
        raise ValueError("speed must be finite in (0,100]")
    if type(reference_record) is not int or reference_record < 1:
        raise ValueError("reference_record is a positive one-based packet index")
    if not math.isfinite(max_seconds) or not 0 < max_seconds <= 86400:
        raise ValueError("max_seconds must be in (0,86400]")
    if (
        not isinstance(provenance, dict)
        or not isinstance(provenance.get("source"), str)
        or not provenance["source"].strip()
        or not isinstance(provenance.get("transformations"), list)
    ):
        raise ValueError("provenance requires source text and an explicit transformations list")
    run_id = str(uuid.uuid4())
    directory = Path(output_root) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest = {
        "run_id": run_id,
        "status": "validating",
        "provenance": provenance,
        "speed": speed,
        "reference_record": reference_record,
        "t0_meaning": "user-labelled attack start submission"
        if attack_start
        else "replay reference submission",
        "python": sys.version,
        "dpkt": dpkt.__version__,
        "kernel": os.uname().release if sys.platform == "linux" else None,
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "limits": {"snapshot_bytes": max_bytes, "capture_seconds": max_seconds},
    }
    target = directory / "manifest.json"
    save_manifest(target, manifest)
    try:
        src_mac, dst_mac, mtu, owned = verify_lab()
        manifest["namespace_ownership"] = owned
        manifest["ethernet_rewrite"] = {"source": src_mac.hex(":"), "destination": dst_mac.hex(":")}
        with snapshot(path, max_bytes) as (stream, digest, size):
            manifest.update({"prepared_pcap_sha256": digest, "prepared_bytes": size})
            details = audit(stream, mtu, max_seconds)
            manifest.update(details)
            if reference_record > details["packets"]:
                raise ValueError("reference_record outside capture")
            manifest["status"] = "running"
            save_manifest(target, manifest)
            with (
                socket.socket(getattr(socket, "AF_PACKET", 17), socket.SOCK_RAW, 0) as sock,
                (directory / "events.jsonl").open("x") as log,
            ):
                sock.bind(("og-a0", 0))
                result = transmit(
                    stream,
                    lambda frame: sock.send(dst_mac + src_mac + frame[12:]),
                    log,
                    first_timestamp=details["first_capture_ts"],
                    speed=speed,
                    reference_record=reference_record,
                )
            manifest.update(result)
            manifest["status"] = "complete"
    except BaseException as exc:
        manifest["status"] = "cancelled" if isinstance(exc, KeyboardInterrupt) else "failed"
        manifest["error_type"] = type(exc).__name__
        manifest["error"] = str(exc)
        raise
    finally:
        save_manifest(target, manifest)
        print(
            json.dumps({"run_id": run_id, "manifest": str(target), "status": manifest["status"]}),
            flush=True,
        )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--reference-record", type=int, default=1)
    parser.add_argument("--attack-start", action="store_true")
    parser.add_argument("--max-bytes", type=int, default=268435456)
    parser.add_argument("--max-seconds", type=float, default=3600)
    args = parser.parse_args()
    try:
        replay(
            args.capture,
            args.output,
            json.loads(args.provenance.read_text()),
            speed=args.speed,
            reference_record=args.reference_record,
            attack_start=args.attack_start,
            max_bytes=args.max_bytes,
            max_seconds=args.max_seconds,
        )
    except (OSError, ValueError, dpkt.UnpackError, subprocess.SubprocessError) as exc:
        parser.exit(2, f"replay rejected: {exc}\n")


if __name__ == "__main__":
    main()
