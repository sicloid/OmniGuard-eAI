# KAN-19 operating threshold policy — 14 September 2026

Owner: R1 (Onur). Reproduce with:

```sh
python -m model.policy_run --pack ~/omniguard-data/samplepack/windows.jsonl \
    --out ~/omniguard-data/runs/kan19
```

**The run was specified before it ran.** [`model/operating_policy_spec.json`](../model/operating_policy_spec.json)
was committed in `b436195` before any calibration on real data. It fixes:

- the window-FPR budget, 1 %, approved by the Lead on 14 September 2026;
- the objective, `max_recall_at_fpr`, selected on validation only;
- `features-1`, the development pack hash and 200 trees;
- seed 1 as the only operating candidate, with seeds 2 and 3 reported for sensitivity.

If no threshold had met the budget, the run would have recorded that and written no
artifact. Spec SHA-256: `867b81f796cfcf72130c401eb582daa31c13115a44716813cf04de375e72315f`.

Nothing here reads the development test split, the ADR-0004 holdout or any KAN-21 fold
result.

## Frozen operating policy (seed 1)

| | |
|---|---|
| Status | `operating_policy_frozen` |
| Train split | Honeypot-4-1, Malware-34-1 |
| Validation split | Honeypot-5-1, Malware-8-1 |
| Threshold | **0.9798815486832** (143 candidates) |
| Validation recall | 0.9453 (8,211 of 8,686 malicious windows) |
| Validation window FPR | 0.0068 (14 of 2,055 benign windows) |
| Validation precision | 0.9983 |
| Capture-bootstrap FPR interval | 0.0000 – 0.0137 |
| Same model at the 0.5 reference | recall 0.9995, FPR 0.4000 |

Hashes:

- Pack `windows_sha256`: `4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625`
- Pack `manifest_sha256`: `65c7184c3cb8602105684f80b415e4fd17e4e5bdab5ce1813aa5af9f9bdbdfb0`
- `training_manifest_sha256`: `b4abc85f8a2d5f00be0789327d2a76e331399396a50c9dcbd289ff222f56be67`
- `model_sha256`: `d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b`. This is byte-identical
  to the KAN-18 seed-1 model: same data, same seed.
- `model.meta.json` SHA-256: `917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad`
- `threshold.policy.json` SHA-256: `4a9491b5ce0be6a5225ce8f0e0b4d72022e67a62ba38c6cf62aeb051acc7bcdb`

The frozen text files are committed in [`model/frozen/kan19-seed1/`](../model/frozen/kan19-seed1/):
`threshold.policy.json`, `model.meta.json`, `provenance.json` and `split.manifest.json`.
`model.joblib` is a binary, so it stays outside Git and is pinned by `model_sha256`.

`load_model` accepted the artifact with those hashes as trusted pins. The metadata
threshold equals the policy threshold, and `read_policy` reproduces the policy hash.

## Sensitivity seeds (never the operating policy)

| Seed | Validation | Threshold | Recall | Window FPR | False positives / benign windows | FPR at 0.5 |
|---|---|---|---|---|---|---|
| 2 | Honeypot-5-1, Malware-3-1 | 0.995 | 0.2652 | 0.0098 | 10 / 1,023 | 0.8035 |
| 3 | Honeypot-7-1, Malware-3-1 | 0.41 | 0.8583 | 0.0064 | 63 / 9,774 | 0.0001 |

## What this shows

1. **KAN-19's acceptance criterion is met.** The threshold was selected on validation only,
   under a recorded Lead-approved budget. The policy and its hash are frozen before any
   test or holdout is scored.
2. **It is not a deployment FPR.** The validation benign side has 2,055 windows from two
   devices: 1,019 from benign Honeypot-5-1, and 1,036 benign windows inside the infected
   8-1 capture. The capture-bootstrap interval's upper bound, 1.37 %, is already above the
   budget. KAN-21 showed that a threshold frozen on one benign capture gave 12.6 % and
   63.1 % FPR on another. Nothing here says how this threshold behaves on an unseen
   benign device.
3. **The budgeted threshold is not stable across splits.** It is 0.98, 0.995 and 0.41 for
   the three seeds, with recall 0.95, 0.27 and 0.86.
   - Seed 2 shows the same 1 % budget can cost almost three quarters of recall when the
     validation malware is Muhstik.
   - This is why the operating seed was fixed in advance rather than picked from these
     results.
4. **The objective spends the budget.** With seed 3, moving from 0.5 to the budgeted 0.41
   raises false positives from 1 to 63 for 20 more true positives.
   `max_recall_at_fpr` maximises recall up to the limit, and that is what it did. The
   objective is fixed in the spec, so it is reported here, not changed.
5. **Declared label.** Seed 3 validates on Honeypot-7-1, whose benign label is declared,
   not measured (ADR-0004 decision 4). The operating seed does not use 7-1 for
   validation, and 7-1 sits in its unread test split.

## What comes next

ADR-0004 decision 7b allows the holdout to be scored only after these are recorded:
`feature_schema_version`, `model_sha256`, the metadata hash, the threshold policy hash,
N/lease, and the development pack hash.

- **Recorded here:** everything except N/lease.
- **Still missing:** N and lease belong to the policy work (KAN-30, PR #25) and KAN-51.
- **Until N/lease are recorded:** the holdout stays unscored.

This policy is unaffected by PR #29 (live on-link EGRESS alignment). The development
pack's windows are byte-identical under that change.
