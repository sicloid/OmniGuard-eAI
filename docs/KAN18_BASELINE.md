# KAN-18 baseline on real IoT-23 data — 13 September 2026

Owner: R1 (Onur). Reproduce with:

```sh
python -m data.samplepack.iot23 --captures ~/omniguard-data/iot23 --out ~/omniguard-data/samplepack
python -m model.baseline_run --pack ~/omniguard-data/samplepack/windows.jsonl \
    --out ~/omniguard-data/runs/kan18 --seeds 1,2,3 --bootstrap 300
```

Sample pack `windows_sha256`: `4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625`

`model.baseline_run` refuses to train unless `windows.jsonl` hashes to the
`windows_sha256` recorded in its `manifest.json`. Each run writes `provenance.json` beside
its artifact with the pack hash, the manifest hash, the model hash and the hash of
`model.meta.json`, so a result can be traced to exact bytes. These are SHA-256 pins,
not signatures.
(41,334 malicious and 15,590 benign windows over
6 capture groups; 29 unknown windows excluded).

## Setup

Training uses the train split only; every number below is measured on **validation**.
The test split was never read. The threshold is the fixed 0.5 baseline: KAN-19 selects an
operating threshold, and a run like this is what it would select from.

With six groups the split gives each part one capture per class, so each run trains on
**one benign and one malware capture**. That is the dominant fact about these results.

## Results (200 trees, 300 bootstrap resamples)

| Seed | Train | Validation | RF P | RF R | RF F1 | RF FPR | Rule P | Rule R | Rule FPR |
|---|---|---|---|---|---|---|---|---|---|
| 1 | ben-4-1, mal-34-1 | ben-5-1, mal-8-1 | 0.914 | 1.000 | 0.955 | **0.4000** | 0.785 | 0.390 | 0.451 |
| 2 | ben-4-1, mal-34-1 | ben-5-1, mal-3-1 | 0.969 | 1.000 | 0.984 | **0.8035** | 0.961 | 0.854 | 0.866 |
| 3 | ben-5-1, mal-34-1 | ben-7-1, mal-3-1 | 1.000 | 0.857 | 0.923 | **0.0001** | 0.724 | 1.000 | 1.000 |

## What this shows

**The pipeline runs end to end on real captures.** PCAP to PacketTuple to 5 s windows to
14 features to a Random Forest to metrics and a hash-pinned artifact, with capture-grouped splits
and no leakage. That was the mechanical goal of the card.

**It does not show detection quality, and the reason is measurable.** The false-positive rate
moves between 0.0001 and 0.80 depending only on which benign capture is in training. Recall
stays high throughout, so the model is not failing to see attacks; it is failing to recognise
unfamiliar benign traffic. With one benign device in training, "benign" means "this device's
habits", and a different household device looks anomalous.

These are fixed-threshold (0.5), aggregate window FPR measurements. Two consequences are
plausible but **untested here**: that a 0.40-0.80 window FPR would make the N-consecutive
rule quarantine a healthy device repeatedly, and that no validation-selected threshold
could lower it without giving up recall. KAN-19 threshold selection and the KAN-51
N/FPR experiment are where those hypotheses get measured.

**The uncertainty estimates are degenerate.** Recall intervals collapse to a point and the FPR
interval in seeds 1-2 spans (0.0, 0.807), because capture-level bootstrap resamples a single
validation group per class. The honest reading is that these point estimates carry no usable
confidence interval.

**The rate-rule baseline is not better.** It either misses most attacks (seed 1, recall 0.39)
or flags everything (seed 3, FPR 1.0). It fails differently, not less.

## What has to change before any quality claim

1. **More benign devices.** This is the bottleneck: three benign captures, two of them small
   (9,770 / 2,831 / 1,019 windows). IoT-23 publishes only three honeypot scenarios, so a second
   benign source, or benign periods from more device types, is required.
2. **Report per-capture results, not one aggregate.** The spread above is the result; an
   averaged number would hide it.
3. **Check for device-identity leakage in the features.** Scale-sensitive features
   (`pkt_count`, `l3_bytes_sum`, `uniq_dst_ip`) may encode "which device" rather than "what
   behaviour". KAN-20's ablation should test exactly that.
4. **KAN-21's unseen-family holdout** stays mandatory before any claim about generalisation.

This is a valid negative baseline result. It makes no G5 claim: the numbers describe
the benign-coverage problem, not the quality of a finished detector.

## Note on the split module

The real group sizes exposed a bug in KAN-17's allocation: filling the window-count target
could consume two of three benign groups and leave the train split empty. The module refused
to produce a split rather than degrade silently, which was the right behaviour, and the fix
caps how many groups each split may take. A regression test uses these real window counts.
