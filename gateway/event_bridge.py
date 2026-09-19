"""Gateway-side, non-blocking StateEvent handoff to the host Unix socket.

ADR-0003 owns the framing/body contract. This module does not add an envelope or
identity fields: the gateway sends exactly the six 0.1.0 StateEvent fields, encoded
canonically and framed with the shared bounded length prefix. Producer/boot/sequence,
run_id and event_id remain host-side responsibilities.

The producer-facing submit path never touches a socket. It performs only a bounded
put_nowait and counter update; a worker owns connect/send failures. Telemetry loss can
therefore be reported without delaying enforcement or release.
"""

from __future__ import annotations

import queue
import socket
import threading
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from core.schema import StateEvent
from telemetry.canonical import canonical_bytes
from telemetry.framing import encode_frame

DEFAULT_SOCKET_TIMEOUT_SECONDS = 1.0
DEFAULT_POLL_SECONDS = 0.05


class BridgeError(RuntimeError):
    """The bridge cannot run as configured."""


class BridgeOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    OVERFLOWED = "OVERFLOWED"
    REFUSED = "REFUSED"


@dataclass(frozen=True)
class BridgeCounters:
    accepted: int = 0
    overflowed: int = 0
    refused: int = 0
    delivered: int = 0
    failures: int = 0
    last_failure: str | None = None


class EventTransport(Protocol):
    def send(self, event: StateEvent) -> None: ...


def state_event_document(event: StateEvent) -> dict:
    """Return exactly ADR-0003 section 2.1's six gateway-owned fields."""
    if not isinstance(event, StateEvent):
        raise TypeError("event must be a StateEvent")
    return {
        "device_id": event.device_id,
        "previous_state": event.previous_state.value,
        "new_state": event.new_state.value,
        "reason": event.reason,
        "timestamp": event.timestamp,
        "expires_at": event.expires_at,
    }


def state_event_frame(event: StateEvent) -> bytes:
    """Canonical JSON body plus the shared four-byte bounded frame."""
    return encode_frame(canonical_bytes(state_event_document(event)))


class UnixSocketTransport:
    """One-event AF_UNIX transport with a bounded connect/write timeout.

    A fresh connection per event is intentionally simple for the prototype. The
    non-blocking guarantee belongs to GatewayEventBridge, whose worker owns this call.
    """

    def __init__(self, path: Path, *, timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS):
        if not hasattr(socket, "AF_UNIX"):
            raise BridgeError("this Python does not expose AF_UNIX")
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        self.path = Path(path)
        self.timeout = float(timeout)

    def send(self, event: StateEvent) -> None:
        frame = state_event_frame(event)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout)
            client.connect(str(self.path))
            client.sendall(frame)


class GatewayEventBridge:
    """Bounded producer queue whose worker alone performs Unix-socket I/O."""

    def __init__(
        self,
        transport: EventTransport,
        *,
        capacity: int = 256,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be a positive integer")
        if (
            isinstance(poll_seconds, bool)
            or not isinstance(poll_seconds, int | float)
            or poll_seconds <= 0
        ):
            raise ValueError("poll_seconds must be a positive number")
        self._transport = transport
        self._queue: queue.Queue[StateEvent] = queue.Queue(maxsize=capacity)
        self._poll_seconds = float(poll_seconds)
        self._lock = threading.Lock()
        self._counters = BridgeCounters()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def counters(self) -> BridgeCounters:
        with self._lock:
            return self._counters

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def __enter__(self) -> GatewayEventBridge:
        self.start()
        return self

    def __exit__(self, *_exception) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread is not None:
            raise BridgeError("bridge already started")
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="gateway-event-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> bool:
        if self._thread is None:
            return True
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        self._stopping.set()
        self._thread.join(float(timeout))
        if self._thread.is_alive():
            return False
        self._thread = None
        return True

    def submit(self, event: StateEvent) -> BridgeOutcome:
        """Enqueue without socket or filesystem I/O on the caller's thread."""
        if not isinstance(event, StateEvent):
            return self._count(BridgeOutcome.REFUSED, "refused")
        if self._thread is None or self._stopping.is_set():
            return self._count(BridgeOutcome.REFUSED, "refused")
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            return self._count(BridgeOutcome.OVERFLOWED, "overflowed")
        return self._count(BridgeOutcome.ACCEPTED, "accepted")

    def _count(self, outcome: BridgeOutcome, field: str) -> BridgeOutcome:
        with self._lock:
            self._counters = replace(
                self._counters,
                **{field: getattr(self._counters, field) + 1},
            )
        return outcome

    def _run(self) -> None:
        while True:
            try:
                event = self._queue.get(timeout=self._poll_seconds)
            except queue.Empty:
                if self._stopping.is_set():
                    return
                continue
            try:
                self._transport.send(event)
            except Exception as exc:
                with self._lock:
                    self._counters = replace(
                        self._counters,
                        failures=self._counters.failures + 1,
                        last_failure=f"{type(exc).__name__}: {exc}",
                    )
            else:
                with self._lock:
                    self._counters = replace(
                        self._counters,
                        delivered=self._counters.delivered + 1,
                    )
            finally:
                self._queue.task_done()
            if self._stopping.is_set() and self._queue.empty():
                return
