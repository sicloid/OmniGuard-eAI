"""Model-independent boundary using the existing 0.1.0 input/output envelopes.

This module loads no artifacts and creates no workers, network clients or firewall
commands. The caller owns scheduling, observation eligibility and policy. A Python
interface is not a sandbox: run trusted model code without elevated privileges.
"""

from dataclasses import dataclass
from typing import Protocol

from core.schema import (
    SCHEMA_VERSION,
    DetectionResult,
    FeatureVector,
    nonempty,
    probability,
)


class Detector(Protocol):
    """Implementations return a score result, never a state transition."""

    def predict(self, vector: FeatureVector) -> DetectionResult: ...


class DetectorError(ValueError):
    """No usable decision was produced; callers must not substitute NORMAL."""


class DetectorCompatibilityError(DetectorError):
    """Input or output does not match the configured model contract."""


class DetectorInferenceError(DetectorError):
    """The implementation raised during inference; original exception is chained."""


@dataclass(frozen=True)
class DetectorSpec:
    """Expected in-memory metadata, supplied by the trusted artifact owner.

    This is not an artifact manifest parser or an additional wire envelope.
    The 0.1.0 baseline has fixed five-second epoch-aligned windows.
    """

    model_id: str
    model_version: str
    feature_schema_version: str
    feature_order: tuple[str, ...]
    threshold: float
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("model_id", "model_version", "feature_schema_version"):
            nonempty(getattr(self, name), name)
        if self.schema_version != SCHEMA_VERSION:
            raise DetectorCompatibilityError("unsupported runtime schema_version")
        if type(self.feature_order) is not tuple or not self.feature_order:
            raise DetectorCompatibilityError("feature_order must be a nonempty tuple")
        for name in self.feature_order:
            nonempty(name, "feature name")
        if len(set(self.feature_order)) != len(self.feature_order):
            raise DetectorCompatibilityError("duplicate feature name")
        probability(self.threshold, "threshold")


class CheckedDetector:
    """Validate compatibility before calling a replaceable model implementation.

    Successful results preserve the input device and window, expected model
    identity and validation-selected threshold. No retries, imputation, result
    caching or default score are performed. Calls are synchronous; the caller
    must provide process isolation/deadlines for potentially hanging models.
    """

    def __init__(self, detector: Detector, spec: DetectorSpec):
        if not isinstance(spec, DetectorSpec):
            raise TypeError("spec must be a DetectorSpec")
        if not callable(getattr(detector, "predict", None)):
            raise TypeError("detector must implement predict(vector)")
        self._detector = detector
        self._spec = spec

    @property
    def spec(self) -> DetectorSpec:
        return self._spec

    def predict(self, vector: FeatureVector) -> DetectionResult:
        if not isinstance(vector, FeatureVector):
            raise DetectorCompatibilityError("input must be a FeatureVector")
        spec = self._spec
        if (
            vector.feature_schema_version != spec.feature_schema_version
            or vector.feature_order != spec.feature_order
        ):
            raise DetectorCompatibilityError("feature schema/order mismatch")
        if vector.window_start % 5 != 0 or vector.window_end != vector.window_start + 5:
            raise DetectorCompatibilityError("expected epoch-aligned five-second window")
        try:
            result = self._detector.predict(vector)
        except Exception as exc:
            raise DetectorInferenceError("detector failed; no decision available") from exc
        if not isinstance(result, DetectionResult):
            raise DetectorCompatibilityError("output must be a DetectionResult")
        if (
            result.device_id != vector.device_id
            or result.window_ts != vector.window_start
            or result.model_id != spec.model_id
            or result.model_version != spec.model_version
            or result.threshold != spec.threshold
        ):
            raise DetectorCompatibilityError("result device/window/model/threshold mismatch")
        return result
