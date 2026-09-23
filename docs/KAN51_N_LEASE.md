# KAN-51 — N and lease on the validation split

Owner: R1 (Onur). Corrected run of 21 September 2026. Reproduce with:

```sh
python -m model.nlease_run \
    --pack ~/omniguard-data/samplepack-v2-20260915T111555Z/windows.jsonl \
    --artifact ~/omniguard-data/runs/kan19/operating \
    --out ~/omniguard-data/runs/kan51
```

The threshold decides whether a window is anomalous. **N** decides how many consecutive
anomalous windows it takes to quarantine a device, and the **lease** decides how long
that quarantine lasts. This card measures what each choice costs.

> **Status.** N = 2 is the Lead's provisional validation choice (20 September, first-hand
> on PR #44). **No lease is approved and the holdout stays sealed** until this corrected
> result is reviewed. The first run's 30 s recommendation is superseded; see
> "What changed, and why" below.

## Method

- **The decisions are the frozen ones.** The KAN-19 artifact is loaded with both pinned
  hashes verified (model `d30725a9…`, metadata `917504c1…`), and the threshold
  `0.9798815486832` is used as recorded, never recomputed.
- **The policy is the real one.** Each device's results are replayed through
  `gateway.policy.DevicePolicy`, the class the runtime uses, so gap resets, staleness
  rejection and the no-renewal rule are the shipped behaviour rather than a model of it.
- **Clock.** A window closes at `start + 5 s` and is decided 0.5 s later. After every
  expiry the episode is re-armed, as an operator or reconcile step would.
- **A lease ends at its deadline.** The replay only ticks at window decisions, so it can
  notice an expiry late when the device is silent. Every episode is capped at
  `start + lease`, which is when the kernel element actually expires.
- **Containment is overlap, not totals.** `malicious_time_blocked_fraction` is the share
  of observed malicious window-time during which the device was actually quarantined:
  the intersection of episode intervals with the malicious windows `[start, start + 5)`.
- **Data.** The seed-1 validation split only: benign Honeypot-5-1 and malware
  Malware-8-1. The test split (7-1, 3-1) is not scored and the ADR-0004 holdout is not
  read. Each capture holds exactly one device, and the runner checks that.
- **A false quarantine is only counted on a benign device.** The benign windows inside
  Malware-8-1 belong to the infected device and are excluded by construction.

**Spec.** [`model/nlease_spec.json`](../model/nlease_spec.json), SHA-256
`4d00461aed16177719f679887d7639d13bdf0f7d568f0e4363388b1ce1baf71d`. It supersedes
`e812d3e9…` (declared in `b72a312` before the first run) only by turning the 0.9 floor
already written into the lease rule into a validated numeric field, and by stating the
criterion as interval overlap. The grid, frozen policy, replay settings and floor value
are unchanged.

| Capture | Windows | Observed | Span | Observed share of span | Anomalous windows |
|---|---:|---:|---:|---:|---:|
| Honeypot-5-1 (benign) | 1,019 | 1.42 h | 5.00 h | 28 % | 14 |
| Malware-8-1 | 9,722 | 13.50 h | 24.00 h | 56 % | 8,211 of 8,686 malicious |

## Result

**Status `selected`: N = 2, lease = 300 s**, by the declared rule: the smallest N with
no false quarantine on the benign capture, then the smallest lease whose blocked share
of malicious time is at least 0.9.

| N | Lease | Benign quarantines | Benign blocked share of span | Malware quarantines | Detection delay | Malicious time blocked | Malware blocked share of span |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 30 s | **13** | 2.2 % | 2,397 | 5.5 s | 84.1 % | 83.2 % |
| 1 | 60 s | **12** | 4.0 % | 1,220 | 5.5 s | 86.0 % | 84.7 % |
| 1 | 120 s | **12** | 8.0 % | 683 | 5.5 s | 99.3 % | 94.8 % |
| 1 | 300 s | **11** | 18.3 % | 268 | 5.5 s | 96.9 % | 92.9 % |
| 2 | 30 s | 0 | 0 % | 1,998 | 10.5 s | 59.1 % | 69.3 % |
| 2 | 60 s | 0 | 0 % | 1,020 | 10.5 s | 70.4 % | 70.8 % |
| 2 | 120 s | 0 | 0 % | 550 | 10.5 s | 80.6 % | 76.3 % |
| **2** | **300 s** | **0** | **0 %** | **257** | **10.5 s** | **92.5 %** | **89.0 %** |
| 3 | 30 s | 0 | 0 % | 1,317 | 15.5 s | 36.3 % | 45.7 % |
| 3 | 60 s | 0 | 0 % | 983 | 15.5 s | 59.7 % | 68.3 % |
| 3 | 120 s | 0 | 0 % | 503 | 15.5 s | 70.8 % | 69.9 % |
| 3 | 300 s | 0 | 0 % | 253 | 15.5 s | 89.1 % | 87.6 % |
| 5 | 30 s | 0 | 0 % | 23 | 4,860.5 s | 0.6 % | 0.8 % |
| 5 | 60 s | 0 | 0 % | 23 | 4,860.5 s | 1.6 % | 1.6 % |
| 5 | 120 s | 0 | 0 % | 13 | 4,860.5 s | 2.1 % | 1.8 % |
| 5 | 300 s | 0 | 0 % | 8 | 4,860.5 s | 3.2 % | 2.8 % |

**Evidence.** [`model/frozen/kan51/nlease_report.json`](../model/frozen/kan51/nlease_report.json)
is the trimmed report written by the runner itself (`model.nlease_run.trimmed_report`):
every cell with both denominators, the overlap and blocked seconds, the policy's
rejection and reset counters, and the first three episodes per capture. The full report
is written beside it by the same run and kept outside Git.

| Artifact | SHA-256 |
|---|---|
| Committed trimmed report (`nlease_report.trimmed.json` of the run) | `6d5d934d8666cc725dcc1f3a9a39caf6dc13fef60efbde0c366d4baa0f434e9a` |
| Full run output, kept outside Git | `a0951c70722bb332fde469608994fcb09742e8aee06e829112430a0162829577` |

The trimmed report reduces local paths to file names, so a rerun on another machine
differs only in its `environment` block.

## What this says

1. **N=1 is not usable.** 14 isolated anomalous windows out of 1,019 on the benign
   device become 11–13 quarantines of a healthy device in a five-hour span, up to 18 % of
   it blocked at a 300 s lease.
2. **N=2 removes every false quarantine here,** because none of those 14 windows has an
   anomalous neighbour. It is a property of this capture, not a general guarantee.
3. **A short lease leaks the attack.** After each expiry the policy needs two fresh
   consecutive anomalies before it can quarantine again, so every episode boundary opens
   at least one window of unblocked traffic. At N=2 with a 30 s lease that happens
   1,998 times and 41 % of malicious time goes unblocked; at 300 s it happens 257 times
   and 7.5 % does.
4. **The price of waiting is one window.** Detection delay is `(N−1)×5 s + 5.5 s`:
   10.5 s at N=2, 15.5 s at N=3.
5. **N=5 loses the incident.** Five consecutive anomalous windows almost never occur in
   8-1 (4,397 gap resets); malicious time blocked falls to 0.6–3.2 %.
6. **`FPR^N` is a comparison, never evidence.** `FPR²` would predict about 0.2 false
   quarantines in this span against 0 measured; the arithmetic assumes independent
   windows and they are not. The decision rests on the measured counts.

**The selected lease is the edge of the grid.** 300 s is the longest lease declared, so
this run shows that 300 s meets the floor and shorter leases do not; it does not show
that 300 s is the best value. A longer lease would contain more of this capture and
would also keep a wrongly quarantined device cut off longer. Extending the grid would be
a new declared run, not a re-reading of this one.

## What changed, and why

The first run (report kept at
[`model/frozen/kan51/superseded/nlease_report_9c5f423.json`](../model/frozen/kan51/superseded/nlease_report_9c5f423.json),
SHA-256 `d146a620…`) recommended **N = 2, lease = 30 s**. The R3 review found two
defects that carried that recommendation:

1. **Containment compared totals.** `min(blocked_seconds, malicious_seconds) /
   malicious_seconds` does not require the blocked intervals to overlap the malicious
   windows. On 8-1 the totals saturated, so every cell from N=1 to N=3 reported 100 %.
   Measured as overlap, N=2 / 30 s blocks 59 % of malicious time, not 100 %.
2. **Leases outlived their deadline in the replay.** An expiry during silence was only
   noticed at the next window, adding up to 9.9 % blocked time on 8-1 and 25.6 % on
   5-1, and inflating short leases most.

Quarantine **counts** were unaffected, so the N result (13 → 0 false quarantines) stands.
The lease result changed from 30 s to 300 s. The Lead withdrew the relayed 30 s
approval on PR #44 for exactly these reasons.

## Limits

- **One benign device and one malware capture.** A per-hour rate from a single device is
  an observation, not a population estimate.
- **Validation data.** The threshold was selected on these same windows, so the benign
  side is the friendly case, not a deployment estimate.
- **Replay timing.** Every window is decided 0.5 s after it closes; real capture and
  inference latency belongs to KAN-42.
- **Policy intent, not traffic.** Blocked seconds are what the policy decided. Whether
  packets actually stopped is KAN-33's counter and the KAN-52 experiment.
- **Empty windows.** A gap resets the series (the declared baseline); the max-gap
  variant is not measured.

## What is needed next

1. Review of this corrected result.
2. The Lead's first-hand record of the final N/lease pair on PR #44 and in ADR-0004
   decision 7b. The ADR currently records N = 2 as provisional and the lease as not
   approved.
3. Only then may the holdout be downloaded, hashed, audited and scored once.
