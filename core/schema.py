"""Draft G1 contracts. See SCHEMA.md and ADR-0001 before integrating."""

from dataclasses import asdict, dataclass
from enum import StrEnum
from ipaddress import ip_address
from math import isfinite

SCHEMA_VERSION = "0.1.0"


class Direction(StrEnum):
    EGRESS = "EGRESS"
    INGRESS = "INGRESS"
    LOCAL = "LOCAL"


class Classification(StrEnum):
    NORMAL = "NORMAL"
    ANOMALOUS = "ANOMALOUS"


class DeviceState(StrEnum):
    NORMAL = "NORMAL"
    SUSPICIOUS = "SUSPICIOUS"
    QUARANTINED = "QUARANTINED"


def nonempty(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")


def number(value: float, field: str, lower: float = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    if not isfinite(value) or value < lower:
        raise ValueError(f"{field} must be finite and >= {lower}")


def probability(value: float, field: str) -> None:
    number(value, field)
    if value > 1:
        raise ValueError(f"{field} must be <= 1")


def integer(value: int, field: str, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f"{field} must be an integer in [{lower}, {upper}]")


@dataclass(frozen=True)
class PacketTuple:
    timestamp: float
    device_id: str
    src_mac: str | None
    src_ip: str
    src_port: int | None
    dst_ip: str
    dst_port: int | None
    protocol: int
    tcp_flags: int
    packet_length: int
    direction: Direction

    def __post_init__(self) -> None:
        number(self.timestamp, "timestamp")
        nonempty(self.device_id, "device_id")
        if self.src_mac is not None:
            nonempty(self.src_mac, "src_mac")
        nonempty(self.src_ip, "src_ip")
        nonempty(self.dst_ip, "dst_ip")
        ip_address(self.src_ip)
        ip_address(self.dst_ip)
        for name in ("src_port", "dst_port"):
            value = getattr(self, name)
            if value is not None:
                integer(value, name, 0, 65535)
        integer(self.protocol, "protocol", 0, 255)
        integer(self.tcp_flags, "tcp_flags", 0, 511)
        integer(self.packet_length, "packet_length", 1, 65575)
        if not isinstance(self.direction, Direction):
            raise ValueError("direction must be a Direction")
        if self.protocol != 6 and self.tcp_flags != 0:
            raise ValueError("non-TCP packet must have zero tcp_flags")


@dataclass(frozen=True)
class FeatureVector:
    device_id: str
    window_start: float
    window_end: float
    feature_schema_version: str
    feature_order: tuple[str, ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        nonempty(self.device_id, "device_id")
        nonempty(self.feature_schema_version, "feature_schema_version")
        number(self.window_start, "window_start")
        number(self.window_end, "window_end")
        if self.window_end <= self.window_start:
            raise ValueError("window must have positive duration")
        if type(self.feature_order) is not tuple or type(self.values) is not tuple:
            raise ValueError("feature_order and values must be immutable tuples")
        if not self.feature_order or len(self.feature_order) != len(self.values):
            raise ValueError("feature names and values must have equal nonzero length")
        for name in self.feature_order:
            nonempty(name, "feature name")
        if len(set(self.feature_order)) != len(self.feature_order):
            raise ValueError("duplicate feature name")
        for value in self.values:
            number(value, "feature value", lower=-float("inf"))


@dataclass(frozen=True)
class DetectionResult:
    device_id: str
    window_ts: float
    model_id: str
    model_version: str
    score: float
    classification: Classification
    threshold: float

    def __post_init__(self) -> None:
        for name in ("device_id", "model_id", "model_version"):
            nonempty(getattr(self, name), name)
        number(self.window_ts, "window_ts")
        probability(self.score, "score")
        probability(self.threshold, "threshold")
        if not isinstance(self.classification, Classification):
            raise ValueError("classification must be a Classification")
        expected = (
            Classification.ANOMALOUS if self.score >= self.threshold else Classification.NORMAL
        )
        if self.classification != expected:
            raise ValueError("classification inconsistent with score >= threshold")


@dataclass(frozen=True)
class StateEvent:
    device_id: str
    previous_state: DeviceState
    new_state: DeviceState
    reason: str
    timestamp: float
    expires_at: float | None

    def __post_init__(self) -> None:
        nonempty(self.device_id, "device_id")
        nonempty(self.reason, "reason")
        number(self.timestamp, "timestamp")
        if not all(isinstance(s, DeviceState) for s in (self.previous_state, self.new_state)):
            raise ValueError("states must be DeviceState values")
        if self.previous_state == self.new_state:
            raise ValueError("StateEvent must describe a transition")
        if self.expires_at is not None:
            number(self.expires_at, "expires_at")
            if self.expires_at <= self.timestamp:
                raise ValueError("expiry must follow event timestamp")


@dataclass(frozen=True)
class TelemetryPayload:
    schema_version: str
    run_id: str
    event_id: str
    event: StateEvent

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported telemetry schema_version")
        nonempty(self.run_id, "run_id")
        nonempty(self.event_id, "event_id")
        if not isinstance(self.event, StateEvent):
            raise ValueError("event must be a StateEvent")

    def to_dict(self) -> dict:
        return asdict(self)
