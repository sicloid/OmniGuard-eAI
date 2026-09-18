# R2 — Şükrü

Next: per-device 5-second tumbling windows, configurable N
state machine, reversible nftables enforcement and conntrack regression test.
Use `stubs.fake_features` and `stubs.fake_detector` to develop independently.
Enforce only in the gateway namespace. Sink stop and restore are required evidence.

## V3 design follow-up

V3 tasarım notu: karar/uygulama ayrımı, bounded kernel lease, restart uzlaştırması,
N=1/gap semantiği ve observation health için [mimariyi](../ARCHITECTURE.md) ve
[önerilen ADR-0002](../docs/adr/0002-bounded-containment.md) okuyun. Yeni kayıtlar
henüz onaylı 0.1.0 sözleşmesinin parçası değildir.

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

## KAN-30: bounded decision policy

`DevicePolicy(device_id, n=..., lease_seconds=..., max_lease=...)` consumes checked
`DetectionResult` values through `observe(result, now=utc, mono=monotonic)` and
returns existing 0.1.0 `StateEvent` tuples. Use one object per device, one caller,
with a bounded device registry owned by the runtime. Configuration is fixed for
an object's lifetime; create/reconcile a new policy for configuration changes.

N=1 requests quarantine in the first eligible window. Only consecutive complete
five-second windows count. A result older than `max_result_age` after its window
closes is stale. Its 2.5 s default composes capture delay, pipeline lateness and a
small extraction/inference allowance; callers may set it explicitly. Stale,
misaligned, future and duplicate results are dropped and counted in `rejections`.
Gaps, model/threshold changes and explicit invalidation reset the series and are
counted in `resets`. Call
`invalidate` on capture/pipeline reset_generation changes, empty windows and
inference failure; missing observations are not benign classifications.

Call `tick` independently of capture/inference, even when they stop producing
results. Durations use monotonic time, while event timestamp/expiry are UTC
presentation fields. Repeated anomalies and invalidation never renew a lease.
Expiry and `release` from SUSPICIOUS or QUARANTINED disarm the policy and emit a
NORMAL event. `release` on an already NORMAL device is rejected, preventing an
unobservable disarm. `rearm` is an explicit caller action
for a new reconciled episode; old window evidence remains rejected. This initial
review candidate allows at most one lease per armed episode. Neither the configured
freshness bound nor N/lease choices are validated detection-quality parameters.

After a monotonic regression, clocked calls reject without mutating policy state.
`reconcile(now=..., mono=...)` accepts the new clock base. It ends an active episode
with an explicit NORMAL event and disarms the policy; the caller can rearm only after
enforcement and device binding have also been reconciled.

This is decision logic, not a deployed controller: live scheduling, bounded device
registry, kernel TTL, restart/binding reconciliation and successful restoration
remain KAN-31/integration work. Creating a new object is not evidence that an old
kernel block disappeared. QUARANTINED is a request, NORMAL after expiry/release
is not a clean-device or firewall-success claim. ADR-0002 stays PROPOSED; no new
wire field or production policy is introduced. No MQTT, disk or firewall I/O runs
in this component.


## KAN-31: bounded nftables enforcer

`gateway.enforcer.NftEnforcer` is the narrow mutation boundary between the existing
policy decision and the owned nftables set. It accepts an explicit `DeviceBinding`,
a lease and its caller-provided maximum, then executes fixed argv through
`ip netns exec <owned-namespace> nft ...`; it never invokes a shell, creates a
ruleset or flushes host/network state.

The lab set now has `flags timeout`. A new quarantine element is installed with a
per-element kernel timeout and is read back before `APPLIED` is reported. Applying
again while the element exists returns `ALREADY_APPLIED` without issuing another
add, so repeated anomaly evidence cannot silently renew the lease. Release deletes
only that device element and verifies absence; a release after kernel expiry is an
idempotent `ALREADY_RELEASED`.

`EnforcerReceipt` is internal implementation evidence, **not** ADR-0002's proposed
wire-level EnforcementResult. The five 0.1.0 runtime contracts are unchanged.
`is_quarantined()` exists for restart/reconcile callers but does not itself mutate
or claim traffic restoration.

Unit tests cover namespace/IP validation, bounded leases, no-renewal, readback,
idempotent release, missing-owned-set refusal and static guards against host ruleset
flush or conntrack deletion. The existing dedicated Linux smoke still provides
established-flow sink stop/restore evidence through `lab/smoke_netns.sh`; this PR
does not claim that hosted CI is a privileged G8 run.
