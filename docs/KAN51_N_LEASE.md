# KAN-51 — N and lease on the validation split, 20 September 2026

Owner: R1 (Onur). Reproduce with:

```sh
python -m model.nlease_run \
    --pack ~/omniguard-data/samplepack-v2-20260915T111555Z/windows.jsonl \
    --artifact ~/omniguard-data/runs/kan19/operating \
    --out ~/omniguard-data/runs/kan51
```

The threshold decides whether a window is anomalous. **N** decides how many consecutive
anomalous windows it takes to quarantine a device, and the **lease** decides how long
that quarantine lasts. This card measures what each choice costs.

**The run was specified before it ran.** [`model/nlease_spec.json`](../model/nlease_spec.json)
was committed in `104b2e4`, before any replay. Spec SHA-256:
`e812d3e934fa3662108df1fe2e5222b767ab9f58e3f6750eadd12063d411109a`.

## Method

- **The decisions are the frozen ones.** The KAN-19 artifact is loaded with both pinned
  hashes verified (model `d30725a9…`, metadata `917504c1…`), and the threshold
  `0.9798815486832` is used as recorded, never recomputed.
- **The policy is the real one.** Each device's results are replayed through
  `gateway.policy.DevicePolicy`, the class the runtime uses, so gap resets, staleness
  rejection, lease expiry and the no-renewal rule are the shipped behaviour rather than
  a model of it.
- **Clock.** A window closes at `start + 5 s` and is decided 0.5 s later; the lease
  expires exactly `lease_seconds` after the decision. After every expiry the episode is
  re-armed, as an operator or reconcile step would. Without that a device could be
  quarantined at most once and the rate would be capped by construction.
- **Data.** The seed-1 validation split only: benign Honeypot-5-1 and malware
  Malware-8-1. The test split (7-1, 3-1) is not scored and the ADR-0004 holdout is not
  read.
- **A false quarantine is only counted on a benign device.** The benign windows inside
  Malware-8-1 belong to the infected device and are excluded by construction.

**Two denominators, kept apart.** A quarantine keeps running through a silent gap, so
blocked time is wall-clock, while a per-window rate belongs to the time the device was
actually seen sending. Mixing them reports more than 3600 blocked seconds per hour.

| Capture | Windows | Observed | Span | Observed share of span | Anomalous windows |
|---|---:|---:|---:|---:|---:|
| Honeypot-5-1 (benign) | 1,019 | 1.42 h | 5.00 h | 28 % | 14 |
| Malware-8-1 | 9,722 | 13.50 h | 24.00 h | 56 % | 8,211 of 8,686 malicious |

## Result

**Status `selected`: N = 2, lease = 30 s**, by the rule fixed in the spec: the smallest N
with no false quarantine, then the smallest lease containing at least 90 % of observed
malicious time.

**Approved by the Lead on 20 September 2026**, both the rule and the pair. N = 1 is out
because it produces false quarantines on the benign device; N = 2 gives zero of them at
100 % containment; a 300 s lease reaches the same false-quarantine result but keeps a
device cut off longer than necessary, so the smallest sufficient lease was taken. The
values are recorded in [ADR-0004 decision 7b](adr/0004-dataset-source.md), which
completes the list the holdout freeze requires.

| N | Lease | Benign quarantines | Benign per span-hour | Benign blocked share of span | Malware quarantines | Detection delay | Contained malicious time |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 30 s | **13** | 2.60 | 2.7 % | 2,397 | 5.5 s | 100 % |
| 1 | 60 s | **12** | 2.40 | 4.7 % | 1,220 | 5.5 s | 100 % |
| 1 | 120 s | **12** | 2.40 | 8.6 % | 683 | 5.5 s | 100 % |
| 1 | 300 s | **11** | 2.20 | 18.5 % | 268 | 5.5 s | 100 % |
| **2** | **30 s** | **0** | 0 | 0 % | 1,998 | 10.5 s | 100 % |
| 2 | 60 s | 0 | 0 | 0 % | 1,020 | 10.5 s | 100 % |
| 2 | 120 s | 0 | 0 | 0 % | 550 | 10.5 s | 100 % |
| 2 | 300 s | 0 | 0 | 0 % | 257 | 10.5 s | 100 % |
| 3 | 30 s | 0 | 0 | 0 % | 1,317 | 15.5 s | 100 % |
| 3 | 60 s | 0 | 0 | 0 % | 983 | 15.5 s | 100 % |
| 3 | 120 s | 0 | 0 | 0 % | 503 | 15.5 s | 100 % |
| 3 | 300 s | 0 | 0 | 0 % | 253 | 15.5 s | 100 % |
| 5 | 30 s | 0 | 0 | 0 % | 23 | **4,860.5 s** | **1.6 %** |
| 5 | 60 s | 0 | 0 | 0 % | 23 | **4,860.5 s** | **3.2 %** |
| 5 | 120 s | 0 | 0 | 0 % | 13 | **4,860.5 s** | **3.6 %** |
| 5 | 300 s | 0 | 0 | 0 % | 8 | **4,860.5 s** | **5.6 %** |

**Evidence:** [`model/frozen/kan51/nlease_report.json`](../model/frozen/kan51/nlease_report.json)
carries every cell with both denominators, the policy's rejection and reset counters and
the first three episodes per capture. The per-episode lists are dropped from the
committed copy, because the full output is 2.3 MB and no run dump belongs in Git.

| Artifact | SHA-256 |
|---|---|
| Committed report (trimmed, home paths replaced by `~`) | `d146a620be9af089d7228d5331e5f308f90be1a978a5e970a17f9787a248aa88` |
| Full run output, kept outside Git | `b350ca50582844a25bdcbd7684483d7c69754837880c5f08c2329f80da634ab0` |

## What this says

1. **N=1 is not usable, and the window FPR alone would not have told us.** The benign
   device has 14 anomalous windows out of 1,019, which sounds small. At N=1 that is
   11–13 quarantines of a healthy device in a five-hour span, up to 18.5 % of it
   blocked at a 300 s lease. A user would notice.
2. **N=2 removes every false quarantine here.** The 14 false positives on 5-1 are
   isolated single windows; none has an anomalous neighbour. That is why one extra
   window of evidence turns 13 quarantines into none. It is a property of this capture,
   not a general guarantee.
3. **The price of waiting is one window.** Detection delay is `(N−1)×5 s + 5.5 s`:
   5.5 s at N=1, 10.5 s at N=2, 15.5 s at N=3, while containment of the malware capture
   stays at 100 % of observed malicious time up to N=3.
4. **N=5 collapses, and this is the most useful finding.** Five consecutive anomalous
   windows almost never occur in 8-1: the policy records 4,397 gap resets, because the
   device's traffic is not continuous. Detection delay jumps from 15.5 s to 4,860 s and
   containment falls to 1.6–5.6 %. Going from N=3 to N=5 does not trade a little recall
   for a little comfort; it loses the incident.
5. **A shorter lease does not mean less exposure for a device that keeps attacking.** At
   N=2 the blocked share of the span is 76 % at a 30 s lease and 90 % at 300 s, while
   the episode count falls from 1,998 to 257. The lease mostly decides how often the
   device is re-quarantined, not whether it is contained.
6. **`FPR^N` is reported as a comparison, never as evidence.** With a 1.4 % window FPR
   on this capture, `FPR²` would predict roughly 0.2 false quarantines in this span,
   against 0 measured. The arithmetic assumes consecutive windows are independent and
   they are not, so the comparison only shows why the assumption is unsafe; the decision
   rests on the measured counts. (Lead, 20 September.)

## Limits

- **One benign device and one malware capture.** A per-hour rate from a single device is
  an observation, not a population estimate. KAN-21 showed that a threshold frozen on
  one benign device does not transfer to another; the same caution applies here.
- **Validation data.** The threshold was selected on these same windows, so the benign
  side is the friendly case, not a deployment estimate.
- **Replay timing.** Every window is decided 0.5 s after it closes. Real capture and
  inference latency belongs to KAN-42, and 8-1 is a 2018 capture replayed at its
  recorded timestamps.
- **Policy intent, not traffic.** Blocked seconds are what the policy decided. Whether
  packets actually stopped is KAN-33's counter and the KAN-52 experiment.
- **Empty windows.** The baseline treats a gap as a series reset; the max-gap variant
  discussed for KAN-20 is not measured here.

## What this unblocks, and what it needs

ADR-0004 decision 7b allows the untouched holdout to be scored only after the feature
schema version, the model and metadata hashes, the threshold policy hash, the
development pack hash **and N/lease** are recorded. Everything except N and lease was
frozen in KAN-19; this run proposes the missing pair.

**Recorded on 20 September 2026.** The Lead approved the selection rule and the pair
N = 2, lease = 30 s, and the values are written into ADR-0004 decision 7b beside the
hashes that were already frozen in KAN-19.

The holdout may therefore be downloaded, hashed and audited, and then scored **once**,
as a separate one-time evaluation. Scoring it is not part of this card.
