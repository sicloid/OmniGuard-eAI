"""Deterministic detector -> policy -> enforcement composition for the gateway.

The frozen 0.1.0 contracts remain the boundaries between detector and policy. This
module adds no wire record. It only makes the runtime obligations explicit:
DetectionResult drives DevicePolicy; policy StateEvents drive the narrow NftEnforcer;
inference failure invalidates the anomaly series instead of becoming NORMAL.

Policy intent and kernel application evidence remain separate. StateEvent is returned
unchanged and EnforcerReceipt is an internal implementation receipt from KAN-31.
"""

from dataclasses import dataclass

from core.schema import DetectionResult, DeviceState, FeatureVector, StateEvent
from gateway.detector import CheckedDetector, DetectorError
from gateway.enforcer import (
    DeviceBinding,
    EnforcementError,
    EnforcerReceipt,
    NftEnforcer,
)
from gateway.policy import DevicePolicy


class ControlError(RuntimeError):
    """The integration boundary cannot safely continue."""


@dataclass(frozen=True)
class ControlStep:
    """One deterministic controller step; no telemetry or new wire contract."""

    detection: DetectionResult | None
    events: tuple[StateEvent, ...]
    receipts: tuple[EnforcerReceipt, ...]
    detector_error: str | None = None


class StateEnforcementController:
    """Compose a checked detector, one-device policy and bounded enforcer.

    An enforcement error can occur after the policy has already emitted a transition.
    In that case policy intent and kernel state are no longer known to agree, so this
    controller enters a faulted state. Normal processing is then refused until an
    explicit reconcile verifies/releases any lingering kernel element.
    """

    def __init__(
        self,
        detector: CheckedDetector,
        policy: DevicePolicy,
        enforcer: NftEnforcer,
        binding: DeviceBinding,
    ):
        if not isinstance(detector, CheckedDetector):
            raise TypeError("detector must be a CheckedDetector")
        if not isinstance(policy, DevicePolicy):
            raise TypeError("policy must be a DevicePolicy")
        if not isinstance(enforcer, NftEnforcer):
            raise TypeError("enforcer must be an NftEnforcer")
        if not isinstance(binding, DeviceBinding):
            raise TypeError("binding must be a DeviceBinding")
        if policy.device_id != binding.device_id:
            raise ValueError("policy and binding must identify the same device")
        self.detector = detector
        self.policy = policy
        self.enforcer = enforcer
        self.binding = binding
        self._faulted = False

    @property
    def faulted(self) -> bool:
        """Whether kernel/policy consistency must be reconciled before more work."""
        return self._faulted

    def _require_healthy(self) -> None:
        if self._faulted:
            raise ControlError(
                "controller is faulted after an enforcement error; reconcile before continuing"
            )

    def process(self, vector: FeatureVector, *, now: float, mono: float) -> ControlStep:
        """Detect one complete vector, then apply policy and any kernel transition.

        Detector failures are observation failures. They reset an in-progress anomaly
        series through DevicePolicy.invalidate and are returned as diagnostics; they
        are never converted into a benign DetectionResult.
        """
        self._require_healthy()
        try:
            detection = self.detector.predict(vector)
        except DetectorError as exc:
            events = self.policy.invalidate(now=now, mono=mono)
            receipts = self._apply(events)
            return ControlStep(None, events, receipts, f"{type(exc).__name__}: {exc}")
        events = self.policy.observe(detection, now=now, mono=mono)
        return ControlStep(detection, events, self._apply(events))

    def invalidate(self, *, now: float, mono: float) -> ControlStep:
        """Propagate capture/window health loss into policy without inventing a score."""
        self._require_healthy()
        events = self.policy.invalidate(now=now, mono=mono)
        return ControlStep(None, events, self._apply(events), "observation invalidated")

    def tick(self, *, now: float, mono: float) -> ControlStep:
        """Advance lease expiry independently of capture and inference."""
        self._require_healthy()
        events = self.policy.tick(now=now, mono=mono)
        return ControlStep(None, events, self._apply(events))

    def release(self, *, now: float, mono: float) -> ControlStep:
        """Explicit operator release; kernel absence is still verified by the enforcer."""
        self._require_healthy()
        events = self.policy.release(now=now, mono=mono)
        return ControlStep(None, events, self._apply(events))

    def reconcile(self, *, now: float, mono: float) -> ControlStep:
        """Restore a known policy/kernel relation after restart or enforcement failure.

        Policy reconciliation ends an active episode. Kernel readback is then checked
        independently so a lingering element from a previous controller/process is
        released even when the current policy object has no matching StateEvent.
        """
        events = self.policy.reconcile(now=now, mono=mono)
        receipts = list(self._apply(events, allow_faulted=True))
        try:
            if self.enforcer.is_quarantined(self.binding):
                receipts.append(self.enforcer.release(self.binding))
        except EnforcementError:
            self._faulted = True
            raise
        self._faulted = False
        return ControlStep(None, events, tuple(receipts))

    def rearm(self) -> None:
        """Start a new episode only after reconciliation and a clear kernel readback."""
        self._require_healthy()
        if self.enforcer.is_quarantined(self.binding):
            raise ControlError("kernel quarantine is still active; refusing to rearm policy")
        self.policy.rearm()

    def _apply(
        self,
        events: tuple[StateEvent, ...],
        *,
        allow_faulted: bool = False,
    ) -> tuple[EnforcerReceipt, ...]:
        if not allow_faulted:
            self._require_healthy()
        receipts = []
        try:
            for event in events:
                if event.new_state == DeviceState.QUARANTINED:
                    if event.expires_at is None:
                        raise ControlError("QUARANTINED StateEvent must carry a bounded expiry")
                    lease_seconds = event.expires_at - event.timestamp
                    receipts.append(
                        self.enforcer.quarantine(
                            self.binding,
                            lease_seconds=lease_seconds,
                            max_lease_seconds=self.policy.max_lease,
                        )
                    )
                elif (
                    event.previous_state == DeviceState.QUARANTINED
                    and event.new_state == DeviceState.NORMAL
                ):
                    receipts.append(self.enforcer.release(self.binding))
        except EnforcementError:
            self._faulted = True
            raise
        return tuple(receipts)


__all__ = [
    "ControlError",
    "ControlStep",
    "StateEnforcementController",
    "EnforcementError",
]
