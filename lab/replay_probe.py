"""Dedicated-container oracle for prepared PCAP replay and persistent run evidence."""

import json
import struct
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import dpkt

from lab.live_probe import PAYLOAD, PORT, SOURCE_PORT, ready, run


def make_capture(path):
    udp = struct.pack("!HHHH", SOURCE_PORT, PORT, 8 + len(PAYLOAD), 0) + PAYLOAD
    header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        0,
        20 + len(udp),
        0,
        0,
        64,
        17,
        0,
        bytes((10, 203, 1, 2)),
        bytes((10, 203, 2, 2)),
    )
    header = header[:10] + struct.pack("!H", dpkt.in_cksum(header)) + header[12:]
    frame = bytes.fromhex("0200000000020200000000010800") + header + udp
    with path.open("wb") as stream:
        writer = dpkt.pcap.Writer(stream, nano=True)
        for index in range(100):
            writer.writepkt(frame, ts=Decimal("1700000000") + Decimal(index) / 100)


def main():
    root = Path("/tmp/replay-validation")
    root.mkdir()
    capture = root / "oracle.pcap"
    make_capture(capture)
    provenance = root / "provenance.json"
    provenance.write_text(
        json.dumps(
            {
                "source": "synthetic benign UDP oracle",
                "transformations": ["generated directly in isolated lab addressing"],
            }
        )
    )
    devices = root / "devices.json"
    devices.write_text('{"10.203.1.2":"camera"}')
    arguments = [
        sys.executable,
        "-m",
        "lab.replay",
        str(capture),
        "--provenance",
        str(provenance),
        "--output",
        str(root / "runs"),
        "--reference-record",
        "21",
        "--speed",
        "2",
    ]
    run("bash", "lab/setup_netns.sh")
    workers = []
    summary = []
    try:
        # Real wrong-namespace negative: container parent must never open a sender.
        refused = subprocess.run(arguments, capture_output=True, text=True, timeout=15)
        if refused.returncode != 2 or "host/gateway replay refused" not in refused.stderr:
            raise RuntimeError("parent namespace was not rejected")
        (root / "host-refusal.txt").write_text(refused.stderr)
        for repetition in range(2):
            prefix = root / f"repeat-{repetition}"
            with (
                Path(str(prefix) + ".jsonl").open("w") as out,
                Path(str(prefix) + ".err").open("w") as err,
                Path(str(prefix) + "-sink.json").open("w") as sink_out,
                Path(str(prefix) + "-sink.err").open("w") as sink_err,
            ):
                sink = subprocess.Popen(
                    ["ip", "netns", "exec", "og-c", sys.executable, "-m", "lab.live_probe", "sink"],
                    stdout=sink_out,
                    stderr=sink_err,
                )
                observer = subprocess.Popen(
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
                workers.extend((sink, observer))
                ready(Path(str(prefix) + "-sink.err"), sink)
                ready(Path(str(prefix) + ".err"), observer)
                replay_output = json.loads(run("ip", "netns", "exec", "og-a", *arguments))
                if sink.wait(timeout=8) or observer.wait(timeout=8):
                    raise RuntimeError("sink/observer failure")
            manifest = json.loads(Path(replay_output["manifest"]).read_text())
            rows = [
                json.loads(line) for line in Path(str(prefix) + ".jsonl").read_text().splitlines()
            ]
            count = sum(row["src_port"] == SOURCE_PORT and row["dst_port"] == PORT for row in rows)
            received = json.loads(Path(str(prefix) + "-sink.json").read_text())["received"]
            events = [
                json.loads(line)
                for line in (Path(replay_output["manifest"]).parent / "events.jsonl")
                .read_text()
                .splitlines()
            ]
            returns = [event for event in events if event["type"] == "send_return"]
            if (manifest["status"], manifest["sent_packets"], count, received) != (
                "complete",
                100,
                100,
                100,
            ):
                raise RuntimeError("replay/capture/sink mismatch")
            if len(returns) != 100 or manifest["reference_t0"]["record"] != 21:
                raise RuntimeError("missing timing evidence")
            duration = returns[-1]["scheduled_ns"] - returns[0]["scheduled_ns"]
            if duration != 495_000_000 or not all(
                e["scheduled_ns"] <= e["send_begin_ns"] <= e["send_return_ns"] for e in returns
            ):
                raise RuntimeError("incorrect speed mapping or send ordering")
            summary.append(
                {
                    "run_id": manifest["run_id"],
                    "sha256": manifest["prepared_pcap_sha256"],
                    "sent": 100,
                    "capture": count,
                    "sink": received,
                    "scheduled_duration_ns": duration,
                    "max_schedule_lag_ns": manifest["max_schedule_lag_ns"],
                    "reference_t0": manifest["reference_t0"],
                }
            )
        if (
            summary[0]["run_id"] == summary[1]["run_id"]
            or summary[0]["sha256"] != summary[1]["sha256"]
        ):
            raise RuntimeError("run identity/hash mismatch")
        (root / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.kill()
                worker.wait()
        run("bash", "lab/teardown_netns.sh")


if __name__ == "__main__":
    main()
