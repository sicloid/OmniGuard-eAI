"""Capture-to-feature composition for trustworthy five-second windows.

This module creates no wire record and owns no policy state.  It only connects
the approved PacketTuple, bounded window buffer and shared pure extractor.
"""

from math import floor
from typing import Protocol

from core.features import extract_features
from core.schema import FeatureVector, PacketTuple, number
from gateway.windows import TumblingWindows


class PacketCapture(Protocol):
    """Small boundary implemented by LiveCapture and deterministic test captures."""

    def read(self, timeout: float = 0.25) -> PacketTuple | None: ...


class WindowFeaturePipeline:
    """Produce features only from complete, non-invalidated packet windows."""

    def __init__(self, start: float, *, max_lateness: float = 1.0, **window_limits: int):
        self._windows = TumblingWindows(start, **window_limits)
        number(max_lateness, "max_lateness")
        self._max_lateness = max_lateness
        self._start = start
        self._initial_start = start
        self._started = False
        self._closed = False
        self.status = "initial"
        self.reset_generation = 0

    @property
    def watermark(self) -> float:
        return self._windows.watermark

    @property
    def invalid_reason(self) -> str | None:
        return self._windows.invalid_reason

    @property
    def buffered_packets(self) -> int:
        return self._windows.buffered_packets

    def invalidate(self, reason: str) -> None:
        """Discard the active interval after capture loss or another health failure."""
        self._windows.invalidate(reason)
        self.status = "invalid"
        self.reset_generation += 1

    def advance(self, watermark: float) -> tuple[FeatureVector, ...]:
        """Close through a trusted event-time watermark and extract usable vectors."""
        if self._closed:
            raise ValueError("pipeline closed")
        try:
            number(watermark, "watermark")
        except ValueError:
            self.invalidate("invalid clock value")
            raise
        if watermark < self._initial_start and not self._started:
            self.status = "initial_partial"
            return ()
        self._started = True
        if watermark > self._start + 5 + self._max_lateness:
            self.invalidate("stale window")
            self.status = "stale"
        vectors = []
        try:
            closed = self._windows.advance(watermark)
        except ValueError:
            self.invalidate("invalid clock/order")
            raise
        for window in closed:
            vector = extract_features(window.device_id, window.start, window.packets)
            if vector is not None:
                vectors.append(vector)
        if watermark >= self._start + 5:
            if not vectors and self.status not in ("stale", "invalid"):
                self.status = "empty"
                self.reset_generation += 1
            elif vectors:
                self.status = "ready"
            self._start = floor(watermark / 5) * 5
        return tuple(vectors)

    def ingest(self, packet: PacketTuple) -> tuple[FeatureVector, ...]:
        """Advance to a packet's kernel timestamp, then retain it in its interval."""
        vectors = self.advance(packet.timestamp)
        if packet.timestamp < self._initial_start and not self._started:
            return ()
        try:
            self._windows.add(packet)
        except ValueError:
            self.invalidate("packet order/capacity failure")
            raise
        return vectors

    def capture_once(
        self, capture: PacketCapture, timeout: float = 0.25
    ) -> tuple[FeatureVector, ...]:
        """Read once; only source-supported progress may close an idle window."""
        try:
            progress = getattr(capture, "read_progress", None)
            packet, watermark = progress(timeout) if progress else (capture.read(timeout), None)
            if packet is not None:
                return self.ingest(packet)
            if watermark is not None:
                return self.advance(watermark)
        except Exception as exc:
            self.invalidate(f"capture failure: {type(exc).__name__}")
            raise
        return ()

    def close_capture(self, capture) -> None:
        """Check final socket loss and discard partial EOF; never flush features."""
        try:
            capture.close()
        finally:
            self.invalidate("capture ended; final interval incomplete")
            self._closed = True
