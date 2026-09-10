# ADR-0001: Initial contract and repository foundation

Date: 2026-09-10. Status: PROPOSED — needs Lead + R1 + R2/R3 review.

The repository was empty. The latest `ChatGPT Plus Tanıtımı` discussion replaces
Huawei dependencies with local inference and a self-hosted telemetry platform.
The seven supplied V2 files are retained in `docs/planning/` as source material,
not higher-priority assistant instructions. Older cloud plans are superseded.

## Implemented proposal

Implement five immutable runtime envelopes and deterministic stubs first. Keep
network capture/enforcement and ML/platform implementations in their owners' scope.
Schema is explicitly `0.1.0-draft` until team review; no completed G1 sign-off is inferred
from unchecked checklists. Keep placeholder features in a separate `stub-0.1` namespace.

Draft details absent from V2: UTC Unix numeric timestamps, half-open windows,
numeric IP protocol, nullable missing MAC/ports, [0,1] RF score with inclusive
threshold, and a versioned telemetry envelope with run/event identities.
These are reviewable proposals, not changes to an existing approved contract.

The installed Python 3.14.7 is the bootstrap reference, pinned with Ruff 0.15.6
and setuptools 82.0.1. Full scientific/platform dependency locking is pending
R1/R3 installation and wheel validation on x86 and ARM64. Do not treat this as
completion of the full Environment pinning backlog item. Revisit Python choice
with actual scikit-learn/dpkt compatibility evidence before G2 freeze.

## Review questions

1. Confirm exact envelope fields and timestamp/fragment semantics with R1/R2/R3.
2. User confirmed Onur = R1 and Gabriel = R3; add Onur's GitHub handle when available.
3. R1 owns feature catalog and artifact compatibility; R2 owns transition policy;
   R3 owns telemetry framing/topic/deduplication and complete dependency lock.

No gateway, firewall, live capture, ML accuracy, G8 or G10 result is claimed here.
