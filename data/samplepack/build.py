"""KAN-14 sample-pack builder: captures plus flow labels into labelled windows.

One capture is one group: windows of a capture never split across train/test
(KAN-17). Labels come from the capture's own Zeek log; a window is malicious when
at least one of its outbound packets belongs to a Malicious flow, unknown when any
packet could not be matched confidently, and benign only when every packet matched
a Benign flow. Unknown windows are written with their label and excluded from
training data, never folded into benign.

A capture that ends mid-record is used up to that point, with the interval that was
still being recorded dropped rather than padded; the manifest records both facts.

Destinations that stay on the local link (multicast, the limited broadcast, link-local
and unspecified) are not EGRESS: that traffic never leaves the house, so counting it
as outbound would teach the model discovery chatter. The rule lives in `sources.scope`
and `PacketNormalizer` applies it, so this builder and live capture see the same EGRESS
set. The manifest's `multicast_or_broadcast` count is the normalizer's `on_link` count.
The Lead approved moving this rule into shared code on 14 September 2026; the
normalizer change still needs R2 review. The declared-label assumption and the IoT-23
primary source stay as recorded in ADR-0004.
"""

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from math import floor
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION, WINDOW_SECONDS, extract_features
from core.schema import Direction, FeatureVector, PacketTuple
from data.samplepack.labels import BENIGN, DEFAULT_TOLERANCE, MALICIOUS, load_conn_log
from model.train import LabelledWindow
from sources.from_pcap import read_pcap
from sources.packets import PacketNormalizer
from sources.scope import ON_LINK_DESTINATIONS

WINDOWS_FILENAME = "windows.jsonl"
MANIFEST_FILENAME = "manifest.json"
EGRESS_EXCLUSIONS = ON_LINK_DESTINATIONS
MALICIOUS_LABEL, BENIGN_LABEL, UNKNOWN_LABEL = "malicious", "benign", "unknown"
LABELS = (MALICIOUS_LABEL, BENIGN_LABEL, UNKNOWN_LABEL)
# sources.from_pcap reports a short read as a plain ValueError with this message. Only
# that error is a truncated tail; PCAPNG, link-type, size-bound and packet errors must
# fail the build instead of producing a nominally successful pack.
TRUNCATED_RECORD = "truncated PCAP header/record"


class SamplePackError(ValueError):
    """The capture specification cannot produce a trustworthy pack."""


@dataclass(frozen=True)
class CaptureSpec:
    group_id: str
    pcap: Path
    lan_cidrs: tuple[str, ...]
    devices: dict[str, str]
    source_url: str
    license: str
    conn_log: Path | None = None
    declared_label: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.group_id.strip():
            raise SamplePackError("group_id must be nonempty text")
        if self.conn_log is None and self.declared_label is None:
            raise SamplePackError(f"{self.group_id}: needs a conn log or an explicit label")
        if self.declared_label not in (None, BENIGN_LABEL, MALICIOUS_LABEL):
            raise SamplePackError(f"{self.group_id}: declared_label must be benign or malicious")


@dataclass
class _Counts:
    packets: int = 0
    egress_packets: int = 0
    multicast_or_broadcast: int = 0
    windows: dict[str, int] = field(
        default_factory=lambda: {MALICIOUS_LABEL: 0, BENIGN_LABEL: 0, UNKNOWN_LABEL: 0}
    )
    windows_without_egress: int = 0
    truncated_tail: bool = False
    dropped_truncated_tail: int = 0
    malicious_with_unmatched: int = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _windows_of(packets: Iterable[PacketTuple], counts: _Counts) -> dict[tuple[str, float], list]:
    grouped: dict[tuple[str, float], list[PacketTuple]] = {}
    stream = iter(packets)
    while True:
        try:
            packet = next(stream)
        except StopIteration:
            break
        except ValueError as exc:
            if str(exc) != TRUNCATED_RECORD:
                raise
            # A capture cut mid-record (IoT-23 5-1 ends this way). Keep what was read
            # and drop the interval that was still being recorded; never pad it.
            counts.truncated_tail = True
            break
        counts.packets += 1
        # On-link destinations already arrive as LOCAL from PacketNormalizer (sources.scope).
        if packet.direction is not Direction.EGRESS:
            continue
        counts.egress_packets += 1
        start = float(floor(packet.timestamp / WINDOW_SECONDS) * WINDOW_SECONDS)
        grouped.setdefault((packet.device_id, start), []).append(packet)
    if counts.truncated_tail:
        for device in {device for device, _ in grouped}:
            last = max(start for other, start in grouped if other == device)
            del grouped[(device, last)]
            counts.dropped_truncated_tail += 1
    return grouped


def _label_window(packets: Sequence[PacketTuple], index, declared: str | None, counts) -> str:
    """Malicious wins over unknown, so windows hiding unmatched packets are counted."""
    if declared is not None:
        return declared
    seen = {index.label_of(packet) for packet in packets}
    if MALICIOUS in seen:
        if None in seen:
            counts.malicious_with_unmatched += 1
        return MALICIOUS_LABEL
    if None in seen:
        return UNKNOWN_LABEL
    return BENIGN_LABEL if seen == {BENIGN} else UNKNOWN_LABEL


def build_sample_pack(
    specs: Sequence[CaptureSpec], out_dir: Path, *, tolerance: float = DEFAULT_TOLERANCE
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    captures: list[dict] = []

    for spec in specs:
        counts = _Counts()
        index = load_conn_log(spec.conn_log, tolerance) if spec.conn_log else None
        if index is not None and not index.has_usable_labels:
            raise SamplePackError(
                f"{spec.group_id}: {spec.conn_log.name} carries no Benign/Malicious labels; "
                "supply declared_label instead of letting every window become unknown"
            )
        normalizer = PacketNormalizer(list(spec.lan_cidrs), spec.devices)
        grouped = _windows_of(read_pcap(spec.pcap, normalizer), counts)
        counts.multicast_or_broadcast = normalizer.stats.on_link
        for (device_id, start), packets in sorted(grouped.items()):
            vector = extract_features(device_id, start, packets)
            if vector is None:
                counts.windows_without_egress += 1
                continue
            label = _label_window(packets, index, spec.declared_label, counts)
            counts.windows[label] += 1
            lines.append(
                json.dumps(
                    {
                        "group": spec.group_id,
                        "device_id": device_id,
                        "window_start": start,
                        "label": label,
                        "values": list(vector.values),
                    },
                    sort_keys=True,
                )
            )
        notes = spec.notes
        if spec.declared_label is not None:
            notes = (
                f"{notes} Label is an assumption from the dataset description "
                f"({spec.declared_label}), not measured from a flow log."
            ).strip()
        captures.append(
            {
                "group_id": spec.group_id,
                "source_url": spec.source_url,
                "license": spec.license,
                "pcap": spec.pcap.name,
                "pcap_sha256": _sha256(spec.pcap),
                "conn_log_sha256": _sha256(spec.conn_log) if spec.conn_log else None,
                "lan_cidrs": list(spec.lan_cidrs),
                "devices": dict(spec.devices),
                "label_source": "declared" if spec.declared_label else "flow-log",
                "notes": notes,
                "packets": {
                    "read": counts.packets,
                    "egress": counts.egress_packets,
                    "multicast_or_broadcast": counts.multicast_or_broadcast,
                    **(index.counters() if index else {}),
                },
                "windows": {
                    **counts.windows,
                    "without_egress": counts.windows_without_egress,
                    "dropped_truncated_tail": counts.dropped_truncated_tail,
                    "malicious_with_unmatched_packets": counts.malicious_with_unmatched,
                },
                "truncated_tail": counts.truncated_tail,
            }
        )

    payload = "".join(line + "\n" for line in lines)
    (out_dir / WINDOWS_FILENAME).write_text(payload, encoding="utf-8")
    manifest = {
        "tool": "data.samplepack.build",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "window_seconds": WINDOW_SECONDS,
        "flow_match_tolerance_s": tolerance,
        "egress_exclusions": list(EGRESS_EXCLUSIONS),
        "label_rule": (
            "malicious if any egress packet matches a Malicious flow; unknown if any "
            "packet is unmatched or ambiguous; benign only if every packet matched Benign"
        ),
        "captures": captures,
        "windows_file": WINDOWS_FILENAME,
        "windows_sha256": hashlib.sha256(payload.encode()).hexdigest(),
        "totals": {
            key: sum(c["windows"][key] for c in captures)
            for key in (MALICIOUS_LABEL, BENIGN_LABEL, UNKNOWN_LABEL)
        },
    }
    (out_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def read_windows(path: Path) -> list[LabelledWindow]:
    """Load training windows; unknown-labelled windows are left out on purpose.

    A label outside LABELS is an error, never a benign row: treating an unrecognised
    label as benign would put unverified windows into the benign class.
    """
    path = Path(path)
    windows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        row = json.loads(line)
        label = row["label"]
        if label not in LABELS:
            raise SamplePackError(f"{path.name}:{number}: label {label!r} is not one of {LABELS}")
        if label == UNKNOWN_LABEL:
            continue
        vector = FeatureVector(
            row["device_id"],
            row["window_start"],
            row["window_start"] + WINDOW_SECONDS,
            FEATURE_SCHEMA_VERSION,
            FEATURE_ORDER,
            tuple(float(v) for v in row["values"]),
        )
        windows.append(LabelledWindow(row["group"], vector, label == MALICIOUS_LABEL))
    return windows
