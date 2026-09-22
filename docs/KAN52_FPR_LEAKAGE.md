# KAN-52 — what containment costs, and what still gets out

Owner: R1 (Onur). Run of 22 September 2026. Reproduce with:

```sh
python -m model.leakage_run \
    --pack ~/omniguard-data/samplepack-v2-20260915T111555Z/windows.jsonl \
    --artifact ~/omniguard-data/runs/kan19/operating \
    --out ~/omniguard-data/runs/kan52
```

KAN-51 chose **N = 2, lease = 300 s**. This card measures the trade-off that choice
sits on: for every cell of the same grid, what a benign device pays and how much of
the attack still gets through. Both numbers come from one run of the frozen KAN-19
model replayed through `gateway.policy.DevicePolicy`; nothing here retrains,
re-thresholds or re-selects anything.

> **What "leakage" means here.** Observed malicious window-time during which the
> infected device was *not* under quarantine, measured as interval overlap. It is a
> policy decision, not a packet count. The bytes an independent sink receives before
> the kernel ACK are [KAN-33](KAN33_LEAKAGE.md) and the G8 run; the two are reported
> side by side and never added.

**Spec.** [`model/leakage_spec.json`](../model/leakage_spec.json), fixed before the
run. It pins the model (`d30725a9…`), the metadata (`917504c1…`), the threshold
`0.9798815486832`, `features-1`, the KAN-51 grid, and the rule that the test split
stays shut until an approval is recorded in the spec itself.

## What was measured, on what

| Capture | Role | Windows | Observed | Span | Observed share | Activity segments | Silence |
|---|---|---:|---:|---:|---:|---:|---:|
| CTU-Honeypot-Capture-5-1 | benign device | 1,019 | 1.42 h | 5.00 h | 28 % | 714 | 3.59 h |
| CTU-IoT-Malware-Capture-8-1 | infected device | 9,722 | 13.50 h | 24.00 h | 56 % | 4,398 | 10.50 h |

The benign capture has 14 anomalous windows; the infected one has 8,686 malicious
windows, 8,211 of them anomalous. Its 1,036 benign-labelled windows belong to the
infected device, are reported apart, and **none** of them was flagged.

**Benign modes (idle, active, startup, update) are not available.** IoT-23 carries no
mode or scenario label, and inventing one by reading the traffic would be a label the
data does not have. What the capture can answer about its own shape — segments, gaps,
observed share of span — is in the table above. Real mode labels arrive with KAN-66's
controlled Pi scenarios and are evaluated in KAN-65.

## Result

Benign cost is on the left, leakage on the right. The two belong to different devices
and are never pooled.

| N | Lease | False quarantines | per observed device-hour | per span hour | Benign blocked s per span hour | Containment leakage | Interval | Bias | Detection delay |
|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| 1 | 30 s | **13** | 9.19 (3.8–13.5) | 2.60 | 77.9 | 15.9 % | 15.0–16.8 % | +0.000 | 5.5 s |
| 1 | 60 s | **12** | 8.48 (3.8–12.3) | 2.40 | 143.9 | 14.0 % | 14.1–15.6 %¹ | −0.008 | 5.5 s |
| 1 | 120 s | **12** | 8.48 (3.8–12.3) | 2.40 | 287.8 | 0.7 % | 0.0–0.0 %¹ | +0.026 | 5.5 s |
| 1 | 300 s | **11** | 7.77 (3.4–11.4) | 2.20 | 659.4 | 3.1 % | 3.7–4.2 %¹ | −0.009 | 5.5 s |
| 2 | 30 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 40.9 % | 39.8–41.1 % | +0.004 | 10.5 s |
| 2 | 60 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 29.6 % | 28.6–30.0 % | +0.003 | 10.5 s |
| 2 | 120 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 19.4 % | 19.6–21.3 %¹ | −0.011 | 10.5 s |
| **2** | **300 s** | **0** | **0.00 (0.0–0.0)** | **0.00** | **0.0** | **7.5 %** | **7.1–7.9 %** | **−0.000** | **10.5 s** |
| 3 | 30 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 63.7 % | 61.0–65.4 % | +0.005 | 15.5 s |
| 3 | 60 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 40.4 % | 38.7–40.5 % | +0.007 | 15.5 s |
| 3 | 120 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 29.2 % | 27.2–29.3 % | +0.010 | 15.5 s |
| 3 | 300 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 10.9 % | 8.1–9.6 %¹ | +0.021 | 15.5 s |
| 5 | 30 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 99.4 % | 99.2–100 % | −0.002 | 4,860.5 s |
| 5 | 60 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 98.5 % | 97.6–100 % | −0.003 | 4,860.5 s |
| 5 | 120 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 97.9 % | 97.2–100 % | −0.009 | 4,860.5 s |
| 5 | 300 s | 0 | 0.00 (0.0–0.0) | 0.00 | 0.0 | 96.9 % | 96.3–100 % | −0.023 | 4,860.5 s |

¹ The resampled runs did not straddle the measurement in this cell: the bias is larger
than the spread, so the interval is not an uncertainty to quote. The measurement
stands; the width does not. These cells are drawn with a dotted bar in the figure.

![KAN-52 headline](../model/frozen/kan52/kan52_headline.svg)

## What this says

1. **N = 1 is the expensive setting, and the lease makes it worse.** 14 isolated
   anomalous windows on a healthy device become 11–13 quarantines — 7.8 to 9.2 per
   observed device-hour. At a 300 s lease that device spends 659 s of every span hour
   cut off, for nothing. This is the cost the headline figure exists to show.
2. **At N ≥ 2 the benign cost on this capture collapses to zero,** because none of
   those 14 windows has an anomalous neighbour. The trade-off then lives entirely in
   the lease: at N = 2 leakage falls from 40.9 % at 30 s to 7.5 % at 300 s.
3. **Zero is not zero risk.** Zero events in 5.0 device-hours of span is consistent
   with a true rate up to about **0.6 false quarantines per device-hour** (the usual
   rule-of-three bound, 3 / 5.0 h), or 2.1 per *observed* device-hour. One benign
   device for five hours cannot measure a rarer rate than that, and the frozen
   operating point must not be described as having none.
4. **Leakage is not smooth in the lease.** At N = 1 a 120 s lease leaks 0.7 % while
   300 s leaks 3.1 %. Longer is not monotonically better: after each expiry the policy
   needs a fresh anomaly series before it can quarantine again, and where those
   restarts land relative to the attack decides what is covered. The grid is coarse
   and this surface is bumpy; no cell here is an optimum.
5. **N = 5 loses the incident.** Five consecutive anomalous windows almost never occur
   in 8-1 (4,397 gap resets), so 96.9–99.4 % of malicious time goes unblocked and the
   first quarantine arrives 81 minutes in.
6. **The frozen point, measured here:** N = 2, 300 s — 0 false quarantines on the
   benign capture, 7.5 % of observed malicious time unblocked, 10.5 s to the first
   quarantine, and 257 re-quarantines over the capture.

## Uncertainty, and where it stops

Each capture is cut into 600 s blocks of wall-clock time; 200 resamples draw those
blocks with replacement, keeping each block's windows, inner gaps and edge silence, and
every resample is replayed through the same policy. A block is longer than the longest
lease, so one episode fits inside a block.

Each statistic reports four things: the measurement, the raw resample spread, the bias
between them, and a basic bootstrap interval reflected about the measurement. The bias
matters: leakage depends on how episodes and malicious stretches line up over hours,
which a 600 s block cannot reproduce. In 5 of 16 cells the resamples do not straddle
the measurement at all, and those intervals are marked rather than quietly reported.

**This interval is temporal variability inside one capture.** It is not a
device-to-device interval and no amount of resampling can make it one. The benign side
rests on a single honeypot device over five hours.

## Limits

- **One benign device, one infected device.** A per-device-hour rate from one capture
  is an observation, not a population estimate.
- **Validation data.** The threshold and the N/lease pair were chosen on these same
  windows, so this is the friendly case. The untouched estimates are the ADR-0004
  malware holdout, scored once under KAN-71, and, for benign devices, KAN-65 and
  KAN-70. KAN-21 is not that estimate: it closed on 14 September as a
  leave-one-family-out experiment over the development captures, every one of which has
  been on a test side, so nothing in it is untouched.
- **Policy intent, not packets.** Blocked seconds are what the policy decided. What
  actually stopped is KAN-33's sink measurement and the G8 run.
- **Replay timing.** Every window is decided 0.5 s after it closes; real capture and
  inference latency belongs to KAN-42.
- **Gaps reset the series** — the declared baseline. A max-gap variant is not measured.
- **7-1 is not here.** The test split stays unscored; when it is used, its benign
  label is assumed rather than published (ADR-0004), and any number from it must
  say so.

## Evidence

| Artifact | SHA-256 |
|---|---|
| Spec (`model/leakage_spec.json`) | `4e3cd99454b1c9071c35fe633b2acc260cc8a510fd802c45056fe44d17dbc9f0` |
| Committed trimmed report | `66d6ad0caff9d35ef37c50ff6d000ad3e079cfe85239e3a9dd92002e92756ace` |
| Headline figure | `c87a8e3b739e54e9e19540fae74154341c2584e4483813a11b628c208b478991` |
| Full run output, kept outside Git | `15d1d27f2122014644c40e4a667d66850dcb93d738574ab4ff1edd0cc18527fa` |

The trimmed report reduces local paths to file names and drops per-episode lists, so a
rerun on another machine differs only in its `environment` block.

## What is needed next

1. Owner review of this result.
2. A Lead decision on whether the seed-1 test split (7-1, 3-1) is spent on one
   confirmation run. The runner refuses it until that approval is written into the
   spec, and the run would be one-shot.
3. New benign devices (KAN-66 capture, KAN-65 evaluation), so the benign cost does not
   rest on one honeypot.
