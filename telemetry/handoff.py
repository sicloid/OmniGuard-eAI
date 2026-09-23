"""ADR-0003 bounded producer handoff: telemetry never holds the critical path.

`TelemetryPublisher` talks to a transport and to the filesystem. Both can stall:
a broker connection can hang until its own timeout, and an `fsync` on a failing
disk can block or raise. Calling the publisher directly from the code that
quarantines or releases a device therefore couples enforcement to telemetry,
which ADR-0002 forbids: "telemetry loss cannot block enforcement or release".

This module owns that boundary. The producer calls `submit()`, which does three
things and nothing else: a bounded, non-blocking enqueue, a counter update, and a
return. The transport and the spool belong to the worker thread on the far side
of the queue; no filesystem call and no broker call happens on the producer's
thread.

The queue is bounded on purpose. An unbounded queue turns a broker outage into
unbounded memory growth, which is a slower way to lose the host. When the queue
is full the event is dropped at the boundary and `OVERFLOWED` is returned, so the
loss is a reported outcome rather than a hidden delay. Overflow here and spool
eviction in the worker are both counted; G10 completeness reads both.

The worker never lets a telemetry failure escape. A stalled transport holds only
the worker, and an exception from the publisher, disk errors included, is
recorded as a worker failure and the worker continues.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, replace

from core.schema import StateEvent
from telemetry.outcomes import HandoffOutcome
from telemetry.publisher import TelemetryPublisher

STOP_TIMEOUT_SECONDS = 5.0
POLL_SECONDS = 0.05


class HandoffError(RuntimeError):
    """The handoff was used outside its lifecycle."""


@dataclass(frozen=True)
class HandoffCounters:
    """Boundary accounting. Delivery accounting stays on the publisher."""

    accepted: int = 0
    overflowed: int = 0
    refused: int = 0
    processed: int = 0
    worker_failures: int = 0
    last_failure: str | None = None


@dataclass(frozen=True)
class _Publish:
    event: StateEvent
    now: float


@dataclass(frozen=True)
class _Drain:
    now: float


class TelemetryHandoff:
    """A bounded queue with a worker that owns the transport and the spool.

    Used as a context manager:

        with TelemetryHandoff(publisher, capacity=256) as handoff:
            handoff.submit(event, now=timestamp)
    """

    def __init__(
        self,
        publisher: TelemetryPublisher,
        *,
        capacity: int,
        poll_seconds: float = POLL_SECONDS,
    ):
        if type(capacity) is not int or capacity < 1:
            raise HandoffError("capacity must be a positive integer")
        if isinstance(poll_seconds, bool) or not isinstance(poll_seconds, int | float):
            raise HandoffError("poll_seconds must be a number")
        self._publisher = publisher
        self._queue: queue.Queue = queue.Queue(maxsize=capacity)
        self._poll_seconds = float(poll_seconds)
        # Held only for the few statements that replace the counters. The worker
        # never holds it across a publish, so a stalled transport cannot make the
        # producer wait on it.
        self._lock = threading.Lock()
        self._counters = HandoffCounters()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def counters(self) -> HandoffCounters:
        with self._lock:
            return self._counters

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def __enter__(self) -> TelemetryHandoff:
        self.start()
        return self

    def __exit__(self, *_exception) -> None:
        self.stop()

    def start(self) -> None:
        if self._thread is not None:
            raise HandoffError("handoff already started")
        self._stopping.clear()
        self._thread = threading.Thread(target=self._run, name="telemetry-handoff", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = STOP_TIMEOUT_SECONDS) -> bool:
        """Drain what is queued, then end the worker.

        Returns False when the worker did not finish in time. A transport stalled
        inside a blocking call cannot be interrupted from here, so this reports
        that truthfully instead of claiming a clean stop.
        """
        if self._thread is None:
            return True
        self._stopping.set()
        self._thread.join(timeout)
        if self._thread.is_alive():
            return False
        self._thread = None
        return True

    def submit(self, event: StateEvent, *, now: float) -> HandoffOutcome:
        """Hand one event to the worker without touching the broker or the disk."""
        return self._enqueue(_Publish(event, now))

    def submit_drain(self, *, now: float) -> HandoffOutcome:
        """Ask the worker to retry the spool. Retrying is never the caller's wait."""
        return self._enqueue(_Drain(now))

    def _enqueue(self, command: _Publish | _Drain) -> HandoffOutcome:
        """The whole producer-side cost: one bounded put and one counter update."""
        if self._thread is None or self._stopping.is_set():
            # A submission to a stopped handoff is a reported loss, not a silent one.
            return self._count(HandoffOutcome.REFUSED, "refused")
        try:
            self._queue.put_nowait(command)
        except queue.Full:
            return self._count(HandoffOutcome.OVERFLOWED, "overflowed")
        return self._count(HandoffOutcome.ACCEPTED, "accepted")

    def _count(self, outcome: HandoffOutcome, field: str) -> HandoffOutcome:
        with self._lock:
            self._counters = replace(self._counters, **{field: getattr(self._counters, field) + 1})
        return outcome

    def _run(self) -> None:
        while True:
            try:
                command = self._queue.get(timeout=self._poll_seconds)
            except queue.Empty:
                if self._stopping.is_set():
                    return
                continue
            try:
                self._apply(command)
            except Exception as exc:
                # Deliberately total: this thread exists so that no telemetry
                # failure, disk errors included, reaches the producer. The
                # failure is counted and named; the worker keeps running.
                self._record_failure(exc)
            finally:
                self._queue.task_done()

    def _apply(self, command: _Publish | _Drain) -> None:
        if isinstance(command, _Drain):
            self._publisher.drain(now=command.now)
        else:
            self._publisher.publish(command.event, now=command.now)
        with self._lock:
            self._counters = replace(self._counters, processed=self._counters.processed + 1)

    def _record_failure(self, exc: BaseException) -> None:
        with self._lock:
            self._counters = replace(
                self._counters,
                worker_failures=self._counters.worker_failures + 1,
                last_failure=f"{type(exc).__name__}: {exc}",
            )
