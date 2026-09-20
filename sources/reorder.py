"""Bound small, measured AF_PACKET timestamp inversions before windowing.

Linux can deliver closely spaced TCP/UDP frames out of kernel timestamp order.
This wrapper preserves their original timestamps, sorts within a fixed event-time
lateness and fails closed if an already-emitted watermark is contradicted.  It
never treats a filtered frame as idle progress or hides socket loss.
"""

import heapq
import time
from typing import Protocol

from core.schema import PacketTuple, number
from sources.live import CaptureError


class ProgressCapture(Protocol):
    def read_progress(self, timeout: float) -> tuple[PacketTuple | None, float | None]: ...
    def close(self) -> None: ...


class BoundedReorderCapture:
    """Sort original PacketTuples within a bounded event-time window and heap."""

    def __init__(self, capture: ProgressCapture, *, lateness: float = 0.002, capacity: int = 256):
        number(lateness, "lateness")
        if not 0 < lateness <= 0.1:
            raise ValueError("lateness must be in (0, 0.1] seconds")
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError("capacity must be an integer in [1, 65536]")
        self.capture = capture
        self.lateness = lateness
        self.capacity = capacity
        self._heap: list[tuple[float, int, PacketTuple]] = []
        self._sequence = 0
        self._max_seen = -1.0
        self._last_emitted = -1.0
        self._pending_cutoff: float | None = None
        self._failed = False
        self.reordered_packets = 0
        self.max_inversion_seconds = 0.0
        self.buffer_high_water = 0
        self.excess_lateness_seconds = 0.0

    @property
    def stats(self) -> dict[str, float | int]:
        return {
            "reordered_packets": self.reordered_packets,
            "max_inversion_seconds": self.max_inversion_seconds,
            "buffer_high_water": self.buffer_high_water,
            "excess_lateness_seconds": self.excess_lateness_seconds,
        }

    def _fail(self, reason: str) -> None:
        self._failed = True
        self._heap.clear()
        raise CaptureError(reason)

    def _pop(self) -> PacketTuple:
        timestamp, _, packet = heapq.heappop(self._heap)
        if timestamp < self._last_emitted:
            self._fail("packet timestamp fell behind an emitted packet/watermark")
        self._last_emitted = timestamp
        return packet

    def _drain_cutoff(self) -> tuple[PacketTuple | None, float | None]:
        cutoff = self._pending_cutoff
        assert cutoff is not None
        if self._heap and self._heap[0][0] <= cutoff:
            return self._pop(), None
        if cutoff < self._last_emitted:
            self._fail("capture watermark regressed behind emitted evidence")
        self._last_emitted = cutoff
        self._pending_cutoff = None
        return None, cutoff

    def read_progress(self, timeout: float = 0.25) -> tuple[PacketTuple | None, float | None]:
        if self._failed:
            raise CaptureError("reorder capture failed; start a new observation session")
        number(timeout, "timeout")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if self._pending_cutoff is not None:
            return self._drain_cutoff()
        deadline = time.monotonic() + timeout
        while True:
            if self._heap and self._heap[0][0] <= self._max_seen - self.lateness:
                return self._pop(), None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, None
            try:
                packet, watermark = self.capture.read_progress(remaining)
            except Exception:
                self._failed = True
                self._heap.clear()
                raise
            if packet is not None:
                if packet.timestamp < self._last_emitted:
                    self.excess_lateness_seconds = max(
                        self.excess_lateness_seconds, self._last_emitted - packet.timestamp
                    )
                    self._fail("packet arrived behind emitted packet/watermark")
                if len(self._heap) >= self.capacity:
                    self._fail("timestamp reorder buffer exceeded capacity")
                if packet.timestamp < self._max_seen:
                    self.reordered_packets += 1
                    self.max_inversion_seconds = max(
                        self.max_inversion_seconds, self._max_seen - packet.timestamp
                    )
                heapq.heappush(self._heap, (packet.timestamp, self._sequence, packet))
                self.buffer_high_water = max(self.buffer_high_water, len(self._heap))
                self._sequence += 1
                self._max_seen = max(self._max_seen, packet.timestamp)
            elif watermark is not None:
                self._pending_cutoff = watermark
                return self._drain_cutoff()

    def close(self) -> None:
        self.capture.close()
