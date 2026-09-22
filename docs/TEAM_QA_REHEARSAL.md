# Team Q&A rehearsal (KAN-59 preparation)

This is a script for the three-person rehearsal, not a record that it happened.
Close KAN-59 only after Şükrü, Onur and Gabriel each explain every boundary below
without relying on their own role's notes, and record the date, participants,
open questions and the exact Git/run evidence reviewed in Jira.

## Ten-minute round for each speaker

Rotate speakers so each person answers all five prompts; the other two ask one
follow-up each. Point to the relevant code and raw run evidence, not only a slide.

| Prompt | Answer must include | Evidence to show |
|---|---|---|
| Which bytes and labels trained the frozen RF? | IoT-23 audit, versioned label rule, capture-based split, development/holdout separation, artifact and policy hashes. A reproduced threshold or metric is not an identical `model.joblib`. | `data/DATASET_AUDIT.md`, `docs/KAN19_POLICY.md`, `model/frozen/kan19-seed1/provenance.json`, exact external artifact hash. |
| What makes a five-second observation eligible for N? | Shared feature catalogue, kernel timestamp ordering/watermark, complete window, model/schema identity, stale/missing observation breaking the anomaly series. A failed observation is not a benign score. | `core/features.py`, `gateway/pipeline.py`, `sources/reorder.py`, `gateway/policy.py` and a failure test. |
| What actually stops and restores traffic? | StateEvent is intent; nftables receipt/readback and an independent TCP **and** UDP sink establish effect. Explain finite lease, rearm/reconcile, SIGKILL with kernel TTL, local service continuity and source attempts during the blocked interval. | `docs/G8_RUNBOOK.md`, PR #41 normal and SIGKILL raw logs, `lab/g8_probe_evidence.py`. Name the tested N/lease profile. |
| What does G10 prove that a green dashboard does not? | Real gateway StateEvent through UDS framing and peer check, MQTT transport, PostgreSQL dedup/recovery, then Grafana. Distinguish policy decision from kernel application; show gaps, duplicates and outage outcome. Seeded dashboard rows and Compose health are only platform demonstrations. | `docs/adr/0003-telemetry-framing.md`, KAN-38/40/41 records, and the accepted KAN-50 real-event run **when available**. |
| Which results can be claimed at delivery? | Per-window FPR budget, false quarantine and benign blocked time, leakage with censor reasons, data role and failed runs, exact run hashes. The Pi ARM64 lab passed functionally but its timing was invalidated by pre-run load; external fan cooling does not turn it into a performance result. Distinguish V3 proposals from implemented behavior. | `docs/KAN42_MEASUREMENT.md`, `docs/REPRODUCE.md`, `docs/DEMO_RUNBOOK.md`, `docs/evidence/PI5_2026-09-22_constrained/`, KAN-52/54 accepted records **when available**. |

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

| Field | Record |
|---|---|
| Date, participants and reviewer | Pending actual team rehearsal |
| Git commit and run IDs shown | Pending |
| Each speaker's five prompts + follow-ups | Pending; record gaps by speaker |
| Open corrections, owner and due date | Pending |
| Jira comment and final owner review | Pending |

The lead should not mark a speaker as ready from this document alone. If G8,
G10, G13 or Pi gates remain open, speakers must say so during the rehearsal and
use the [demo runbook](DEMO_RUNBOOK.md) partial-prototype path.
