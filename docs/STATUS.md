# Development status — 2026-09-12

## 22 September 2026 update

PRs #43 and #44 are merged. The Lead froze validation policy N = 2 / lease =
300 s from the corrected KAN-51 grid; PR #46 recorded the decision in ADR-0004
and merged. This is not a final holdout score. KAN-44 private Tailscale
management and KAN-46's load/throttling guard behavior are accepted. A real
Pi 5 ARM64 Docker lab run passed its network, UDS and cleanup checks, while
the guard correctly marked its timing invalid for high pre-run load; the
[raw samples and log](evidence/PI5_2026-09-22_constrained/README.md) are retained.
The owner is proceeding with the available power setup, so no 27 W PSU is a
gate. G10 correlation/completeness, KAN-52 headline experiment, G13 freeze,
three-person Q&A rehearsal and release remain open. KAN-55 and KAN-58 have
review candidates; KAN-53 is a bounded functional result awaiting review and
its G10 prerequisite. The dated history below must not be read as current
Jira or PR state.

## 20 September 2026 status update

The dated history below is retained as a record of earlier review states. The
real-model G8 Linux sink/kernel evidence received independent approval on the
exact head, and PR #41 merged; KAN-49 and the Pi-free laptop demo KAN-35 are
complete at that bounded development-validation scope. G10 correlation and
completeness, the policy/holdout experiments, actual Pi 5 measurements, G13
results freeze and final release remain open. Do not read the older G8 status
or test counts below as the current gate decision.

PRs #4–#15, #19 and #20 are merged after review and verification. PR #18
remains a review candidate; #21 is blocked by uncommitted sample-pack source files.
G1 is approved; Onur's direct PR #4 acceptance is in [G1_REVIEW](G1_REVIEW.md).
The five runtime contracts remain `0.1.0`. ADR-0002 remains **PROPOSED** until
KAN-38's concrete framing/topic/envelope decisions are reviewed.

## Implemented and verified

- PCAP/live normalization, loss rejection and bounded per-device windows connected
  to the shared pure extractor.
- Checked model-independent detector boundary; no inference failure becomes NORMAL.
- Pure 14-feature EGRESS extractor and deterministic parent-group split machinery.
- Artifact loading checks both model and metadata pins before deserialization;
  RF/rate-rule training, grouped metrics and validation-only threshold policy code.
- Prepared-PCAP replay with per-run evidence and separate reference/monotonic times.
- Windows binary secret writes; healthy Mosquitto/PostgreSQL/Grafana services.
- Core/ML hash locks including pip and macOS; project Python upgraded to 3.14.7.

Combined PR #18 candidate suite: **224 tests, two platform-absence skips**,
Python 3.14.7; Ruff lint and
format pass. Hosted Linux/Windows/macOS and platform checks passed on reviewed
heads. Real Linux capture/replay and service smoke passed again. Details:
[review closeout](REVIEW_CLOSEOUT_2026-09-12.md). The KAN-28 integration evidence
is recorded in [KAN-28 validation](KAN28_VALIDATION.md).

## Jira completion versus implementation

| Card | State after review | Reason / remaining acceptance |
|---|---|---|
| KAN-10 | Tamamlandı | Current core/ML locks and clean installs verified across team platforms |
| KAN-27 | Tamamlandı | Shared tuple/live loss checks; real pre-drop capture/overflow evidence |
| KAN-29 | Tamamlandı | Checked detector interface and failure semantics verified |
| KAN-32 | Tamamlandı | Prepared replay/run identity/t0/independent sink evidence verified |
| KAN-9 | İncelemede | Component merged; catalogue/artifact freeze and remaining compatibility work |
| KAN-15/16 | İncelemede | Catalogue audit/freeze and actual capture-health-window-feature parity |
| KAN-17 | İncelemede | Real sample-pack parent identity and disjointness evidence |
| KAN-18/19 | İncelemede | Real audited data/model/metrics, agreed validation budget and policy freeze |
| KAN-28 | İncelemede | PR #18 now includes guarded idle progress, stale/gap diagnostics and lifecycle tests; idle-only Docker and loss propagation passed; team review pending |
| KAN-13 | İncelemede | Audit component PR #20 merged; primary-dataset change remains explicitly unapproved |
| KAN-14 | İncelemede | PR #21 lacks builder/labels/runner source; ignore rule fixed, owner must push files |
| KAN-38 | İncelemede | PR #19 merged; real MQTT PUBACK/subscriber/retry passed; remaining ADR-0003 team review is not assumed |
| KAN-63 | Tamamlandı | R1/R3 design review accepted; requested fixes merged. Concrete wire work remains in KAN-38 |

PR merge is not evidence that these missing data or integration criteria passed.
Owners/dates are unchanged. KAN-13/14/20/38/39/40/41/42/43 now carry the review
follow-ups described in [the resolution record](architecture/REVIEW_RESOLUTION_2026-09-12.md).

## Next work

1. R1: audit available PCAP direction/labels/provenance; resolve the dataset ADR
   before training if the candidate attacks are LOCAL rather than EGRESS.
2. R2: finish KAN-28 safe idle progress, stale/gap handoff and lifecycle loss
   propagation, then connect the real model and implement KAN-30 N policy,
   bounded enforcement, restart/release and leakage measurements.
3. R3: finish ADR-0003 team review; build 0.1.0 DB/consumer/dashboard first with
   migrations, provisioning, dedup/recovery and explicit decision semantics.
4. G5/G8: real audited model and independent sink stop/restore, including faults
   and benign service impact. Synthetic RF tests are not research results.
5. G10: StateEvent → UDS → MQTT → PostgreSQL → Grafana with outage/recovery and
   completeness evidence. Healthy services alone are not this gate.
6. Linux ARM64/Pi, experiments, results freeze and final reproducible demo.

**G5/G8/G10 are not passed.** Earlier [Linux](LINUX_VALIDATION.md),
[live](LIVE_VALIDATION.md), [replay](REPLAY_VALIDATION.md) and
[Windows](WEEK_ONE_R2.md) records remain dated historical evidence.

Main at 446b240 passed 212 tests with two platform-absence skips. PR #19's real
broker evidence is in [KAN38_MQTT_VALIDATION](KAN38_MQTT_VALIDATION.md). The
IoT-23 primary-source recommendation was explicitly left unapproved by Şükrü;
merging the audit is not a dataset switch. No actual RF/result freeze is claimed.

## 14 September 2026 — current correction and KAN-30 candidate

The historical tables above describe earlier review states. PRs #18–24 have now
merged. KAN-9/14/17/18/28/38 are completed at their component scope. The sample-pack
sources and first real negative baseline are present; G5/G8/G10 remain unpassed.
IoT-23 primary-source and shared direction semantics remain proposals/follow-ups.
KAN-39 uses the 0.1.0 initial migration including run_id; boot/ordering additions
belong to KAN-40's additive 002 migration.

KAN-30 now has a review candidate in `gateway/policy.py`: configurable N,
invalid/gap reset, independent monotonic expiry and explicit episode rearm using
existing StateEvent. See gateway/README.md for call obligations. This does not
complete live scheduling or kernel enforcement, and is not yet merged/deployed.
