"""Prepare a fixed IoT-23 8-1 SYN slice for isolated G8 integration replay.

This is a traffic transformation, not a new label or model evaluation. The
parent capture is hash-pinned and the exact selected record indices are logged.
Only SYN packets without payload from the captured infected device are copied;
their private source/destination addresses are mapped to the owned A/C lab.
"""

import argparse
import hashlib
import json
import socket
from collections import Counter
from pathlib import Path

import dpkt

PARENT_SHA256 = "80dcc2602519479ddcde889fa902fee19a76696630811452f8df38888af894f2"
SOURCE = socket.inet_aton("192.168.100.113")
LAB_SOURCE = socket.inet_aton("10.203.1.2")
LAB_SINK = socket.inet_aton("10.203.2.2")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(parent: Path, out: Path, *, max_span_seconds: float = 6.0) -> dict:
    if digest(parent) != PARENT_SHA256:
        raise ValueError("parent capture does not match audited IoT-23 8-1 SHA-256")
    if max_span_seconds <= 0 or max_span_seconds > 60:
        raise ValueError("max_span_seconds must be in (0, 60]")
    out.mkdir(parents=True, exist_ok=False)
    counts: Counter[str] = Counter()
    selected = []
    first = None
    last = None
    target = out / "prepared.pcap"
    with parent.open("rb") as source, target.open("wb") as destination:
        reader = dpkt.pcap.Reader(source)
        if reader.datalink() != dpkt.pcap.DLT_EN10MB:
            raise ValueError("parent capture must be Ethernet")
        writer = dpkt.pcap.Writer(destination)
        for index, (timestamp, frame) in enumerate(reader, 1):
            counts["records_read"] += 1
            try:
                eth = dpkt.ethernet.Ethernet(frame)
                ip = eth.data
            except dpkt.UnpackError, ValueError:
                counts["malformed_or_unsupported"] += 1
                continue
            if not isinstance(ip, dpkt.ip.IP) or ip.src != SOURCE:
                counts["not_device_ipv4"] += 1
                continue
            if (
                frame[12:14] != b"\x08\x00"
                or ip.hl != 5
                or int.from_bytes(frame[20:22], "big") & 0x3FFF
                or not isinstance(ip.data, dpkt.tcp.TCP)
            ):
                counts["not_plain_tcp"] += 1
                continue
            tcp = ip.data
            if tcp.dport != 50 or tcp.flags != dpkt.tcp.TH_SYN or tcp.data:
                counts["not_selected_syn"] += 1
                continue
            if first is None:
                first = timestamp
            if timestamp - first > max_span_seconds:
                counts["after_selected_span"] += 1
                continue
            original_destination = socket.inet_ntoa(ip.dst)
            ip.src, ip.dst = LAB_SOURCE, LAB_SINK
            ip.sum, tcp.sum = 0, 0
            eth.data = ip
            prepared = bytes(eth)
            if len(prepared) != 14 + ip.len or dpkt.in_cksum(prepared[14:34]):
                raise ValueError(f"prepared record {index} has invalid length/checksum")
            writer.writepkt(prepared, ts=timestamp)
            selected.append(
                {
                    "parent_record": index,
                    "capture_ts": timestamp,
                    "original_dst_ip": original_destination,
                    "original_dst_port": tcp.dport,
                }
            )
            last = timestamp
            counts["selected"] += 1
        writer.close()
    if len(selected) < 2:
        raise ValueError("fewer than two eligible SYN packets in declared span")
    manifest = {
        "source": "IoT-23 CTU-IoT-Malware-Capture-8-1; integration slice, not holdout",
        "parent_pcap_sha256": PARENT_SHA256,
        "prepared_pcap_sha256": digest(target),
        "selection": "IPv4 TCP SYN/no payload, captured device 192.168.100.113, dport 50",
        "max_span_seconds": max_span_seconds,
        "transformations": [
            "drop all records outside selection, counting exclusions",
            "map captured source 192.168.100.113 to owned og-a 10.203.1.2",
            "map selected destination to owned og-c 10.203.2.2",
            "recompute IPv4 and TCP checksums; replay harness replaces Ethernet MACs",
        ],
        "counts": dict(counts),
        "selected_records": selected,
        "first_capture_ts": first,
        "last_capture_ts": last,
        "label_limit": "scenario is malware capture; no per-record attack-start claim",
    }
    (out / "provenance.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-span-seconds", type=float, default=6.0)
    args = parser.parse_args()
    report = prepare(args.parent, args.out, max_span_seconds=args.max_span_seconds)
    print(
        json.dumps(
            {
                "prepared_pcap_sha256": report["prepared_pcap_sha256"],
                "selected": report["counts"]["selected"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
