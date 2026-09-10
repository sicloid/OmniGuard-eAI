"""Streaming classic-PCAP reader. No dataset labels, inference or packet replay."""

import argparse
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path

import dpkt

from core.schema import PacketTuple
from sources.packets import PacketError, PacketNormalizer, UnsupportedLinkType


def read_pcap(path: str | Path, normalizer: PacketNormalizer) -> Iterator[PacketTuple]:
    """Fail fast on malformed records; emit one canonical tuple per relevant IP packet.

    PCAPNG is explicitly rejected: mixed interfaces need per-record linktype support.
    Statistics are available on normalizer.stats even when parsing raises.
    """
    with open(path, "rb") as stream:
        if stream.read(4) == b"\x0a\x0d\x0d\x0a":
            raise ValueError("PCAPNG unsupported; convert to classic PCAP per interface")
        stream.seek(0)
        capture = dpkt.pcap.Reader(stream)
        linktype = capture.datalink()
        if linktype not in (1, 12, 101, 113, 276):
            raise UnsupportedLinkType(f"unsupported linktype {linktype}")
        for timestamp, frame in capture:
            packet = normalizer.parse(float(timestamp), frame, linktype)
            if packet is not None:
                yield packet


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--lan", action="append", required=True, help="LAN CIDR; repeatable")
    parser.add_argument("--devices", required=True, type=Path, help="JSON object: IP -> device_id")
    args = parser.parse_args()
    normalizer = None
    try:
        devices = json.loads(args.devices.read_text(encoding="utf-8"))
        normalizer = PacketNormalizer(args.lan, devices)
        for packet in read_pcap(args.capture, normalizer):
            print(json.dumps(asdict(packet), allow_nan=False))
    except (ValueError, OSError, dpkt.UnpackError, PacketError) as exc:
        parser.exit(2, f"capture rejected: {exc}\n")
    finally:
        if normalizer is not None:
            print(json.dumps({"statistics": asdict(normalizer.stats)}), file=sys.stderr)


if __name__ == "__main__":
    main()
