"""KAN-20 cost side: what a feature set costs per window, measured on this machine.

`core.features.extract_features` computes all fourteen values in one function. To
price a subset, the same arithmetic is split here into the catalogue's four groups,
plus the pass every set pays (the EGRESS filter and `n`). A test pins that the split
reproduces the runtime extractor's values exactly.

**What the group timing is and is not.** It measures the group arithmetic only. The
runtime extractor also pays a per-window epoch-alignment check and a per-packet loop
validating `device_id` and the window bounds, and that work is constant across feature
sets, so it is outside the timed path here. Set-to-set ranking is therefore sound, but a
per-window extraction figure taken from the group timing is lower than the extractor's
own (R3 review, PR #35). `time_extractor` measures `extract_features` itself and is
reported beside the groups as the full-extractor reference.

Numbers from here are development-machine numbers. They rank sets against each
other; the gateway CPU, RAM and latency figures come from the KAN-42 harness on the
finalists only. Timing uses packets alone, never labels or scores.
"""

import io
import statistics
from collections import Counter
from collections.abc import Iterable, Sequence
from math import floor, sqrt
from pathlib import Path
from time import perf_counter_ns

from core.features import WINDOW_SECONDS, extract_features
from core.schema import Direction, PacketTuple
from model.ablation import FEATURE_GROUPS

_TCP, _UDP, _ICMP, _ICMPV6 = 6, 17, 1, 58
_SYN, _RST, _ACK = 0x02, 0x04, 0x10


def _volume(egress, n):
    lengths = [p.packet_length for p in egress]
    total = sum(lengths)
    mean = total / n
    return (n, total, mean, sqrt(sum((x - mean) ** 2 for x in lengths) / n))


def _destinations(egress, n):
    per_dst = Counter(p.dst_ip for p in egress)
    return (
        len(per_dst),
        len({p.dst_port for p in egress if p.dst_port is not None}),
        max(per_dst.values()) / n,
    )


def _protocol(egress, n):
    protocols = Counter(p.protocol for p in egress)
    return (
        protocols[_TCP] / n,
        protocols[_UDP] / n,
        (protocols[_ICMP] + protocols[_ICMPV6]) / n,
    )


def _connection(egress, n):
    tcp_flags = [p.tcp_flags for p in egress if p.protocol == _TCP]
    times = [p.timestamp for p in egress]
    return (
        sum(1 for f in tcp_flags if f & _SYN and not f & _ACK) / n,
        sum(1 for f in tcp_flags if f & _RST) / n,
        sum(1 for p in egress if p.dst_port is None) / n,
        max(times) - min(times),
    )


GROUP_FUNCTIONS = {
    "volume": _volume,
    "destinations": _destinations,
    "protocol": _protocol,
    "connection": _connection,
}


def groups_for(columns: Sequence[int]) -> tuple[str, ...]:
    """Every group that owns at least one requested column must run in full."""
    wanted = set(columns)
    return tuple(g for g, cols in FEATURE_GROUPS.items() if wanted & set(cols))


def extract_groups(packets: Sequence[PacketTuple], groups: Iterable[str]) -> dict[int, float]:
    """The requested groups' values by catalogue index, or {} for a window with no EGRESS."""
    egress = [p for p in packets if p.direction is Direction.EGRESS]
    if not egress:
        return {}
    n = len(egress)
    values = {}
    for group in groups:
        computed = GROUP_FUNCTIONS[group](egress, n)
        for column, value in zip(FEATURE_GROUPS[group], computed, strict=True):
            values[column] = float(value)
    return values


def packet_windows(packets: Iterable[PacketTuple], limit: int) -> list[list[PacketTuple]]:
    """The first `limit` per-device 5 s EGRESS windows of a packet stream, in order.

    Reading stops as soon as a window beyond `limit` opens, so a large capture is not
    read to the end for a timing sample. That newest window is the one dropped.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("limit must be a positive int")
    windows: dict[tuple[str, float], list[PacketTuple]] = {}
    for packet in packets:
        if packet.direction is not Direction.EGRESS:
            continue
        key = (packet.device_id, float(floor(packet.timestamp / WINDOW_SECONDS) * WINDOW_SECONDS))
        if key not in windows and len(windows) == limit:
            break
        windows.setdefault(key, []).append(packet)
    return [windows[key] for key in sorted(windows)]


def time_extraction(
    windows: Sequence[Sequence[PacketTuple]], columns: Sequence[int], *, repeats: int
) -> dict:
    """Median over `repeats` of the mean nanoseconds per window for this set's groups."""
    if not windows:
        raise ValueError("no windows to time")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive int")
    groups = groups_for(columns)
    runs = []
    for _ in range(repeats):
        started = perf_counter_ns()
        for window in windows:
            extract_groups(window, groups)
        runs.append((perf_counter_ns() - started) / len(windows))
    return {
        "measures": "group arithmetic only; excludes the extractor's validation and packet loop",
        "groups": list(groups),
        "windows": len(windows),
        "repeats": repeats,
        "ns_per_window_median": round(statistics.median(runs), 1),
        "ns_per_window_min": round(min(runs), 1),
    }


def time_extractor(windows: Sequence[Sequence[PacketTuple]], *, repeats: int) -> dict:
    """Time `core.features.extract_features` itself: every group plus its validation.

    This is the number to compare against gateway measurements; the per-set group
    timings above are for ranking sets against each other.
    """
    if not windows:
        raise ValueError("no windows to time")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be a positive int")
    prepared = []
    for window in windows:
        device = window[0].device_id
        start = float(floor(window[0].timestamp / WINDOW_SECONDS) * WINDOW_SECONDS)
        prepared.append((device, start, window))
    runs = []
    for _ in range(repeats):
        started = perf_counter_ns()
        for device, start, window in prepared:
            extract_features(device, start, window)
        runs.append((perf_counter_ns() - started) / len(prepared))
    return {
        "measures": "core.features.extract_features, the work the runtime pays per window",
        "windows": len(prepared),
        "repeats": repeats,
        "ns_per_window_median": round(statistics.median(runs), 1),
        "ns_per_window_min": round(min(runs), 1),
    }


def time_inference(model, rows: Sequence[Sequence[float]]) -> dict:
    """Single-window `predict_proba` latency, the way the live detector calls it."""
    if not rows:
        raise ValueError("no rows to time")
    samples = []
    for row in rows:
        started = perf_counter_ns()
        model.predict_proba([list(row)])
        samples.append(perf_counter_ns() - started)
    samples.sort()
    return {
        "rows": len(samples),
        "us_median": round(statistics.median(samples) / 1000, 1),
        "us_p95": round(samples[min(len(samples) - 1, int(0.95 * len(samples)))] / 1000, 1),
    }


def model_size(model) -> dict:
    """Tree nodes and serialized bytes: the memory side of a feature set."""
    import joblib

    buffer = io.BytesIO()
    joblib.dump(model, buffer)
    return {
        "tree_nodes": int(sum(t.tree_.node_count for t in model.estimators_)),
        "joblib_bytes": buffer.getbuffer().nbytes,
    }


def capture_windows(pcap: Path, lan_cidrs, devices, limit: int) -> list[list[PacketTuple]]:
    """Timing sample from one capture, normalized exactly as the pack builder does."""
    from sources.from_pcap import read_pcap
    from sources.packets import PacketNormalizer

    normalizer = PacketNormalizer(list(lan_cidrs), dict(devices))
    return packet_windows(read_pcap(pcap, normalizer), limit)
