"""Dedicated disposable-container capture oracle; synthetic benign UDP only."""

import argparse
import json
import math
import socket
import subprocess
import sys
import time
from pathlib import Path

from gateway.pipeline import WindowFeaturePipeline
from sources.live import CaptureError, LiveCapture
from sources.packets import PacketNormalizer

PORT = 39027
SOURCE_PORT = 39028
PAYLOAD = b"OG-LIVE-ORACLE".ljust(32, b".")


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True, timeout=30).stdout


def ready(path, process):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"worker exited before ready: {path.read_text()}")
        if '"ready": true' in path.read_text():
            return
        time.sleep(0.02)
    raise TimeoutError(f"worker readiness timeout: {path}")


def source(count, paced):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("10.203.1.2", SOURCE_PORT))
        for _ in range(count):
            sock.sendto(PAYLOAD, ("10.203.2.2", PORT))
            if paced:
                time.sleep(0.003)
    print(json.dumps({"sent": count}))


def window_source(start):
    if start is None:
        raise ValueError("window source requires --start")
    while time.time() < start + 0.2:
        time.sleep(0.01)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("10.203.1.2", SOURCE_PORT))
        for _ in range(3):
            sock.sendto(PAYLOAD, ("10.203.2.2", PORT))
        while time.time() < start + 5.2:
            time.sleep(0.01)
        sock.sendto(PAYLOAD, ("10.203.2.2", PORT))
    print(json.dumps({"sent": 4, "window_start": start}))


def sink():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind(("10.203.2.2", PORT))
        sock.settimeout(0.1)
        print(json.dumps({"ready": True}), file=sys.stderr, flush=True)
        deadline = time.monotonic() + 3
        count = 0
        while time.monotonic() < deadline:
            try:
                data, _ = sock.recvfrom(65536)
            except TimeoutError:
                continue
            if data != PAYLOAD:
                raise RuntimeError("unexpected oracle payload")
            count += 1
    print(json.dumps({"received": count}))


def overflow():
    normalizer = PacketNormalizer(["10.203.1.0/24"], {"10.203.1.2": "camera"})
    capture = LiveCapture("og-b0", normalizer, receive_bytes=4096)
    print(json.dumps({"ready": True}), file=sys.stderr, flush=True)
    time.sleep(1)  # Deliberately starve this socket while the isolated sender floods it.
    try:
        capture.read()
    except CaptureError:
        if capture.stats.kernel_drops <= 0:
            raise
        print(json.dumps({"detected_drops": capture.stats.kernel_drops}))
    else:
        raise RuntimeError("expected socket overflow was not detected")
    finally:
        capture.close(check_loss=False)


def window_capture():
    normalizer = PacketNormalizer(["10.203.1.0/24"], {"10.203.1.2": "camera"})
    start = math.floor(time.time() / 5) * 5 + 5
    pipeline = WindowFeaturePipeline(start)
    with LiveCapture("og-b0", normalizer) as capture:
        print(json.dumps({"ready": True, "window_start": start}), file=sys.stderr, flush=True)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            vectors = pipeline.capture_once(capture)
            if vectors:
                vector = vectors[0]
                print(
                    json.dumps(
                        {
                            "device_id": vector.device_id,
                            "window_start": vector.window_start,
                            "window_end": vector.window_end,
                            "feature_order": vector.feature_order,
                            "values": vector.values,
                            "kernel_drops": capture.stats.kernel_drops,
                        }
                    )
                )
                return
    raise RuntimeError("window capture produced no complete feature vector")


def orchestrate():
    root = Path("/tmp/live-validation")
    root.mkdir()
    devices = root / "devices.json"
    devices.write_text('{"10.203.1.2":"camera"}')
    script = str(Path(__file__).resolve())
    processes = []
    run("bash", "lab/setup_netns.sh")
    try:
        run("ip", "netns", "exec", "og-a", "ping", "-c", "1", "-W", "1", "10.203.2.2")
        source_mac = json.loads(run("ip", "-n", "og-a", "-j", "link", "show", "og-a0"))[0][
            "address"
        ]
        summary = {}
        with (root / "window.json").open("w") as out, (root / "window.err").open("w") as err:
            capture = subprocess.Popen(
                ["ip", "netns", "exec", "og-b", sys.executable, script, "window-capture"],
                stdout=out,
                stderr=err,
            )
            processes.append(capture)
            ready(root / "window.err", capture)
            start = json.loads((root / "window.err").read_text().splitlines()[0])["window_start"]
            sent = json.loads(
                run(
                    "ip",
                    "netns",
                    "exec",
                    "og-a",
                    sys.executable,
                    script,
                    "window-source",
                    "--start",
                    str(start),
                )
            )
            if capture.wait(timeout=15):
                raise RuntimeError("live window pipeline failed")
        vector = json.loads((root / "window.json").read_text())
        values = dict(zip(vector["feature_order"], vector["values"], strict=True))
        if sent["sent"] != 4 or values["pkt_count"] != 3 or values["l3_bytes_sum"] != 180:
            raise RuntimeError("live window feature values differ from packet oracle")
        if (vector["window_start"], vector["window_end"], vector["kernel_drops"]) != (
            start,
            start + 5,
            0,
        ):
            raise RuntimeError("live window metadata or capture health mismatch")
        summary["window_pipeline"] = {
            "sent": 4,
            "first_window_packets": 3,
            "feature_packet_count": values["pkt_count"],
            "feature_l3_bytes": values["l3_bytes_sum"],
            "kernel_drops": vector["kernel_drops"],
        }
        for phase in ("baseline", "blocked", "released"):
            run("bash", "lab/quarantine.sh", "apply" if phase == "blocked" else "release")
            with (
                (root / f"{phase}.jsonl").open("w") as out,
                (root / f"{phase}.err").open("w") as err,
                (root / f"{phase}-sink.json").open("w") as sink_out,
                (root / f"{phase}-sink.err").open("w") as sink_err,
            ):
                receiver = subprocess.Popen(
                    ["ip", "netns", "exec", "og-c", sys.executable, script, "sink"],
                    stdout=sink_out,
                    stderr=sink_err,
                )
                processes.append(receiver)
                capture = subprocess.Popen(
                    [
                        "ip",
                        "netns",
                        "exec",
                        "og-b",
                        sys.executable,
                        "-m",
                        "sources.live",
                        "--interface",
                        "og-b0",
                        "--lan",
                        "10.203.1.0/24",
                        "--devices",
                        str(devices),
                        "--duration",
                        "2",
                    ],
                    stdout=out,
                    stderr=err,
                )
                processes.append(capture)
                ready(root / f"{phase}-sink.err", receiver)
                ready(root / f"{phase}.err", capture)
                sent = json.loads(
                    run("ip", "netns", "exec", "og-a", sys.executable, script, "source")
                )
                if capture.wait(timeout=8) or receiver.wait(timeout=8):
                    raise RuntimeError(f"capture/sink failed in {phase}")
            rows = [json.loads(line) for line in (root / f"{phase}.jsonl").read_text().splitlines()]
            packets = [
                row for row in rows if row["src_port"] == SOURCE_PORT and row["dst_port"] == PORT
            ]
            stats = json.loads((root / f"{phase}.err").read_text().splitlines()[-1])
            received = json.loads((root / f"{phase}-sink.json").read_text())["received"]
            if sent["sent"] != 100 or len(packets) != 100:
                raise RuntimeError(f"source/capture count mismatch in {phase}")
            if received != (0 if phase == "blocked" else 100):
                raise RuntimeError(f"unexpected sink count in {phase}: {received}")
            if stats["capture"]["kernel_drops"]:
                raise RuntimeError("unexpected socket drops")
            for row in packets:
                if (row["packet_length"], row["direction"], row["device_id"], row["src_mac"]) != (
                    60,
                    "EGRESS",
                    "camera",
                    source_mac,
                ):
                    raise RuntimeError("live metadata differs from independent oracle")
            summary[phase] = {
                "sent": 100,
                "captured": len(packets),
                "sink": received,
                "socket_drops": stats["capture"]["kernel_drops"],
            }
        run("bash", "lab/quarantine.sh", "apply")
        with (root / "overflow.json").open("w") as out, (root / "overflow.err").open("w") as err:
            worker = subprocess.Popen(
                ["ip", "netns", "exec", "og-b", sys.executable, script, "overflow"],
                stdout=out,
                stderr=err,
            )
            processes.append(worker)
            ready(root / "overflow.err", worker)
            run("ip", "netns", "exec", "og-a", sys.executable, script, "flood")
            if worker.wait(timeout=8):
                raise RuntimeError("overflow detection failed")
        summary["overflow"] = json.loads((root / "overflow.json").read_text())
        (root / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        run("bash", "lab/teardown_netns.sh")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        choices=("run", "sink", "source", "flood", "overflow", "window-capture", "window-source"),
    )
    parser.add_argument("--start", type=float)
    args = parser.parse_args()
    mode = args.mode
    if mode == "run":
        orchestrate()
    elif mode == "sink":
        sink()
    elif mode == "overflow":
        overflow()
    elif mode == "window-capture":
        window_capture()
    elif mode == "window-source":
        window_source(args.start)
    else:
        source(100 if mode == "source" else 10000, mode == "source")
