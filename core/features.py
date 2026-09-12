"""KAN-15/16 feature catalogue v1 and the one pure extractor used offline and live.

See data/FEATURE_CATALOG.md. No I/O, clock or state. device_id travels in the
envelope and is never a feature value.
"""

from collections import Counter
from collections.abc import Sequence
from math import sqrt

from core.schema import Direction, FeatureVector, PacketTuple

FEATURE_SCHEMA_VERSION = "features-1"
WINDOW_SECONDS = 5
FEATURE_ORDER = (
    "pkt_count",
    "l3_bytes_sum",
    "l3_bytes_mean",
    "l3_bytes_std",
    "uniq_dst_ip",
    "uniq_dst_port",
    "max_dst_ip_share",
    "tcp_share",
    "udp_share",
    "icmp_share",
    "syn_only_share",
    "rst_share",
    "portless_share",
    "active_span_s",
)

_TCP, _UDP, _ICMP, _ICMPV6 = 6, 17, 1, 58
_SYN, _RST, _ACK = 0x02, 0x04, 0x10


class FeatureError(ValueError):
    """The window cannot be described; callers must not substitute a benign vector."""


def extract_features(
    device_id: str, window_start: float, packets: Sequence[PacketTuple]
) -> FeatureVector | None:
    """Describe one device's EGRESS traffic in one window, or None if it sent nothing."""
    if window_start % WINDOW_SECONDS:
        raise FeatureError("window_start must be epoch-aligned to 5 s")
    window_end = window_start + WINDOW_SECONDS
    for packet in packets:
        if packet.device_id != device_id:
            raise FeatureError("packet belongs to another device")
        if not window_start <= packet.timestamp < window_end:
            raise FeatureError("packet outside [window_start, window_end)")
    egress = [p for p in packets if p.direction is Direction.EGRESS]
    if not egress:
        return None

    n = len(egress)
    lengths = [p.packet_length for p in egress]
    total = sum(lengths)
    mean = total / n
    per_dst = Counter(p.dst_ip for p in egress)
    protocols = Counter(p.protocol for p in egress)
    tcp_flags = [p.tcp_flags for p in egress if p.protocol == _TCP]
    times = [p.timestamp for p in egress]

    values = (
        n,
        total,
        mean,
        sqrt(sum((x - mean) ** 2 for x in lengths) / n),
        len(per_dst),
        len({p.dst_port for p in egress if p.dst_port is not None}),
        max(per_dst.values()) / n,
        protocols[_TCP] / n,
        protocols[_UDP] / n,
        (protocols[_ICMP] + protocols[_ICMPV6]) / n,
        sum(1 for f in tcp_flags if f & _SYN and not f & _ACK) / n,
        sum(1 for f in tcp_flags if f & _RST) / n,
        sum(1 for p in egress if p.dst_port is None) / n,
        max(times) - min(times),
    )
    return FeatureVector(
        device_id,
        window_start,
        window_end,
        FEATURE_SCHEMA_VERSION,
        FEATURE_ORDER,
        tuple(float(v) for v in values),
    )
