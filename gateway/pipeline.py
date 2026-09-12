"""Capture-to-feature composition for trustworthy five-second windows.

This module creates no wire record and owns no policy state.  It only connects
the approved PacketTuple, bounded window buffer and shared pure extractor.
"""

from typing import Protocol

from core.features import extract_features
from core.schema import FeatureVector, PacketTuple
from gateway.windows import TumblingWindows


class PacketCapture(Protocol):
    """Small boundary implemented by LiveCapture and deterministic test captures."""

    def read(self, timeout: float = 0.25) -> PacketTuple | None: ...


class WindowFeaturePipeline:
    """Produce features only from complete, non-invalidated packet windows."""

    def __init__(self, start: float, **window_limits: int):
        self._windows = TumblingWindows(start, **window_limits)

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

    def advance(self, watermark: float) -> tuple[FeatureVector, ...]:
        """Close through a trusted event-time watermark and extract usable vectors."""
        vectors = []
        for window in self._windows.advance(watermark):
            vector = extract_features(window.device_id, window.start, window.packets)
            if vector is not None:
                vectors.append(vector)
        return tuple(vectors)

    def ingest(self, packet: PacketTuple) -> tuple[FeatureVector, ...]:
        """Advance to a packet's kernel timestamp, then retain it in its interval."""
        vectors = self.advance(packet.timestamp)
        self._windows.add(packet)
        return vectors

    def capture_once(
        self, capture: PacketCapture, timeout: float = 0.25
    ) -> tuple[FeatureVector, ...]:
        """Read once; capture failure poisons the interval and idle never closes it."""
        try:
            packet = capture.read(timeout)
        except Exception as exc:
            self.invalidate(f"capture failure: {type(exc).__name__}")
            raise
        if packet is None:
            return ()
        return self.ingest(packet)
