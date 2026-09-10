"""Bounded event-time buffering for the frozen five-second window baseline.

The caller advances an ordered UTC watermark before adding each packet, and on
idle ticks. No clock, capture, feature extraction or state policy is hidden here.
"""

from dataclasses import dataclass
from math import floor

from core.schema import PacketTuple, number


class WindowError(ValueError):
    """Input cannot contribute to a trustworthy window; never infer benignness."""


class WindowCapacityError(WindowError):
    """A configured bound was reached and the entire open interval invalidated."""


@dataclass(frozen=True)
class PacketWindow:
    """Internal buffer result, not a feature or a new runtime wire envelope."""

    device_id: str
    start: float
    end: float
    packets: tuple[PacketTuple, ...]


class TumblingWindows:
    """Collect nonempty per-device windows with explicit watermark advancement.

    Start at an epoch-aligned boundary; discard a capture's initial partial window
    before construction. No packet reordering or lateness allowance is provided.
    A loss/overload/late input poisons the current interval; it emits no windows.
    Advancing across its end recovers an empty buffer for the new interval. This
    is conservative buffer behavior, not an ObservationHealth wire contract.
    """

    def __init__(
        self,
        start: float,
        *,
        max_devices: int = 64,
        max_packets_per_device: int = 2048,
        max_packets_total: int = 32768,
    ):
        number(start, "start")
        if start % 5 or start + 5 <= start:
            raise WindowError("start must be epoch-aligned; skip initial partial window")
        for value in (max_devices, max_packets_per_device, max_packets_total):
            if type(value) is not int or value < 1:
                raise ValueError("buffer limits must be positive integers")
        self._watermark = start
        self._start = start
        self._buffers: dict[str, list[PacketTuple]] = {}
        self._total = 0
        self._last_packet_ts = start
        self._invalid_reason: str | None = None
        self._max_devices = max_devices
        self._max_per_device = max_packets_per_device
        self._max_total = max_packets_total

    @property
    def watermark(self) -> float:
        return self._watermark

    @property
    def buffered_packets(self) -> int:
        return self._total

    @property
    def invalid_reason(self) -> str | None:
        return self._invalid_reason

    def invalidate(self, reason: str) -> None:
        """Caller reports capture loss/error; discard every device in this interval."""
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("invalidation needs a nonempty reason")
        self._buffers.clear()
        self._total = 0
        self._invalid_reason = reason

    def advance(self, watermark: float) -> tuple[PacketWindow, ...]:
        """Close intervals ending at/before an ordered UTC observation watermark.

        EOF alone is not evidence the final interval is complete. Do not advance
        to its end just to flush it. Empty/missing intervals create no zero-vector
        or benign result. Downstream policy must notice gaps independently.
        """
        try:
            number(watermark, "watermark")
            if watermark + 5 <= watermark:
                raise ValueError("timestamp precision cannot represent five seconds")
        except ValueError:
            self.invalidate("invalid clock value")
            raise
        if watermark < max(self._watermark, self._last_packet_ts):
            self.invalidate("backward watermark")
            raise WindowError("watermark cannot move backward")
        self._watermark = watermark
        if watermark < self._start + 5:
            return ()
        closed = tuple(
            PacketWindow(device, self._start, self._start + 5, tuple(packets))
            for device, packets in sorted(self._buffers.items())
        )
        self._buffers.clear()
        self._total = 0
        self._invalid_reason = None
        self._start = floor(watermark / 5) * 5
        return closed

    def add(self, packet: PacketTuple) -> None:
        """Add only within the active interval; call advance before crossing it."""
        if not isinstance(packet, PacketTuple):
            self.invalidate("invalid packet type")
            raise WindowError("expected PacketTuple")
        if packet.timestamp < max(self._watermark, self._last_packet_ts):
            self.invalidate("late packet")
            raise WindowError("late packet; closed windows cannot be amended")
        if packet.timestamp >= self._start + 5:
            raise WindowError("advance watermark before adding a new-interval packet")
        if self._invalid_reason is not None:
            raise WindowError(f"interval invalid: {self._invalid_reason}")
        packets = self._buffers.get(packet.device_id)
        if (
            (packets is None and len(self._buffers) >= self._max_devices)
            or (packets is not None and len(packets) >= self._max_per_device)
            or self._total >= self._max_total
        ):
            self.invalidate("buffer capacity exceeded")
            raise WindowCapacityError("buffer capacity exceeded; whole interval discarded")
        self._buffers.setdefault(packet.device_id, []).append(packet)
        self._total += 1
        self._last_packet_ts = packet.timestamp
