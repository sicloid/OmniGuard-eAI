# Team Q&A rehearsal (KAN-59 preparation)

This is a script for the three-person rehearsal, not a record that it happened.
Close KAN-59 only after Şükrü, Onur and Gabriel each explain every boundary below
without relying on their own role's notes, and record the date, participants,
open questions and the exact Git/run evidence reviewed in Jira.

## Ten-minute round for each speaker

Rotate speakers so each person answers all six prompts; the other two ask one
follow-up each. Point to the relevant code and raw run evidence, not only a slide.

| Prompt | Answer must include | Evidence to show |
|---|---|---|
| Which bytes and labels trained the frozen RF? | IoT-23 audit, versioned label rule, capture-based split, development/holdout separation, artifact and policy hashes. A reproduced threshold or metric is not an identical `model.joblib`. | `data/DATASET_AUDIT.md`, `docs/KAN19_POLICY.md`, `model/frozen/kan19-seed1/provenance.json`, exact external artifact hash. |
| What makes a five-second observation eligible for N? | Shared feature catalogue, kernel timestamp ordering/watermark, complete window, model/schema identity, stale/missing observation breaking the anomaly series. A failed observation is not a benign score. | `core/features.py`, `gateway/pipeline.py`, `sources/reorder.py`, `gateway/policy.py` and a failure test. |
| What actually stops and restores traffic? | StateEvent is intent; nftables receipt/readback and an independent TCP **and** UDP sink establish effect. Explain finite lease, rearm/reconcile, SIGKILL with kernel TTL, local service continuity and source attempts during the blocked interval. | `docs/G8_RUNBOOK.md`, PR #41 normal and SIGKILL raw logs, `lab/g8_probe_evidence.py`. Name the tested N/lease profile. |
| What does G10 prove that a green dashboard does not? | Real gateway StateEvent through UDS framing and peer check, MQTT transport, PostgreSQL dedup/recovery, then Grafana. Distinguish policy decision from kernel application; show gaps, duplicates and outage outcome. Seeded dashboard rows and Compose health are only platform demonstrations. | `docs/adr/0003-telemetry-framing.md`, KAN-38/40/41 records and `docs/evidence/G10_2026-09-24/` normal/duplicate/outage evidence. |
| Why is the lower-FPR candidate not an automatic winner, and why was it selected? | KAN-19 failed external CIC benign generalization at 19.55% development and 21.97% holdout FPR. The candidate reduced development FPR to 0.957% and produced zero anomalous windows on the fresh Pi run, but CIC Backdoor EGRESS stress recall fell to 6.41% versus KAN-19's 25.56%. It was selected only for the bounded competition/demo profile after combining Pi, IoT-23, CIC benign, transfer and G8 evidence. The folder label is not packet-level truth and the result is not a production-IDS claim. | `model/runtime_profile.json`, `docs/CICIOT_BENIGN_GENERALIZATION.md`, `docs/KAN23_CICIOT_TRANSFER.md`, `docs/KAN67_CANDIDATE_MODEL.md`, exact evidence JSON and model hashes. |
| Which results can be claimed at delivery? | Per-window FPR budget, false quarantine and benign blocked time, leakage with censor reasons, data role and failed runs, exact run hashes. The earlier Pi ARM64 timing run remains invalid. The accepted fresh one-hour Pi run proves functional/fresh-benign behavior: KAN-19 had 75% FPR, ten quarantines and 2,980 blocked seconds; the candidate had zero in 328 windows, with a 6.58/device-hour rule-of-three upper bound. The available supply and external 100% fan still prevent a full-power performance claim. | `docs/KAN42_MEASUREMENT.md`, `docs/KAN66_PI_BENIGN.md`, `docs/evidence/KAN66_PI_2026-09-28/`, `docs/REPRODUCE.md`, `docs/DEMO_RUNBOOK.md`, KAN-52 and G13 records. |

## Follow-ups to ask every speaker

1. If an `APPLIED` StateEvent appears but the kernel readback or sink log is
   missing, what is the gate result? Answer: incomplete evidence, not containment.
2. If a source sends nothing during the quarantine interval, what does an empty
   sink log mean? Answer: nothing about enforcement; the run is censored/invalid.
3. If UDP returns before the controller's release readback, is the measurement
   necessarily inconsistent? Answer: no. Kernel TTL may expire first. Preserve
   the signed time difference and the separate controller receipt.
4. If the Pi reboots between pre/post samples, can zero sticky throttle bits
   validate that measurement? Answer: no; boot identity changed and the run is
   invalid.
5. If a final holdout score is poor, can N/threshold be retuned against it and
   still be reported as the untouched holdout result? Answer: no; freeze the
   predeclared policy and report the result and any failed/censored runs.

## Rehearsal record to fill after the meeting

Gabriel supplied a preparation note covering all six prompts, evidence paths,
follow-up questions and his G10/measurement area. It has been reviewed against
the final Pi and runtime-profile result; those two answers above supersede the
preparation note's earlier pending/invalid-only wording. This confirms Gabriel's
prepared material exists, but it does not by itself prove the live three-person
rehearsal happened.

| Field | Record |
|---|---|
| Date, participants and reviewer | Pending actual team rehearsal |
| Git commit and run IDs shown | Pending |
| Each speaker's six prompts + follow-ups | Pending; record gaps by speaker |
| Open corrections, owner and due date | Pending |
| Jira comment and final owner review | Pending |

The lead should not mark a speaker as ready from this document alone. If G8,
G10, G13 or Pi gates remain open, speakers must say so during the rehearsal and
use the [demo runbook](DEMO_RUNBOOK.md) partial-prototype path.
