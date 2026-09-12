# R2 — Şükrü

Next: per-device 5-second tumbling windows, configurable N
state machine, reversible nftables enforcement and conntrack regression test.
Use `stubs.fake_features` and `stubs.fake_detector` to develop independently.
Enforce only in the gateway namespace. Sink stop and restore are required evidence.

## KAN-29: model-independent detector boundary

`gateway.detector.Detector` defines `predict(FeatureVector) -> DetectionResult`.
`CheckedDetector` wraps any implementation of this method, including the existing
`FakeDetector`. Its immutable `DetectorSpec` binds expected model identity/version,
feature schema/order, validation-selected threshold and runtime schema 0.1.0.

```python
from gateway.detector import CheckedDetector, DetectorSpec
from stubs.fake_detector import FakeDetector
from stubs.fake_features import STUB_FEATURE_ORDER, STUB_FEATURE_VERSION, fake_features

spec = DetectorSpec(
    "STUB-NOT-TRAINED", "0.1", STUB_FEATURE_VERSION, STUB_FEATURE_ORDER, 0.5
)
detector = CheckedDetector(FakeDetector(), spec)
result = detector.predict(fake_features("camera-1", 0))
```

Feature version/order and five-second epoch alignment are checked before inference.
The output must retain input device/window, configured model identity and threshold.
Type/compatibility failures raise `DetectorCompatibilityError`. Backend exceptions
raise `DetectorInferenceError` with their cause, including exhausted stub sequences;
process cancellation propagates. No retry or fallback NORMAL result is generated.
Callers must treat either error as no usable decision, not evidence of benign traffic.

The boundary does not decide whether a window is complete/fresh or apply policy.
The caller owns observation eligibility and ordering. Calls are synchronous; this
interface cannot stop a hung model. Process deadlines and privilege isolation belong
to runtime orchestration. Python typing is not a sandbox. Load only trusted model
code without capture/firewall privileges. No artifact deserialization, model training,
telemetry, enforcement, or wire-envelope change is introduced here. R1 supplies the
real implementation and verified artifact metadata in KAN-9/KAN-18.

Tests: `.venv/bin/python -m unittest discover -s tests -p test_detector.py -v`.
Two interchangeable implementations, pre-call rejection, output mismatch, exact
threshold equality, failure/cancellation and stub exhaustion are covered. These
prove interface behavior, not trained-model performance or G8/G10.
