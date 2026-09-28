# KAN-59 — R1 preparation note (Onur)

This is R1's preparation for the three-person rehearsal, the counterpart of the
note Gabriel supplied. **It is not a record that the rehearsal happened** and it
does not make R1 "ready": the rehearsal script in
[TEAM_QA_REHEARSAL.md](TEAM_QA_REHEARSAL.md) requires each speaker to answer all
six prompts live, without their own role's notes, with two follow-ups from the
others. Prompts 3 and 4 are outside R1's own area on purpose; the answers below
are prepared from the committed evidence, and the gaps R1 expects to be caught
on are stated at the end rather than hidden.

Prepared against `main` at `f16ce7d`, with the suite passing 701 tests
(3 platform skips) and Ruff check/format clean.

## 1. Which bytes and labels trained the frozen RF?

IoT-23, six captures audited before any training, with their Zeek label files.
Labels are **per Zeek connection** in `conn.log.labeled`, not per packet, so a
five-second window inherits a connection-level label — that is a label-resolution
limit, not packet truth, and it is the first thing to say out loud.

The split is **capture-based, not row-based**, at seed 1: train
Honeypot-4-1 + Malware-34-1, validation Honeypot-5-1 + Malware-8-1, test
Honeypot-7-1 + Malware-3-1. No capture appears in two roles, so a window cannot
leak across the split through its own device.

Frozen artifact and policy, all pinned before any scored run:

| Pin | Value |
|---|---|
| Feature schema | `features-1` (14 features) |
| Model | `d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b` |
| Metadata | `917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad` |
| Threshold | `0.9798815486832` |
| N / lease | 2 / 300 s |
| Seed | 1 |

A reproduced threshold or a reproduced metric is **not** an identical
`model.joblib`. Sameness is claimed only when the artifact hash matches; anything
else is "the number came out the same", which is a different statement.

Evidence: `data/DATASET_AUDIT.md`, `docs/KAN19_POLICY.md`,
`model/frozen/kan19-seed1/provenance.json`, `model/leakage_spec.json`.

## 2. What makes a five-second observation eligible for N?

All of the following, and failing any one of them does not produce a benign
score — it breaks the series:

- the window is **complete** and built from the shared feature catalogue
  (`core/features.py`), at the same schema version the model was pinned to;
- kernel timestamp ordering holds behind the watermark (`sources/reorder.py`);
  stale, future, misaligned and duplicate observations are rejected and counted,
  not silently accepted;
- model and schema identity match the pinned artifact; a model change resets the
  anomaly series rather than continuing it;
- a **missing or failed observation resets N**. This is the point most likely to
  be probed: if a failed inference counted as "not anomalous", a broken sensor
  would look like a healthy device. It does not; the consecutive count restarts.

Gaps are counted separately from invalidations and model changes, and the KAN-70
per-device records carry `rejections` and `resets` blocks precisely so this is
auditable after the fact.

Evidence: `core/features.py`, `gateway/pipeline.py`, `sources/reorder.py`,
`gateway/policy.py`, plus the failure test in the suite.

## 3. What actually stops and restores traffic? *(outside R1's area)*

`StateEvent` is **intent**. Effect is established by the nftables receipt and
readback plus an **independent TCP and UDP sink** — both, because a TCP-only
sink would miss the protocol most of this traffic actually uses.

The bounded competition runtime profile uses N = 2 and a finite 300 s lease with
rearm/reconcile. The cited 20 September G8 acceptance run deliberately used a
shorter **N = 1 / 6 s laboratory profile** so apply, kernel expiry and restore
could all be observed in a bounded test; it is not evidence that the N = 2 /
300 s runtime profile itself was exercised end to end. In that G8 run both sinks
received nothing during the blocked interval despite 24 source attempts per
protocol, and deliveries resumed after release. The corresponding SIGKILL run
killed the Python controller after `APPLIED`, and the readback stayed active —
containment is held by the kernel TTL, not by the controller process, so killing
the controller does not silently unblock the device. Both sinks had zero
deliveries against 12 source attempts per protocol there.

The two traps: an empty sink log **when the source sent nothing** proves nothing
and the run is censored; and an `APPLIED` event whose kernel readback or sink log
is missing is incomplete evidence, not containment.

Evidence: `docs/G8_RUNBOOK.md`, the normal and SIGKILL raw logs,
`lab/g8_probe_evidence.py`. Name the tested N/lease profile when showing it.

## 4. What does G10 prove that a green dashboard does not? *(outside R1's area)*

That a real gateway `StateEvent` travelled the whole chain: UDS framing with a
peer check, MQTT transport, PostgreSQL dedup and recovery, and only then Grafana.
A green dashboard can be produced by seeded rows and healthy Compose containers,
which demonstrate the platform and nothing about detection.

The distinction to keep explicit is **policy decision vs kernel application** —
the dashboard shows the former. The peer check is also not uniform: on Linux the
peer is verified, on macOS it is `UNAVAILABLE` because the platform offers no
`SO_PEERCRED`, so the same code reports a weaker guarantee there.

The sealed evidence covers three cases, not just the happy one: `normal`,
`duplicate` and `outage`, with `SHA256SUMS`, the commit and worktree status
recorded alongside.

Evidence: `docs/adr/0003-telemetry-framing.md`, KAN-38/40/41 records,
`docs/evidence/G10_2026-09-24/`.

## 5. Why is the lower-FPR candidate not an automatic winner, and why was it selected?

Because it is better on one axis and worse on another, and the honest statement
includes both.

| | Frozen KAN-19 | ExtraTrees candidate |
|---|---|---|
| CIC benign development FPR (48 devices, 243,559 windows) | 19.55% | **0.957%** |
| CIC benign one-shot holdout FPR (11 devices, 78,834 windows) | 21.97% | — |
| CIC Backdoor EGRESS stress recall | **25.56%** | 6.41% |
| Worst-seed IoT-23 validation recall | — | 99.16% |
| Fresh Pi benign, 328 windows | 75.00% FPR, 10 quarantines, 2,980 s blocked | 0 anomalous, 0 quarantine |

The frozen model **failed** the external benign check — that is the finding, and
it is why a candidate was looked at in the first place. The candidate fixes the
false-alarm side and loses most of what little external recall there was. It was
selected only for the **bounded competition/demo runtime profile**, after
combining Pi, IoT-23, CIC benign, transfer and G8 evidence, not on the FPR number
alone.

The mechanism was already visible before the external data arrived: KAN-21
measured a threshold frozen on one benign capture giving **12.6% and 63.1% FPR**
on another. The 19.55% seen on CIC benign is that same effect at a larger scale,
not a surprise.

Two caveats that must be said unprompted: the Backdoor stress set is
**folder-labelled**, which is not packet-level truth; and the candidate's zero on
the Pi rests on only **0.4556 observed device-hours**, so its rule-of-three upper
bound is still 6.58 false quarantines per observed device-hour. A zero over half
a device-hour is not a zero.

Evidence: `model/runtime_profile.json`, `docs/CICIOT_BENIGN_GENERALIZATION.md`,
`docs/KAN23_CICIOT_TRANSFER.md`, `docs/KAN67_CANDIDATE_MODEL.md`.

## 6. Which results can be claimed at delivery?

Claimable, with hashes: per-window FPR budget, false quarantine counts and benign
blocked time, containment leakage with censor reasons, data role and failed runs,
and the exact run hashes for each.

The results R1 owns, stated as measured:

- **KAN-52 (containment leakage, validation grid).** At the frozen N = 2 /
  lease = 300 s cell: zero false quarantines on the benign capture and 7.5%
  malicious time still leaking, detection delay 10.5 s. The zero at N = 2 is not
  a clean bill — Honeypot-7-1 is fragmented, and the block bootstrap over
  wall-clock time is what exposed that. Two methodology corrections are recorded
  in `model/leakage_spec.json` rather than quietly fixed.
- **KAN-71 (sealed IoT-23 holdout, scored once).** 48-1 Mirai 0.0%, 36-1 Okiru
  0.0%, 20-1 Torii 1.53% window recall, 2 quarantines, 10.5 s delay. Mirai was a
  **seen family** and still produced nothing. Validation 94.5% → seed-1 test
  41.2% → holdout 0/0/1.5%: three evaluations, one direction. The detector does
  not transfer. No untouched-benign FPR follows from that pack, because it holds
  no benign device.
- **KAN-13 (CICIoT2023 audit).** Four benign splits are EGRESS-dominant
  (47.6–50.3%) across 65–68 LAN source MACs, so the benign side is a candidate.
  The selected Mirai split is **98.52% LOCAL / 0.78% EGRESS** and fails the egress
  gate, so it is not used for any gateway-egress attack claim.

Not claimable: a production-IDS claim, any packet-level truth from folder or
connection labels, the earlier Pi ARM64 timing run (invalid), and a full-power
performance claim — the available supply and external 100% fan still prevent it.

Evidence: `docs/KAN52_FPR_LEAKAGE.md`, `docs/KAN71_HOLDOUT_SCORE.md`,
`data/ciciot2023/audit_record.json`, `docs/KAN42_MEASUREMENT.md`,
`docs/KAN66_PI_BENIGN.md`, `docs/REPRODUCE.md`, G13 records.

## Follow-ups R1 should be able to answer cold

The script's five follow-ups, with the one that lands on R1 hardest last:

1. `APPLIED` with no readback or sink log → incomplete evidence, not containment.
2. Source sent nothing during quarantine → the empty sink log says nothing; the
   run is censored/invalid.
3. UDP returning before the controller's release readback → not necessarily
   inconsistent; kernel TTL may expire first. Preserve the signed time difference
   and the separate controller receipt.
4. Pi rebooted between pre/post samples → zero sticky throttle bits validate
   nothing; boot identity changed and the run is invalid.
5. **A poor final holdout score may not be answered by retuning N or the
   threshold against it and still calling the result an untouched holdout.**
   Freeze the predeclared policy, report the number, report the failed and
   censored runs. This is written into `docs/KAN71_HOLDOUT_SCORE.md` as "what
   must not happen next", and the holdout is now spent: any future tuning has to
   be judged on data this project has not read.

## Where R1 expects to be caught

Stated in advance so the rehearsal can use the time on them:

- **Prompt 3's lease/rearm mechanics** and **prompt 4's MQTT/PostgreSQL dedup
  path** are read from the evidence, not operated first-hand. Expect the
  follow-ups here to go deeper than this note.
- **Why 0.5 is not the operating threshold.** 0.5 is a default of the
  classifier's probability output, not a decision. The operating point was chosen
  against a **1% window-FPR budget approved by the Lead on 14 September**, out of
  143 candidates, which is what `0.9798815486832` encodes. The budgeted threshold
  is also not stable across splits — it comes out 0.98, 0.995 and **0.41** on the
  three seeds — so the specific value is a property of the split, not of the
  malware. If no candidate had met the budget, the run would have recorded that
  and written no threshold.
- **Whether KAN-19 should have been replaced sooner.** The defensible answer is
  that the freeze is what makes the three-evaluation trend readable at all; an
  unfrozen model would have made the failure unmeasurable rather than absent.
