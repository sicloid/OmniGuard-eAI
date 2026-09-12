# Development status — 2026-09-12

PRs #4–#15 are merged after review, targeted corrections and verification.
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

Final combined runtime suite: **133 tests, no skips**, Python 3.14.7; Ruff lint and
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
| KAN-28 | İncelemede | PR #18 has packet-driven integration; safe idle progress, stale/gap handoff and lifecycle health tests remain; no team review yet |
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
3. R3: KAN-38 UDS/framing ADR; build 0.1.0 DB/consumer/dashboard first with
   migrations, provisioning, dedup/recovery and explicit decision semantics.
4. G5/G8: real audited model and independent sink stop/restore, including faults
   and benign service impact. Synthetic RF tests are not research results.
5. G10: StateEvent → UDS → MQTT → PostgreSQL → Grafana with outage/recovery and
   completeness evidence. Healthy services alone are not this gate.
6. Linux ARM64/Pi, experiments, results freeze and final reproducible demo.

**G5/G8/G10 are not passed.** Earlier [Linux](LINUX_VALIDATION.md),
[live](LIVE_VALIDATION.md), [replay](REPLAY_VALIDATION.md) and
[Windows](WEEK_ONE_R2.md) records remain dated historical evidence.
