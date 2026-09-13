"""KAN-14 flow-label index built from a Zeek `conn.log.labeled` file.

IoT-23 packs the last three columns (`tunnel_parents`, `label`, `detailed-label`)
into a single tab field separated by spaces, in the header and in every row, so
they are expanded before use rather than assumed to be tab-delimited.

Labels are per connection, not per packet, so a packet is labelled by locating the
flow it belongs to. Matching is direction-insensitive on the 5-tuple and bounded by
the flow's own time window plus a tolerance. A packet that matches nothing, or
matches flows that disagree, is **unknown** — never benign. Unknown counts are kept
so the sample pack can report them instead of hiding them in the benign class.
"""

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from core.schema import PacketTuple

BENIGN = "Benign"
MALICIOUS = "Malicious"
DEFAULT_TOLERANCE = 1.0
REQUIRED_FIELDS = (
    "ts",
    "id.orig_h",
    "id.orig_p",
    "id.resp_h",
    "id.resp_p",
    "proto",
    "duration",
    "label",
)
PROTOCOL_NUMBERS = {"tcp": 6, "udp": 17, "icmp": 1, "icmp6": 58, "ipv6-icmp": 58}


class LabelError(ValueError):
    """The label file cannot be trusted, so no labelling is attempted."""


def _expand(parts: list[str], expected: int | None = None) -> list[str]:
    """IoT-23 packs the trailing label columns into one tab field, space separated."""
    if not parts:
        return parts
    extra = 0 if expected is None else expected - len(parts)
    if expected is not None and extra <= 0:
        return parts
    tail = parts[-1].split(None, 2 if expected is None else extra)
    return parts[:-1] + tail if len(tail) > 1 else parts


def _canonical(label: str) -> str:
    """IoT-23 writes `benign` in honeypot logs and `Benign` in malware logs."""
    folded = label.strip().lower()
    if folded == BENIGN.lower():
        return BENIGN
    if folded == MALICIOUS.lower():
        return MALICIOUS
    return label.strip()


def _key(protocol: int, a_ip: str, a_port: int, b_ip: str, b_port: int) -> tuple:
    return (protocol, *sorted(((a_ip, a_port), (b_ip, b_port))))


@dataclass(frozen=True)
class Flow:
    start: float
    end: float
    label: str


class FlowIndex:
    """Flows grouped by direction-insensitive key, with match/miss counters."""

    def __init__(self, flows: dict[tuple, list[Flow]], labels: dict[str, int], tolerance: float):
        self._flows = flows
        self.flow_labels = labels
        self.flows = sum(len(v) for v in flows.values())
        self.tolerance = tolerance
        self.matched = 0
        self.unmatched = 0
        self.ambiguous = 0

    def label_of(self, packet: PacketTuple) -> str | None:
        """Return Benign/Malicious, or None when the packet is unknown."""
        if packet.src_port is None or packet.dst_port is None:
            self.unmatched += 1
            return None
        key = _key(packet.protocol, packet.src_ip, packet.src_port, packet.dst_ip, packet.dst_port)
        found = {
            flow.label
            for flow in self._flows.get(key, ())
            if flow.start - self.tolerance <= packet.timestamp <= flow.end + self.tolerance
        }
        if not found:
            self.unmatched += 1
            return None
        if len(found) > 1:
            self.ambiguous += 1
            return None
        self.matched += 1
        return found.pop()

    @property
    def has_usable_labels(self) -> bool:
        return bool({BENIGN, MALICIOUS} & set(self.flow_labels))

    def counters(self) -> dict[str, int]:
        return {
            "flows": self.flows,
            "matched_packets": self.matched,
            "unmatched_packets": self.unmatched,
            "ambiguous_packets": self.ambiguous,
        }


def load_conn_log(path: Path, tolerance: float = DEFAULT_TOLERANCE) -> FlowIndex:
    fields: list[str] | None = None
    flows: dict[tuple, list[Flow]] = {}
    labels: dict[str, int] = {}
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("#fields"):
            fields = _expand(line.split("\t")[1:])
            missing = [name for name in REQUIRED_FIELDS if name not in fields]
            if missing:
                raise LabelError(f"{path.name}: missing fields {', '.join(missing)}")
            continue
        if line.startswith("#") or not line.strip():
            continue
        if fields is None:
            raise LabelError(f"{path.name}: data before the #fields header")
        values = _expand(line.split("\t"), len(fields))
        if len(values) != len(fields):
            raise LabelError(f"{path.name}: row has {len(values)} of {len(fields)} columns")
        record = dict(zip(fields, values, strict=True))
        protocol = PROTOCOL_NUMBERS.get(record["proto"])
        if protocol is None:
            continue
        try:
            start = float(record["ts"])
            duration = float(record["duration"]) if record["duration"] not in ("-", "") else 0.0
            ports = (int(record["id.orig_p"]), int(record["id.resp_p"]))
        except ValueError as exc:
            raise LabelError(f"{path.name}: unreadable numeric field ({exc})") from exc
        if not isfinite(start) or not isfinite(duration) or duration < 0:
            raise LabelError(f"{path.name}: nonfinite or negative timing")
        label = _canonical(record["label"])
        key = _key(protocol, record["id.orig_h"], ports[0], record["id.resp_h"], ports[1])
        flows.setdefault(key, []).append(Flow(start, start + duration, label))
        labels[label] = labels.get(label, 0) + 1
    if fields is None:
        raise LabelError(f"{path.name}: no #fields header")
    return FlowIndex(flows, labels, tolerance)
