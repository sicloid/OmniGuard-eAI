"""KAN-33 dedicated Linux containment-leakage evidence.

The fixture is intentionally harmless IPv4/UDP traffic inside the A->B->C lab.
It does not classify traffic with Direction.EGRESS. A raw AF_PACKET sink in og-c
records delivered packets independently, including the IPv4 total length as L3 bytes.

All source, sink and enforcer timestamps are CLOCK_MONOTONIC readings from the same
Linux boot, whose boot_id is recorded and checked before correlation.
"""

import argparse
import json
import shutil
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

from gateway.enforcer import DeviceBinding, EnforcementAction, NftEnforcer
from measure.leakage import MonotonicInterval, SinkDelivery, summarize_leakage

PORT = 49010
SOURCE_PORT = 49011
PAYLOAD = b"OG-LEAKAGE-PROBE".ljust(64, b".")
ETH_P_ALL = 0x0003
SOL_PACKET = 263
PACKET_STATISTICS = 6
TP_STATS = struct.Struct("II")


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=30).stdout


def current_boot_id() -> str:
    value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("kernel boot_id is empty")
    return value


def write_json_atomic(path: Path, document: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def wait_for_marker(path: Path, process, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("source exited before t0 marker")
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        time.sleep(0.005)
    raise TimeoutError("t0 marker timeout")


def wait_ready(path: Path, process, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"sink exited before ready: {path.read_text(encoding='utf-8')}")
        if path.exists() and path.read_text(encoding="utf-8").strip():
            line = path.read_text(encoding="utf-8").splitlines()[0]
            document = json.loads(line)
            if document.get("ready") is True:
                return document
        time.sleep(0.005)
    raise TimeoutError("sink readiness timeout")


def source(marker: Path, *, count: int, interval: float, reference_record: int) -> int:
    if not 1 <= reference_record <= count:
        raise ValueError("reference_record must be within the generated sequence")
    boot_id = current_boot_id()
    l3_bytes = 20 + 8 + len(PAYLOAD)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("10.203.1.2", SOURCE_PORT))
        for record in range(1, count + 1):
            begin = time.monotonic_ns()
            sent = sock.sendto(PAYLOAD, ("10.203.2.2", PORT))
            returned = time.monotonic_ns()
            if sent != len(PAYLOAD):
                raise OSError("short UDP send")
            event = {
                "type": "source_send",
                "record": record,
                "boot_id": boot_id,
                "begin_ns": begin,
                "return_ns": returned,
                "l3_bytes": l3_bytes,
            }
            print(json.dumps(event, sort_keys=True), flush=True)
            if record == reference_record:
                write_json_atomic(
                    marker,
                    {
                        "boot_id": boot_id,
                        "begin_ns": begin,
                        "end_ns": returned,
                        "record": record,
                        "meaning": "synthetic fixture reference packet submission",
                    },
                )
            time.sleep(interval)
    return 0


def _matches_fixture(frame: bytes) -> tuple[bool, int]:
    if len(frame) < 42 or frame[12:14] != b"\x08\x00":
        return False, 0
    ihl = (frame[14] & 0x0F) * 4
    if ihl < 20 or len(frame) < 14 + ihl + 8:
        return False, 0
    if frame[23] != socket.IPPROTO_UDP:
        return False, 0
    if frame[26:30] != bytes((10, 203, 1, 2)) or frame[30:34] != bytes((10, 203, 2, 2)):
        return False, 0
    udp = 14 + ihl
    if int.from_bytes(frame[udp : udp + 2], "big") != SOURCE_PORT:
        return False, 0
    if int.from_bytes(frame[udp + 2 : udp + 4], "big") != PORT:
        return False, 0
    total_length = int.from_bytes(frame[16:18], "big")
    if total_length < ihl + 8 or len(frame) < 14 + total_length:
        return False, 0
    udp_payload = frame[udp + 8 : 14 + total_length]
    return udp_payload == PAYLOAD, total_length


def sink(*, duration: float) -> int:
    boot_id = current_boot_id()
    with (
        socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp,
        socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL)) as raw,
    ):
        udp.bind(("10.203.2.2", PORT))
        raw.bind(("og-c0", 0))
        raw.settimeout(0.05)
        print(json.dumps({"ready": True, "boot_id": boot_id}), file=sys.stderr, flush=True)
        deadline = time.monotonic() + duration
        matched = 0
        while time.monotonic() < deadline:
            try:
                frame = raw.recv(65535)
            except TimeoutError:
                continue
            observed = time.monotonic_ns()
            matches, l3_bytes = _matches_fixture(frame)
            if not matches:
                continue
            matched += 1
            print(
                json.dumps(
                    {
                        "type": "sink_delivery",
                        "boot_id": boot_id,
                        "observed_ns": observed,
                        "l3_bytes": l3_bytes,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        raw_packets, raw_drops = TP_STATS.unpack(
            raw.getsockopt(SOL_PACKET, PACKET_STATISTICS, TP_STATS.size)
        )
    print(
        json.dumps(
            {
                "type": "sink_summary",
                "boot_id": boot_id,
                "matched_packets": matched,
                "raw_packets": raw_packets,
                "raw_drops": raw_drops,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


def _json_lines(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def orchestrate() -> int:
    root = Path("/tmp/leakage-validation")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()

    before_rules = run("nft", "list", "ruleset")
    before_routes = run("ip", "-j", "route")
    (root / "parent-rules-before.txt").write_text(before_rules, encoding="utf-8")
    (root / "parent-routes-before.json").write_text(before_routes, encoding="utf-8")

    processes = []
    marker = root / "t0.json"
    binding = DeviceBinding("lab-camera", "10.203.1.2")
    enforcer = NftEnforcer()
    boot_id = current_boot_id()

    run("bash", "lab/setup_netns.sh")
    try:
        enforcer.release(binding)
        with (
            (root / "sink.jsonl").open("w", encoding="utf-8") as sink_out,
            (root / "sink.err").open("w", encoding="utf-8") as sink_err,
        ):
            sink_process = subprocess.Popen(
                [
                    "ip",
                    "netns",
                    "exec",
                    "og-c",
                    sys.executable,
                    __file__,
                    "sink",
                    "--duration",
                    "1.4",
                ],
                stdout=sink_out,
                stderr=sink_err,
                text=True,
            )
            processes.append(sink_process)
            ready = wait_ready(root / "sink.err", sink_process)
            if ready["boot_id"] != boot_id:
                raise RuntimeError("sink is not in the same boot clock domain")

            with (
                (root / "source.jsonl").open("w", encoding="utf-8") as source_out,
                (root / "source.err").open("w", encoding="utf-8") as source_err,
            ):
                source_process = subprocess.Popen(
                    [
                        "ip",
                        "netns",
                        "exec",
                        "og-a",
                        sys.executable,
                        __file__,
                        "source",
                        "--marker",
                        str(marker),
                        "--count",
                        "300",
                        "--interval",
                        "0.003",
                        "--reference-record",
                        "20",
                    ],
                    stdout=source_out,
                    stderr=source_err,
                    text=True,
                )
                processes.append(source_process)
                t0 = wait_for_marker(marker, source_process)
                if t0["boot_id"] != boot_id:
                    raise RuntimeError("source is not in the same boot clock domain")

                time.sleep(0.05)
                apply_begin = time.monotonic_ns()
                receipt = enforcer.quarantine(
                    binding,
                    lease_seconds=2.0,
                    max_lease_seconds=5.0,
                )
                apply_ack = time.monotonic_ns()
                if receipt.action is not EnforcementAction.APPLIED:
                    raise RuntimeError(f"expected fresh APPLIED receipt, got {receipt.action}")
                if not enforcer.is_quarantined(binding):
                    raise RuntimeError("kernel readback lost active quarantine")

                if source_process.wait(timeout=5):
                    raise RuntimeError("source process failed")

            if sink_process.wait(timeout=5):
                raise RuntimeError("sink process failed")

        source_rows = _json_lines(root / "source.jsonl")
        sink_rows = _json_lines(root / "sink.jsonl")
        source_events = [row for row in source_rows if row.get("type") == "source_send"]
        sink_events = [row for row in sink_rows if row.get("type") == "sink_delivery"]
        sink_summary = next(row for row in sink_rows if row.get("type") == "sink_summary")

        deliveries = [
            SinkDelivery(row["boot_id"], row["observed_ns"], row["l3_bytes"])
            for row in sink_events
        ]
        t0_interval = MonotonicInterval(
            t0["boot_id"],
            t0["begin_ns"],
            t0["end_ns"],
            t0["meaning"],
        )
        apply_interval = MonotonicInterval(
            boot_id,
            apply_begin,
            apply_ack,
            "NftEnforcer quarantine call through successful kernel readback",
        )
        leakage = summarize_leakage(
            t0_interval,
            apply_interval,
            deliveries,
            sink_complete=sink_summary["raw_drops"] == 0,
        )
        attempts_after_ack = sum(row["begin_ns"] > apply_ack for row in source_events)

        if leakage.lower_bound is None or leakage.upper_bound is None:
            raise RuntimeError("fixture unexpectedly produced censored leakage evidence")
        if leakage.lower_bound.packets < 1:
            raise RuntimeError("fixture did not produce definite pre-apply leakage")
        if attempts_after_ack < 1:
            raise RuntimeError("source did not continue after containment ACK")

        result = {
            "boot_id": boot_id,
            "coverage": {
                "address_family": "IPv4",
                "protocol": "UDP",
                "unicast": True,
                "ipv6_measured": False,
                "multicast_measured": False,
                "sink_point": "og-c0 AF_PACKET userspace observation",
            },
            "timing_semantics": {
                "t0": "reference send submission interval, not an exact instant",
                "apply": "enforcer call begin through successful nft readback return",
                "post_ack": "kept separate as in-flight-or-bypass observation",
            },
            "t0": t0,
            "apply": {
                "begin_ns": apply_begin,
                "ack_ns": apply_ack,
                "receipt": receipt.action.value,
            },
            "source_attempts": len(source_events),
            "source_attempts_after_ack": attempts_after_ack,
            "sink": sink_summary,
            "leakage": leakage.to_dict(),
        }
        (root / "summary.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        try:
            enforcer.release(binding)
        except Exception:
            pass
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        run("bash", "lab/teardown_netns.sh")

    after_rules = run("nft", "list", "ruleset")
    after_routes = run("ip", "-j", "route")
    (root / "parent-rules-after.txt").write_text(after_rules, encoding="utf-8")
    (root / "parent-routes-after.json").write_text(after_routes, encoding="utf-8")
    if after_rules != before_rules or after_routes != before_routes:
        raise RuntimeError("parent namespace rules/routes changed across leakage run")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "source", "sink"))
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--interval", type=float, default=0.003)
    parser.add_argument("--reference-record", type=int, default=20)
    parser.add_argument("--duration", type=float, default=1.4)
    args = parser.parse_args()

    if args.mode == "run":
        return orchestrate()
    if args.mode == "source":
        if args.marker is None:
            parser.error("source mode requires --marker")
        return source(
            args.marker,
            count=args.count,
            interval=args.interval,
            reference_record=args.reference_record,
        )
    return sink(duration=args.duration)


if __name__ == "__main__":
    raise SystemExit(main())
