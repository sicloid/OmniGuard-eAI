# KAN-20 feature ablation and per-window cost — 17 September 2026

Owner: R1 (Onur). Reproduce with:

```sh
python -m model.ablation_run --pack ~/omniguard-data/samplepack-v2-20260915T111555Z/windows.jsonl \
    --captures ~/omniguard-data/iot23 --out ~/omniguard-data/runs/kan20
```

**The run was specified before it ran.** [`model/ablation_spec.json`](../model/ablation_spec.json)
and the runner were committed in `c750d21` before any ablation on real data. The spec fixes:

- the candidate sets;
- the KAN-19 window-FPR budget (1 %) and objective, selected on validation only;
- seeds 1–3, 200 trees and 300 capture-bootstrap resamples;
- the compact-set rule and its tolerance;
- the timing sample.

Spec SHA-256: `d43f2ac1dc14ba417f6646d1c2270b6b00e7281b9c7e64972a7b3e5c79826773`.

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

**Cost.** Three measurements for every set:
- **Extraction time:** the runtime extractor's arithmetic, split into the four groups. A test pins
  that the split reproduces `extract_features` exactly. Timed over 4,000 real packet windows from
  4-1 and 34-1, the seed-1 train captures. Only packets are used, no labels.
- **Inference latency:** one `predict_proba` call per window, as the live detector makes it.
- **Model size:** the seed-1 model's forest size.

## Result

**Status: `selected`. Compact finalist: `without:protocol` (11 features).**

The full set on seed 1 reproduces the frozen KAN-19 threshold exactly (`0.9798815486832`).

| Set | n | Val recall @1 % FPR (seed 1 / 2 / 3) | Val AP (1 / 2 / 3) | Extraction µs/window | Inference ms (median) | Tree nodes |
|---|---:|---|---|---:|---:|---:|
| full | 14 | 0.945 / 0.265 / 0.858 | 0.998 / 0.995 / 0.997 | 4.55 | 4.24 | 22,424 |
| **without:protocol** | 11 | 0.949 / 0.272 / 0.907 | 0.998 / 0.996 / 0.997 | 3.40 | 4.24 | 23,260 |
| without:destinations | 11 | 0.376 / — / 0.926 | 0.991 / 0.997 / 0.999 | 3.39 | 4.26 | 20,388 |
| without:connection | 10 | — / — / 0.855 | 0.986 / 0.977 / 0.996 | 3.32 | 4.23 | 15,452 |
| without:volume | 10 | — / — / — | 0.978 / 0.976 / 0.863 | 3.65 | 4.26 | 50,614 |
| pair:volume+connection | 8 | 0.377 / — / 0.926 | 0.995 / 0.997 / 0.998 | 2.17 | 4.26 | 23,334 |
| pair:volume+protocol | 7 | — / — / 0.900 | 0.972 / 0.992 / 0.996 | 2.15 | 4.25 | 14,818 |
| only:volume | 4 | — / — / 0.906 | 0.977 / 0.992 / 0.993 | 1.00 | 4.28 | 14,344 |
| only:connection | 4 | — / — / — | 0.981 / 0.994 / 0.985 | 1.28 | 4.25 | 55,778 |
| only:destinations | 3 | 0.020 / — / 0.108 | 0.830 / 0.957 / 0.676 | 1.27 | 4.23 | 8,672 |
| only:protocol | 3 | — / — / 0.025 | 0.897 / 0.961 / 0.731 | 1.26 | 4.24 | 2,952 |

In the table:
- **"—"** means no threshold met the 1 % budget on that seed. The budget was not relaxed.
- **Pairs not shown** (`volume+destinations`, `destinations+protocol`, `destinations+connection`,
  `protocol+connection`) fail the rule on every seed.

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
| Committed report (home paths replaced by `~`) | `503a48b3c1559436cce57971ae0ad743e67a3a8052b9e1d05128406946b525d2` |
| Original run output | `c4145e68c178d302ff8611d3a30b58b5a9fce5079bed607aae4ad862d43e7d61` |

The pack is manifest v2 `8ea8c310…` (`label_rule_version` `window-label-1`); its windows
`4b97fb95…` are the same as in KAN-18/19.

## What this says

1. **Volume features are the one group detection cannot lose.**
   - Without them, no seed finds a threshold under the budget.
   - Alone, volume and connection both rank well (AP ≥ 0.977), but only volume ever passes the
     budget by itself, on seed 3.
   - Destinations or protocol alone are weak (AP 0.68–0.96).
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
   - Extraction takes about 1–4.5 µs per window.
   - A single `predict_proba` takes about 4.2 ms for every set, roughly a thousand times more,
     dominated by the call overhead of 200 trees.
   - Dropping the protocol group saves about 1.1 µs per window (−25 % of extraction) and changes
     neither inference time nor model size meaningfully.

## Recommendation (for Lead review)

- **Runtime catalogue:** keep `features-1`. A `features-2` without the protocol group would need a
  contract change and a new pack, and it saves too little to justify either.
- **KAN-51's "two feature sets × N" matrix:** if a second set is still wanted, use `full` and
  `without:protocol`. Because the saving is small, forest size may be the better second axis.
- **Next cost experiment:** inference latency is dominated by `n_estimators` and per-call
  overhead. A tree-count sweep, or batching windows per device tick, would move gateway latency;
  feature pruning would not. That needs its own declared experiment, measured on the gateway with
  the KAN-42 harness.
- **Decision needed from the Lead:** the 0.02 tolerance. The rule and every verdict are recorded,
  so a different tolerance can be checked against the report without re-running.
