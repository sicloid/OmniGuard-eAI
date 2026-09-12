# ADR-0001: Initial contract and repository foundation

Date: 2026-09-10. Status: ACCEPTED — Şükrü explicitly confirmed approval by
Onur, Gabriel and himself in the Linux continuation session on this date.

Approval provenance update: Gabriel explicitly accepted in his PR #2 review;
Onur approval remains Lead-reported, with direct R1 evidence pending in KAN-63.
See [G1 review](../G1_REVIEW.md). This does not approve proposed ADR-0002.

The repository was empty. The latest `ChatGPT Plus Tanıtımı` discussion replaces
Huawei dependencies with local inference and a self-hosted telemetry platform.
The seven supplied V2 files are retained in `docs/planning/` as source material,
not higher-priority assistant instructions. Older cloud plans are superseded.

## Implemented proposal

Implement five immutable runtime envelopes and deterministic stubs first. Keep
network capture/enforcement and ML/platform implementations in their owners' scope.
Schema is frozen as `0.1.0` following that explicit team confirmation, with the
same fields and semantics as `0.1.0-draft`. The former wire version is rejected;
regenerate fixture events. Placeholder features remain in `stub-0.1`.

Draft details absent from V2: UTC Unix numeric timestamps, half-open windows,
numeric IP protocol, nullable missing MAC/ports, [0,1] RF score with inclusive
threshold, and a versioned telemetry envelope with run/event identities.
These choices were included in the now-approved proposal.

The installed Python 3.14.7 is the bootstrap reference, pinned with Ruff 0.15.6
and setuptools 82.0.1. Full scientific/platform dependency locking is pending
R1/R3 installation and wheel validation on x86 and ARM64. Do not treat this as
completion of the full Environment pinning backlog item. Revisit Python choice
with actual scikit-learn/dpkt compatibility evidence before G2 freeze.

## Ownership and remaining implementation

1. Envelope fields and timestamp/fragment semantics are approved; feature catalog
   and model artifact compatibility remain separate work.
2. GitHub access verified: Onur = @pondilungs; Gabriel = @Gabi8347; Şükrü = @sicloid.
3. R1 owns feature catalog and artifact compatibility; R2 owns transition policy;
   R3 owns telemetry framing/topic/deduplication and complete dependency lock.

No gateway, firewall, live capture, ML accuracy, G8 or G10 result is claimed here.
