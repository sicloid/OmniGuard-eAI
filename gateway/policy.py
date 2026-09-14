"""Single-device, caller-clocked decision policy; never applies firewall rules."""

from core.schema import Classification, DetectionResult, DeviceState, StateEvent, nonempty, number


class DevicePolicy:
    """One bounded episode at a time, with no automatic lease renewal.

    Call tick independently of inference. Re-arm after release requires an explicit
    owner action; a new object must not be used to bypass kernel reconciliation.
    """

    def __init__(self, device_id: str, *, n: int, lease_seconds: float, max_lease: float):
        nonempty(device_id, "device_id")
        if type(n) is not int or n < 1:
            raise ValueError("n must be a positive integer")
        number(lease_seconds, "lease_seconds")
        number(max_lease, "max_lease")
        if not 0 < lease_seconds <= max_lease:
            raise ValueError("lease must be positive and bounded by max_lease")
        self.device_id = device_id
        self.n = n
        self.lease_seconds = lease_seconds
        self.state = DeviceState.NORMAL
        self.count = 0
        self.deadline = None
        self.armed = True
        self._last_window = None
        self._model = None
        self._mono = None

    def _clock(self, now: float, mono: float) -> None:
        number(now, "UTC now")
        number(mono, "monotonic now")
        if self._mono is not None and mono < self._mono:
            self.count = 0
            raise ValueError("monotonic clock regressed; reconcile before reuse")
        self._mono = mono

    def _transition(self, state, reason, now, expires=None):
        if state == self.state:
            return ()
        event = StateEvent(self.device_id, self.state, state, reason, now, expires)
        self.state = state
        return (event,)

    def tick(self, *, now: float, mono: float) -> tuple[StateEvent, ...]:
        """Expire a decision even without observations; UTC never extends a lease."""
        self._clock(now, mono)
        if self.deadline is not None and mono >= self.deadline:
            self.deadline = None
            self.count = 0
            self.armed = False
            return self._transition(DeviceState.NORMAL, "lease expired; not a clean bill", now)
        return ()

    def invalidate(self, *, now: float, mono: float) -> tuple[StateEvent, ...]:
        """Missing/invalid/stale/empty observation breaks N, not an active lease."""
        events = self.tick(now=now, mono=mono)
        self.count = 0
        if self.state == DeviceState.SUSPICIOUS:
            events += self._transition(DeviceState.NORMAL, "observation unavailable", now)
        return events

    def observe(self, result: DetectionResult, *, now: float, mono: float):
        if not isinstance(result, DetectionResult) or result.device_id != self.device_id:
            raise ValueError("expected this device's DetectionResult")
        events = self.tick(now=now, mono=mono)
        start = result.window_ts
        # A complete five-second window may be at most one second late.
        if start % 5 or not 0 <= now - (start + 5) <= 1:
            return events + self.invalidate(now=now, mono=mono)
        if self._last_window is not None and start <= self._last_window:
            return events + self.invalidate(now=now, mono=mono)
        model = (result.model_id, result.model_version, result.threshold)
        if self._last_window != start - 5 or self._model != model:
            self.count = 0
        self._last_window, self._model = start, model
        if self.state == DeviceState.QUARANTINED or not self.armed:
            return events
        if result.classification == Classification.NORMAL:
            self.count = 0
            return events + self._transition(DeviceState.NORMAL, "observed below threshold", now)
        self.count += 1
        if self.count >= self.n:
            self.deadline = mono + self.lease_seconds
            return events + self._transition(
                DeviceState.QUARANTINED,
                "consecutive eligible anomalies",
                now,
                now + self.lease_seconds,
            )
        return events + self._transition(DeviceState.SUSPICIOUS, "anomaly series started", now)

    def release(self, *, now: float, mono: float):
        """Decision only: the enforcer must separately prove traffic restoration."""
        events = self.tick(now=now, mono=mono)
        self.deadline = None
        self.count = 0
        self.armed = False
        return events + self._transition(DeviceState.NORMAL, "explicit release", now)

    def rearm(self):
        """Explicit new episode after caller has reconciled enforcement/binding."""
        if self.state != DeviceState.NORMAL or self.deadline is not None:
            raise ValueError("release and reconcile before rearming")
        self.count = 0
        self.armed = True
        # Keep window high-water mark to prevent reusing old evidence.
