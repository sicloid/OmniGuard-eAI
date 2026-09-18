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
ruleset or flushes host/network state. With the production/default runner it also
checks the current `/run/netns/<name>` device/inode against the ownership record
written by `lab/setup_netns.sh`, so deleting and recreating a namespace under the
same `og-b` name is refused rather than silently adopted.

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
flush or conntrack deletion. The dedicated Linux smoke now exercises both established
UDP and established TCP flows: the same live flow must stop under quarantine and resume
after release while conntrack state remains present. It also installs a one-second
kernel lease, lets the userspace command return, and verifies that nftables expires the
element without a controller timer. These are runnable acceptance fixtures; hosted CI
does not execute the privileged netns path and therefore is not G8 evidence.

## KAN-48: deterministic stub state/enforcement E2E

`gateway.controller.StateEnforcementController` composes the already reviewed
boundaries without adding a wire contract: `CheckedDetector` returns a 0.1.0
`DetectionResult`, `DevicePolicy` returns 0.1.0 `StateEvent` values, and the
KAN-31 `NftEnforcer` returns internal kernel receipts.

Detector failure is treated as observation loss and calls `DevicePolicy.invalidate`;
it is never converted to a NORMAL result. QUARANTINED events require a bounded expiry
before the controller calls the enforcer. A QUARANTINED→NORMAL transition performs
an idempotent kernel release. An enforcement error faults the controller because the
policy transition may already have happened while the kernel mutation did not; normal
processing is refused until `reconcile()` restores a known policy/kernel relation.
Reconcile also releases a lingering kernel element discovered after a fresh process
starts. `rearm()` refuses while faulted or while the owned nft set still contains
the device, so a new policy episode cannot silently coexist with a lingering block.

The deterministic unit suite covers N=1/2/3, invalid observations, window gaps, stale
results, detector exhaustion, explicit release, lease expiry, re-arm boundaries,
enforcement-fault latching/recovery and previous-process kernel reconciliation. `lab/stub_state_enforcement_e2e.py` is additionally
executed by the dedicated Linux lab and uses the real `NftEnforcer` against the
owned `og-b` nft set: first anomaly remains SUSPICIOUS, the Nth anomaly installs the
element, and explicit release removes it with kernel readback.

This is a software/state-enforcement integration proof only. It uses
`STUB-NOT-TRAINED` scores and therefore is **not** a G8 or trained-RF result.

## KAN-34: gateway to host Unix-socket bridge

`gateway.event_bridge` implements the gateway half of ADR-0003 section 2.1 without
changing the frozen 0.1.0 contracts. `state_event_document()` serializes exactly
`device_id`, `previous_state`, `new_state`, `reason`, `timestamp` and
`expires_at`; identity/envelope fields remain host-side. The body uses the shared
canonical encoder and the shared four-byte bounded frame.

`GatewayEventBridge.submit()` is a bounded `put_nowait` only. Socket connect/write
runs on its worker; a full queue returns `OVERFLOWED`, a stopped bridge returns
`REFUSED`, and transport exceptions are counted rather than escaping into policy or
enforcement. This preserves the invariant that telemetry loss cannot block quarantine
or release.

The dedicated Linux probe `lab/uds_bridge_smoke.sh` starts a 0600 parent-namespace
UDS, sends a real framed StateEvent from the isolated `og-b` network namespace,
checks Linux peer credentials and verifies before and after that no lab namespace has
a default/outside IP route. It proves the gateway-to-host filesystem/UDS path; it is
not G10 and does not replace the R3 host adapter's own decode/sink tests.
