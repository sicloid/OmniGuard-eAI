"""KAN-43: what the telemetry path costs in bytes, counted where the bytes are spent.

Four boundaries carry four *different* documents, so one number cannot stand for the
others and none of them is the network cost:

1. `payload_json` — the 0.1.0 `TelemetryPayload` on its own. It is never sent on its
   own; it is nested verbatim inside the envelope. Recorded so the schema's own size
   can be separated from what wrapping and transporting it adds.
2. `uds_frame` — the gateway to host boundary. The body there is the six-field
   StateEvent message of ADR-0003 §2.1, not the payload, plus the four byte length
   prefix. Counted as the bytes that actually crossed the socket.
3. `mqtt_application` — the envelope body plus its topic, as handed to the MQTT
   client. This is what the host offered to the transport; it is not proof that the
   bytes left the host, the same way a local queue is not a broker acknowledgement.
4. `mqtt_publish_packet` — the PUBLISH packet MQTT 3.1.1 would encode for that topic
   and body. **Derived from the protocol, not observed**, and marked so in the
   summary. The observed wire figure comes from `lab/mqtt_wire_counter.py`, which
   counts bytes on the connection itself.

Nothing here averages a missing observation in as zero: a boundary nobody recorded is
absent from the summary, and `missing()` names it. The counters that belong to other
components — publisher, spool, handoff, consumer — are not re-implemented here; this
module records bytes and leaves those counts to their owners.
"""

import json
from dataclasses import dataclass, field

from telemetry.canonical import canonical_bytes
from telemetry.framing import HEADER_SIZE
from telemetry.publisher import Acknowledgement, TransportError
from telemetry.uds import UnixSocketAdapter

PAYLOAD_JSON = "payload_json"
UDS_FRAME = "uds_frame"
MQTT_APPLICATION = "mqtt_application"
MQTT_PUBLISH_PACKET = "mqtt_publish_packet"

BOUNDARIES = (PAYLOAD_JSON, UDS_FRAME, MQTT_APPLICATION, MQTT_PUBLISH_PACKET)
#: Boundaries whose figure is computed from a contract rather than counted off a wire.
DERIVED = frozenset({MQTT_PUBLISH_PACKET})


class VolumeError(ValueError):
    """A byte figure that cannot describe traffic."""


@dataclass
class BoundaryVolume:
    """Bytes seen at one boundary, kept per observation rather than as an average."""

    boundary: str
    observations: int = 0
    bytes_total: int = 0
    bytes_min: int | None = None
    bytes_max: int | None = None

    def add(self, byte_count: int) -> None:
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise VolumeError(f"{self.boundary}: a byte count must be a non-negative integer")
        self.observations += 1
        self.bytes_total += byte_count
        self.bytes_min = byte_count if self.bytes_min is None else min(self.bytes_min, byte_count)
        self.bytes_max = byte_count if self.bytes_max is None else max(self.bytes_max, byte_count)

    def summary(self) -> dict:
        return {
            "observations": self.observations,
            "bytes_total": self.bytes_total,
            "bytes_min": self.bytes_min,
            "bytes_max": self.bytes_max,
            "bytes_mean": self.bytes_total / self.observations if self.observations else None,
            "derived": self.boundary in DERIVED,
        }


@dataclass
class VolumeLedger:
    """Byte totals for one run, bound to the run id the manifest was frozen under.

    The ledger records sizes only. Whether a publish was acknowledged, spooled or
    dropped is the publisher's counter, and it is carried here unchanged so a reader
    can divide bytes by the events that actually reached the broker rather than by
    the events this host hoped it had sent.
    """

    run_id: str
    boundaries: dict[str, BoundaryVolume] = field(default_factory=dict)
    acknowledged_events: int = 0
    offered_events: int = 0
    transport_failures: int = 0
    bodies_without_payload: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise VolumeError("run_id must be nonempty text")

    def record(self, boundary: str, byte_count: int) -> None:
        if boundary not in BOUNDARIES:
            raise VolumeError(f"unknown boundary {boundary!r}")
        self.boundaries.setdefault(boundary, BoundaryVolume(boundary)).add(byte_count)

    def record_payload(self, payload_document: dict) -> int:
        """Size the 0.1.0 document on its own, in the encoding the wire would use."""
        size = len(canonical_bytes(payload_document))
        self.record(PAYLOAD_JSON, size)
        return size

    def record_uds_frame(self, body: bytes) -> int:
        """One framed message on the gateway-to-host socket, length prefix included."""
        if not isinstance(body, bytes | bytearray):
            raise VolumeError("a UDS frame body must be bytes")
        size = HEADER_SIZE + len(body)
        self.record(UDS_FRAME, size)
        return size

    def missing(self) -> tuple[str, ...]:
        """Boundaries with no observation. Absent is not zero and is named as such."""
        return tuple(name for name in BOUNDARIES if name not in self.boundaries)

    def summary(self) -> dict:
        """A plain dict for the experiment manifest's `measurements`."""
        return {
            "run_id": self.run_id,
            "boundaries": {
                name: self.boundaries[name].summary()
                for name in BOUNDARIES
                if name in self.boundaries
            },
            "not_observed": list(self.missing()),
            "events": {
                "offered_to_transport": self.offered_events,
                "broker_acknowledged": self.acknowledged_events,
                "transport_failures": self.transport_failures,
                "bodies_without_a_nested_payload": self.bodies_without_payload,
            },
            # Said once, here, so no reader has to reconstruct it from field names.
            "note": (
                "payload_json is the nested document's own size and is never sent alone; "
                "mqtt_application is what was offered to the client, not proof of leaving "
                "the host; mqtt_publish_packet is derived from MQTT 3.1.1 framing. The "
                "observed wire total is reported separately by lab/mqtt_wire_counter.py."
            ),
        }


def _remaining_length_size(value: int) -> int:
    """Bytes MQTT 3.1.1 spends on the variable-length Remaining Length field."""
    if value < 0:
        raise VolumeError("remaining length cannot be negative")
    size = 1
    while value >= 128:
        value //= 128
        size += 1
    return size


def mqtt_publish_packet_bytes(topic: str, payload: bytes, *, qos: int = 1) -> int:
    """Size of one MQTT 3.1.1 PUBLISH packet: fixed header, topic, packet id, body.

    Derived from the protocol, which is why it is reported as `derived` and never as
    the measured cost of the network. It exists so the gap between the application
    bytes and the counted wire bytes has a named expectation to be compared against.
    """
    if not isinstance(payload, bytes | bytearray):
        raise VolumeError("payload must be bytes")
    if qos not in (0, 1, 2):
        raise VolumeError("qos must be 0, 1 or 2")
    variable = 2 + len(topic.encode("utf-8")) + (2 if qos else 0) + len(payload)
    return 1 + _remaining_length_size(variable) + variable


class CountingTransport:
    """Wrap a Transport and record what each publish cost, without changing it.

    The wrapper is deliberately not part of `TelemetryPublisher`: measurement must not
    live on the path it measures, and a run with no ledger must produce byte-identical
    behaviour to one with it.
    """

    def __init__(self, transport, ledger: VolumeLedger, *, size_nested_payload: bool = True):
        if not isinstance(ledger, VolumeLedger):
            raise VolumeError("ledger must be a VolumeLedger")
        self._transport = transport
        self._ledger = ledger
        self._size_nested_payload = size_nested_payload

    def _record_nested_payload(self, body: bytes) -> None:
        """Size the 0.1.0 document where it really sits: inside the envelope.

        This is the document's own canonical size — the bytes it occupies in the
        body, without the `"payload"` key and the separators around it. A body that
        carries no nested payload is counted as such instead of being passed over.
        """
        try:
            nested = json.loads(body)["payload"]
        except (ValueError, TypeError, KeyError):
            self._ledger.bodies_without_payload += 1
            return
        self._ledger.record_payload(nested)

    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> Acknowledgement:
        if self._size_nested_payload:
            self._record_nested_payload(payload)
        application = len(topic.encode("utf-8")) + len(payload)
        self._ledger.record(MQTT_APPLICATION, application)
        self._ledger.record(MQTT_PUBLISH_PACKET, mqtt_publish_packet_bytes(topic, payload, qos=qos))
        self._ledger.offered_events += 1
        try:
            acknowledgement = self._transport.publish(topic, payload, qos=qos, retain=retain)
        except TransportError:
            # The bytes were still offered, so they stay recorded; what is unknown is
            # whether they left the host, and that is exactly what is not counted here.
            self._ledger.transport_failures += 1
            raise
        if acknowledgement is Acknowledgement.ACKED:
            self._ledger.acknowledged_events += 1
        return acknowledgement


class CountingAdapter(UnixSocketAdapter):
    """The UDS adapter, with every frame it reads recorded before it is decoded.

    A subclass rather than an edit to `uds.py`: a run without measurement keeps the
    shipped class untouched. `handle_body` is the one place every frame body passes,
    including the ones that are refused — those bytes crossed the socket too, and
    leaving them out would report a boundary cheaper than it was. Which frames were
    refused stays in the adapter's own counters.
    """

    def __init__(self, *args, ledger: VolumeLedger, **kwargs):
        if not isinstance(ledger, VolumeLedger):
            raise VolumeError("ledger must be a VolumeLedger")
        super().__init__(*args, **kwargs)
        self._ledger = ledger

    def handle_body(self, body: bytes) -> bool:
        self._ledger.record_uds_frame(body)
        return super().handle_body(body)


class CountingStream:
    """A read-only stream wrapper that counts the bytes a reader actually consumed.

    `read_frame` pulls the length prefix and then the body, so counting at `read`
    gives the framed size that crossed the socket rather than a size computed from a
    decoded message.
    """

    def __init__(self, stream):
        self._stream = stream
        self.bytes_read = 0

    def read(self, count: int) -> bytes:
        chunk = self._stream.read(count)
        self.bytes_read += len(chunk)
        return chunk

    def __getattr__(self, name):
        return getattr(self._stream, name)
