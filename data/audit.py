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
    distinct_lan_ips: int
    distinct_lan_source_macs: int
    lan_source_mac_ip_bindings: dict[str, list[str]]


def _direction(src, dst, lans) -> str:
    src_in = any(src in lan for lan in lans)
    dst_in = any(dst in lan for lan in lans)
    return {(True, False): "EGRESS", (False, True): "INGRESS", (True, True): "LOCAL"}.get(
        (src_in, dst_in), "OUTSIDE"
    )


def summarize_pcap(path: Path, lan_cidrs: Sequence[str], top: int = 20) -> CaptureSummary:
    lans = [ip_network(cidr) for cidr in lan_cidrs]
    packets = ip_packets = 0
    first = last = None
    protocols: Counter[int] = Counter()
    directions: Counter[str] = Counter()
    pairs: Counter[tuple[str, str]] = Counter()
    lan_ips: set[str] = set()
    lan_source_mac_ips: dict[str, set[str]] = {}
    with open(path, "rb") as stream:
        try:
            reader = dpkt.pcap.Reader(stream)
        except ValueError as exc:
            raise ValueError(f"{Path(path).name}: not a classic PCAP ({exc})") from exc
        for ts, frame in reader:
            packets += 1
            first = ts if first is None else first
            last = ts
            ethernet = dpkt.ethernet.Ethernet(frame)
            ip = ethernet.data
            if not isinstance(ip, dpkt.ip.IP | dpkt.ip6.IP6):
                continue
            ip_packets += 1
            src, dst = ip_address(ip.src), ip_address(ip.dst)
            if any(src in lan for lan in lans):
                src_text = str(src)
                lan_ips.add(src_text)
                source_mac = ethernet.src.hex(":")
                lan_source_mac_ips.setdefault(source_mac, set()).add(src_text)
            if any(dst in lan for lan in lans):
                lan_ips.add(str(dst))
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
        len(lan_ips),
        len(lan_source_mac_ips),
        {mac: sorted(ips) for mac, ips in sorted(lan_source_mac_ips.items())},
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
