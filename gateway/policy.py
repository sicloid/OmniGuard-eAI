"""Single-device, caller-clocked decision policy; never applies firewall rules."""

from core.schema import Classification, DetectionResult, DeviceState, StateEvent, nonempty, number

MAX_RESULT_AGE = 2.5
REJECTIONS = ("misaligned", "future", "stale", "duplicate")
RESETS = ("gap", "model_change", "invalidated")


class DevicePolicy:
    """One bounded episode at a time, with no automatic lease renewal.

    Call tick independently of inference. Re-arm after release requires an explicit
    owner action; a new object must not be used to bypass kernel reconciliation.
    """

    def __init__(
        self,
        device_id: str,
        *,
        n: int,
        lease_seconds: float,
        max_lease: float,
        max_result_age: float = MAX_RESULT_AGE,
    ):
        nonempty(device_id, "device_id")
        if type(n) is not int or n < 1:
            raise ValueError("n must be a positive integer")
        number(lease_seconds, "lease_seconds")
        number(max_lease, "max_lease")
        if not 0 < lease_seconds <= max_lease:
            raise ValueError("lease must be positive and bounded by max_lease")
        number(max_result_age, "max_result_age")
        if max_result_age <= 0:
            raise ValueError("max_result_age must be positive")
        self.device_id = device_id
        self.n = n
        self.lease_seconds = lease_seconds
        self.max_lease = max_lease
        self.max_result_age = max_result_age
        self.state = DeviceState.NORMAL
        self.count = 0
        self.deadline = None
        self.armed = True
        self.rejections = dict.fromkeys(REJECTIONS, 0)
        self.resets = dict.fromkeys(RESETS, 0)
        self._last_window = None
        self._model = None
        self._mono = None

    def _clock(self, now: float, mono: float) -> None:
        number(now, "UTC now")
        number(mono, "monotonic now")
        if self._mono is not None and mono < self._mono:
            raise ValueError("monotonic clock regressed; call reconcile with the new clock")
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
        self.resets["invalidated"] += 1
        return events + self._break_series(now)

    def _break_series(self, now: float) -> tuple[StateEvent, ...]:
        self.count = 0
        if self.state == DeviceState.SUSPICIOUS:
            return self._transition(DeviceState.NORMAL, "observation unavailable", now)
        return ()

    def _reject(self, reason: str, now: float) -> tuple[StateEvent, ...]:
        self.rejections[reason] += 1
        return self._break_series(now)

    def observe(self, result: DetectionResult, *, now: float, mono: float):
        if not isinstance(result, DetectionResult) or result.device_id != self.device_id:
            raise ValueError("expected this device's DetectionResult")
        events = self.tick(now=now, mono=mono)
        start = result.window_ts
        age = now - (start + 5)
        if start % 5:
            return events + self._reject("misaligned", now)
        if age < 0:
            return events + self._reject("future", now)
        if age > self.max_result_age:
            return events + self._reject("stale", now)
        if self._last_window is not None and start <= self._last_window:
            return events + self._reject("duplicate", now)
        model = (result.model_id, result.model_version, result.threshold)
        if self._last_window is not None and self._last_window != start - 5:
            self.resets["gap"] += 1
        if self._model is not None and self._model != model:
            self.resets["model_change"] += 1
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
        if self.state == DeviceState.NORMAL:
            raise ValueError("nothing to release: device is NORMAL and stays armed")
        events = self.tick(now=now, mono=mono)
        if self.state == DeviceState.NORMAL:
            return events
        self.deadline = None
        self.count = 0
        self.armed = False
        return events + self._transition(DeviceState.NORMAL, "explicit release", now)

    def reconcile(self, *, now: float, mono: float) -> tuple[StateEvent, ...]:
        """Accept a new monotonic base and observably end an active episode."""
        number(now, "UTC now")
        number(mono, "monotonic now")
        self._mono = mono
        if self.state == DeviceState.NORMAL:
            return ()
        self.deadline = None
        self.count = 0
        self.armed = False
        return self._transition(
            DeviceState.NORMAL,
            "monotonic clock reconciled; lease ended, not a clean bill",
            now,
        )

    def rearm(self):
        """Explicit new episode after caller has reconciled enforcement/binding."""
        if self.state != DeviceState.NORMAL or self.deadline is not None:
            raise ValueError("release and reconcile before rearming")
        self.count = 0
        self.armed = True
        # Keep window high-water mark to prevent reusing old evidence.
