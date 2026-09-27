"""KAN-13 capture audit: endpoint and direction summary of a classic PCAP.

Audit evidence only. It assigns no labels, emits no PacketTuples and, unlike the
R2 source adapter, keeps outside-LAN traffic so the capture point can be judged.
"""

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from ipaddress import ip_address, ip_network
from pathlib import Path

import dpkt


@dataclass(frozen=True)
class CaptureSummary:
    packets: int
    ip_packets: int
    first_ts: float | None
    last_ts: float | None
    protocols: dict[int, int]
    direction_counts: dict[str, int]
    top_pairs: list[tuple[str, str, int]]


def _direction(src, dst, lans) -> str:
    src_in = any(src in lan for lan in lans)
    dst_in = any(dst in lan for lan in lans)
    return {(True, False): "EGRESS", (False, True): "INGRESS", (True, True): "LOCAL"}.get(
        (src_in, dst_in), "OUTSIDE"
    )


def pcap_record_count(path: Path) -> int:
    """Count classic-PCAP records by walking record headers only, without reading frames.

    Used to tell a malformed *final* record, which is how a capture cut at its last packet
    looks, from a malformed record in the middle of a file. A trailing partial header is
    not a record and is not counted.
    """
    import struct

    with open(path, "rb") as stream:
        header = stream.read(24)
        if len(header) < 24:
            return 0
        magic = header[:4]
        if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
            endian = "<"
        elif magic in (b"\xa1\xb2\xc3\xd4", b"\xa1\xb2\x3c\x4d"):
            endian = ">"
        else:
            raise ValueError(f"{Path(path).name}: not a classic PCAP")
        count = 0
        while True:
            record = stream.read(16)
            if len(record) < 16:
                return count
            (caplen,) = struct.unpack(endian + "I", record[8:12])
            stream.seek(caplen, 1)
            count += 1


def summarize_pcap(path: Path, lan_cidrs: Sequence[str], top: int = 20) -> CaptureSummary:
    lans = [ip_network(cidr) for cidr in lan_cidrs]
    packets = ip_packets = 0
    first = last = None
    protocols: Counter[int] = Counter()
    directions: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    with open(path, "rb") as stream:
        try:
            reader = dpkt.pcap.Reader(stream)
        except ValueError as exc:
            raise ValueError(f"{Path(path).name}: not a classic PCAP ({exc})") from exc
        for ts, frame in reader:
            packets += 1
            first = ts if first is None else first
            last = ts
            try:
                ip = dpkt.ethernet.Ethernet(frame).data
            except dpkt.NeedData:
                # Only the final record may be short: a capture cut at its last packet.
                # Anywhere else a short frame is corruption and must not be skipped.
                if packets == pcap_record_count(path):
                    break
                raise
            if not isinstance(ip, dpkt.ip.IP | dpkt.ip6.IP6):
                continue
            ip_packets += 1
            src, dst = ip_address(ip.src), ip_address(ip.dst)
            protocols[ip.p if isinstance(ip, dpkt.ip.IP) else ip.nxt] += 1
            directions[_direction(src, dst, lans)] += 1
            pairs[(str(src), str(dst))] += 1
    return CaptureSummary(
        packets,
        ip_packets,
        first,
        last,
        dict(protocols),
        dict(directions),
        [(src, dst, count) for (src, dst), count in pairs.most_common(top)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--lan", action="append", required=True, help="candidate LAN CIDR")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(asdict(summarize_pcap(args.pcap, args.lan, args.top)), indent=2))


if __name__ == "__main__":
    main()
