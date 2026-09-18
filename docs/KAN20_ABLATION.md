# KAN-20 feature ablation and per-window cost — 17 September 2026

Owner: R1 (Onur). Reproduce with:

```sh
python -m model.ablation_run --pack ~/omniguard-data/samplepack-v2-20260915T111555Z/windows.jsonl \
    --captures ~/omniguard-data/iot23 --out ~/omniguard-data/runs/kan20
```

**The run was specified before it ran.** [`model/ablation_spec.json`](../model/ablation_spec.json)
and the runner were committed in `155043a` before any ablation on real data. The spec fixes:

- the candidate sets;
- the KAN-19 window-FPR budget (1 %) and objective, selected on validation only;
- seeds 1–3, 200 trees and 300 capture-bootstrap resamples;
- the compact-set rule and its tolerance;
- the timing sample.

Spec SHA-256: `db85c38dc28d38eeef0c802fab1c1bbd660dd864c97cd22a0b2613121ad11e8d`.

**Scope of the evidence.**
- **Splits:** every detection number is on each seed's **validation** split. The test split is
  never scored and the ADR-0004 holdout is never read.
- **Optimism:** validation both selects each set's threshold and scores it, so all recalls are
  optimistic in the same way. Compare sets against each other, not against a deployment claim.
- **Timings:** from a development Mac (arm64, Python 3.14.7, scikit-learn 1.8.0). They rank sets
  against each other and are not gateway numbers. The gateway figures belong to KAN-42 on the
  finalists.

## What was compared

The four catalogue groups from [`data/FEATURE_CATALOG.md`](../data/FEATURE_CATALOG.md):

| Group | Columns |
|---|---|
| volume | `pkt_count`, `l3_bytes_sum`, `l3_bytes_mean`, `l3_bytes_std` |
| destinations | `uniq_dst_ip`, `uniq_dst_port`, `max_dst_ip_share` |
| protocol | `tcp_share`, `udp_share`, `icmp_share` |
| connection | `syn_only_share`, `rst_share`, `portless_share`, `active_span_s` |

The runner evaluated 29 sets:

| Kind | Sets | Role |
|---|---:|---|
| Full catalogue | 1 | reference |
| Each group alone | 4 | compact candidate |
| Every pair of groups | 6 | compact candidate |
| Every group removed | 4 | compact candidate |
| Each single feature dropped | 14 | diagnostic only |

The single-feature drops are never compact candidates. Removing one column inside a group saves
almost no work, because the rest of the group still runs.

**Compact rule (R1 proposal; the 0.02 tolerance needs Lead review).** A candidate qualifies only if
it meets both conditions on every seed:
1. It calibrates under the budget.
2. Its validation recall at the budget is at least the full set's recall minus 0.02.

The qualifier with the fewest features wins. Timings never choose.

**Cost.** Three measurements for every set, plus one reference:
- **Group-arithmetic time:** the four groups' arithmetic, split out of the runtime extractor. A
  test pins that the split reproduces `extract_features`'s values exactly. It does **not** include
  the extractor's epoch-alignment check or its per-packet validation loop, which every set pays
  alike. Use it to rank sets, not as the extractor's per-window cost.
- **Full-extractor reference:** `core.features.extract_features` itself, timed once per run. This
  is the number to compare with gateway measurements.
- Both are timed over 4,000 real packet windows from 4-1 and 34-1, the seed-1 train captures.
  Only packets are used, no labels.
- **Inference latency:** one `predict_proba` call per window, as the live detector makes it.
- **Model size:** the seed-1 model's forest size.

## Result

**Status: `selected`. Compact finalist: `without:protocol` (11 features).**

The full set on seed 1 reproduces the frozen KAN-19 threshold exactly (`0.9798815486832`).

| Set | n | Val recall @1 % FPR (seed 1 / 2 / 3) | Val AP (1 / 2 / 3) | Group arithmetic µs/window | Inference ms (median) | Tree nodes |
|---|---:|---|---|---:|---:|---:|
| full | 14 | 0.945 / 0.265 / 0.858 | 0.998 / 0.995 / 0.997 | 4.62 | 4.29 | 22,424 |
| **without:protocol** | 11 | 0.949 / 0.272 / 0.907 | 0.998 / 0.996 / 0.997 | 3.52 | 4.34 | 23,260 |
| without:destinations | 11 | 0.376 / — / 0.926 | 0.991 / 0.997 / 0.999 | 3.54 | 4.34 | 20,388 |
| without:connection | 10 | — / — / 0.855 | 0.986 / 0.977 / 0.996 | 3.46 | 4.33 | 15,452 |
| without:volume | 10 | — / — / — | 0.978 / 0.976 / 0.862 | 3.70 | 4.35 | 50,614 |
| pair:volume+connection | 8 | 0.377 / — / 0.926 | 0.995 / 0.997 / 0.998 | 2.33 | 4.52 | 23,334 |
| pair:volume+protocol | 7 | — / — / 0.900 | 0.972 / 0.992 / 0.996 | 2.26 | 4.45 | 14,818 |
| pair:destinations+protocol | 6 | 0.121 / 0.013 / 0.011 | 0.909 / 0.943 / 0.617 | 2.65 | 4.44 | 6,164 |
| only:volume | 4 | — / — / 0.906 | 0.977 / 0.992 / 0.992 | 1.02 | 4.28 | 14,344 |
| only:connection | 4 | — / — / — | 0.981 / 0.994 / 0.985 | 1.30 | 4.27 | 55,778 |
| only:destinations | 3 | 0.020 / — / 0.108 | 0.830 / 0.957 / 0.676 | 1.33 | 4.25 | 8,672 |
| only:protocol | 3 | — / — / 0.025 | 0.897 / 0.961 / 0.731 | 1.29 | 4.25 | 2,952 |

**Full-extractor reference:** `core.features.extract_features` costs **7.36 µs per window** on the
same 4,000 windows. Every group-arithmetic figure above is smaller than the extractor's own cost,
because the validation and packet loop that all sets pay alike are outside the timed path.

In the table:
- **"—"** means no threshold met the 1 % budget on that seed. The budget was not relaxed.
- **Pairs not shown** (`volume+destinations`, `destinations+connection`, `protocol+connection`)
  fail the rule on every seed. `pair:destinations+protocol` is listed because it calibrates on all
  three seeds while detecting almost nothing, which is the point made in §1.

Validation splits by seed:

| Seed | Validation captures | Benign windows | Note |
|---|---|---:|---|
| 1 | 5-1, 8-1 | 2,055 | |
| 2 | 5-1, 3-1 | 1,023 | At most 10 false-positive windows fit the budget. |
| 3 | 7-1, 3-1 | 9,774 | 7-1's label is declared, not measured. |

**Full record:** [`model/frozen/kan20/ablation_report.json`](../model/frozen/kan20/ablation_report.json)
holds, for every set and seed, the policies, bootstrap intervals, false-positive counts, verdicts
and costs.

| Artifact | SHA-256 |
|---|---|
| Committed report (home paths replaced by `~`) | `4c85add98f2af26fe38e9dbae69b7bc8b32977e13384b3ae19277b3246ca6d87` |
| Original run output | `7d7bef0cd24d0edd3e1a39d6687e099634e563c8eda54619b042cb5980369a1a` |

The pack is manifest v2 `8ea8c310…` (`label_rule_version` `window-label-1`); its windows
`4b97fb95…` are the same as in KAN-18/19.

## What this says

1. **Volume features carry the detection, and the exact claim matters.**
   - `without:volume`, the ten non-volume features together, finds no threshold under the budget
     on any seed.
   - Volume-free sets are not all uncalibratable, though: `pair:destinations+protocol` calibrates
     on all three seeds, `only:destinations` on seeds 1 and 3, `only:protocol` on seed 3. What
     they cannot do is detect: their recall at the budget is 0.011–0.121.
   - So the supported statement is "no volume-free set reaches useful recall, and the full
     volume-free set cannot even be calibrated", not "without volume nothing calibrates".
   - The gap between those two is itself a result: a 6-feature set calibrates on every seed while
     its 10-feature superset calibrates on none. Adding the connection group removes the ability
     to calibrate at all, which is the §3 cliff appearing in the group results.
   - Alone, volume and connection both rank well (AP ≥ 0.977). Destinations or protocol alone are
     weak (AP 0.68–0.96).
2. **Protocol mix adds nothing measurable here.**
   - Removing `tcp_share`, `udp_share` and `icmp_share` keeps both recall at the budget and AP
     on every seed.
   - It is the only candidate that passes the rule.
   - This is a dev-pack observation: six captures, one malware family per validation split. It
     is not a general claim.
3. **Recall at a 1 % budget sits on a cliff.**
   - AP stays at 0.99 or above for most sets. Yet on seed 1, seven of the fourteen single-feature
     drops take recall at the budget from 0.945 to about 0.33, and one finds no threshold at all.
   - Cause: the 200-tree forest's scores are coarse near the top, in steps of about 0.005.
     Once more than about 20 benign windows share the top score levels, the threshold jumps to
     0.995 or 1.0.
   - The rule's verdicts are therefore sensitive to small changes, and the finalist is tentative.
   - The same effect gives seed 2 its 0.265 recall, with only 10 false positives of room. It
     matches the KAN-19 sensitivity result (thresholds 0.41–0.995 across seeds).
4. **Feature count is not the cost lever.**
   - The full extractor costs 7.36 µs per window; the group arithmetic inside it, 1.0–4.6 µs
     depending on the set.
   - A single `predict_proba` costs about 4.3 ms for every set: roughly six hundred times the
     whole extractor, dominated by the call overhead of 200 trees.
   - Dropping the protocol group saves about 1.1 µs of group arithmetic per window, which is
     about 15 % of the extractor's cost and changes neither inference time nor model size
     meaningfully.

## Recommendation (for Lead review)

- **Runtime catalogue:** keep `features-1`. A `features-2` without the protocol group would need a
  contract change and a new pack, and it saves too little to justify either.
- **KAN-51's "two feature sets × N" matrix:** if a second set is still wanted, use `full` and
  `without:protocol`. Because the saving is small, forest size may be the better second axis.
- **Forest size:** inference latency is dominated by `n_estimators` and per-call overhead, so the
  follow-up below measures forest size and batching. Feature pruning would not move gateway
  latency.
- **Decision needed from the Lead:** the 0.02 tolerance. The rule and every verdict are recorded,
  so a different tolerance can be checked against the report without re-running.

## Follow-up: forest size — 17 September 2026

Reproduce with:

```sh
python -m model.forest_run --pack ~/omniguard-data/samplepack-v2-20260915T111555Z/windows.jsonl \
    --out ~/omniguard-data/runs/kan20-forest
```

[`model/forest_spec.json`](../model/forest_spec.json) was committed in `9e8493c`, before the
run. Spec SHA-256: `c3091f68a9afdf10637689c0085a59eb7fb601227174b4768e052e39396a1551`.

**Setup:**
- Full `features-1` set at 10, 25, 50, 100 and 200 trees; seeds 1–3.
- Same 1 % budget, validation only, 300 capture-bootstrap resamples.
- Rule: the smallest forest whose recall stays within 0.02 of 200 trees on every seed.

**Cost measurement:** on seed 1's validation rows.
- **Single window:** 300 separate `predict_proba` calls.
- **Batched:** one call on 32 rows, repeated 50 times, reported per window.

**Result: `selected`, smallest forest 100 trees.** The 200-tree reference again reproduces the
KAN-19 threshold exactly.

| Trees | Val recall @1 % FPR (seed 1 / 2 / 3) | Val AP (1 / 2 / 3) | Single window, ms (median) | Batched, µs per window | Tree nodes | joblib bytes |
|---:|---|---|---:|---:|---:|---:|
| 10 | 0.990 / — / 0.856 | 0.996 / 0.992 / 0.995 | 0.28 | 9.2 | 1,084 | 92,076 |
| 25 | 0.945 / — / 0.856 | 0.997 / 0.982 / 0.995 | 0.60 | 19.4 | 2,763 | 232,156 |
| 50 | 0.941 / — / 0.858 | 0.997 / 0.995 / 0.996 | 1.13 | 36.0 | 5,562 | 465,676 |
| **100** | 0.945 / 0.265 / 0.876 | 0.998 / 0.995 / 0.996 | 2.18 | 69.3 | 11,316 | 945,196 |
| 200 | 0.945 / 0.265 / 0.858 | 0.998 / 0.995 / 0.997 | 4.27 | 136.4 | 22,424 | 1,872,236 |

**Report hashes:**
- Committed report ([`model/frozen/kan20/forest_report.json`](../model/frozen/kan20/forest_report.json),
  home paths replaced by `~`): `65d3d0863caafaea02471782c1f8653a853b880d112499fa7276a5c059c2f9d8`.
- Original run output: `3140f3063b1585382722b43f87cfd73e8cee6804c2d57a6d9365b3ad00816f86`.

**What this says:**

1. **Halving the forest keeps the result and halves the cost.**
   - 100 trees matches 200 on every seed, and slightly exceeds it on seed 3.
   - Single-window latency, forest size and file size all fall by about half; latency is close
     to linear in tree count.
2. **Smaller forests fail on the budget, not on ranking.**
   - 10, 25 and 50 trees rank almost as well (AP ≥ 0.98), and on seeds 1 and 3 they match or beat
     200 trees at the budget.
   - All three fail on seed 2: with 1,023 benign validation windows the budget allows 10 false
     positives, and a small forest's coarse scores leave more than 10 benign windows at its top
     score level.
   - This is the same cliff as in the feature ablation, now caused by forest size.
   - The 10-tree forest's 0.990 on seed 1 is the cliff working the other way, not a better model.
3. **Batching matters more than forest size.**
   - One call on 32 windows costs about 136 µs per window at 200 trees, against about 4.3 ms for a
     single-window call: roughly 30 times less.
   - A detector that scores every device's closed window in one call per 5 s tick would gain more
     than any forest reduction.
   - This is a development-machine measurement, and the live detector's call pattern belongs to
     R2.
4. **Timing noise.** The 200-tree single-window median was 4.29 ms in the ablation run and 4.27 ms
   here, on the same machine; an earlier pair of runs differed by 6 %. Differences under about
   10 % are not meaningful.

**Recommendation (for Lead and R2 review):**
- **Forest size for KAN-51:** carry 100 trees as a candidate beside the frozen 200-tree policy.
  It would be a new model with its own validation-selected threshold, so the KAN-19 freeze does
  not change unless the Lead decides to replace it before the holdout is scored.
- **Batching:** batch inference per tick is worth asking R2 about. It changes no contract,
  because each window still gets its own `DetectionResult`.
- **Gateway numbers:** gateway CPU/RAM/latency for 100 vs 200 trees, single and batched, belong to
  the KAN-42 harness.
