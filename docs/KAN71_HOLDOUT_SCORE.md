# KAN-71 — the sealed holdout, scored once

Owner: R1 (Onur). Run of 25 September 2026. **The result is bad, and it is reported as
measured.** Reproduce with:

```sh
python -m data.holdout.pipeline score \
    --pack ~/omniguard-data/holdout-pack/windows.jsonl \
    --artifact ~/omniguard-data/runs/kan19/operating \
    --out ~/omniguard-data/runs/holdout
```

The runner refuses to run again while `data/holdout/score_record.json` exists. That file
is committed, so a second run needs this commit reverted in review.

## What was run

The frozen KAN-19 policy, unchanged, against three IoT-23 captures that no experiment in
this project had ever read: model `d30725a9…`, metadata `917504c1…`, threshold
`0.9798815486832`, `features-1`, N = 2, lease = 300 s. Every pin was recorded before the
captures were downloaded, and the audit gate passed before the pack was built.

Spec `30d6b4c3…` · selection `8c305c85…` · pack `7205c961…` · manifest `c65558cf…`

## Result

| Capture | Family | Role | Malicious windows | Flagged | Window recall | Quarantined | Malicious time blocked |
|---|---|---|---:|---:|---:|---|---:|
| 48-1 | Mirai | **seen family** | 7,036 | **0** | **0.0 %** | no | 0.0 % |
| 36-1 | Okiru | unseen | 17,278 | **0** | **0.0 %** | no | 0.0 % |
| 20-1 | Torii | unseen | 16,545 | 253 | **1.53 %** | yes, twice | 0.49 % |

Detection delay on 20-1 was 10.5 s, the same as everywhere else: when the policy fires at
all, it fires on schedule. The 134 benign-labelled windows inside 20-1 produced no flags;
they belong to the infected device and are not a benign-device FPR.

**Untouched benign FPR: not measured** (ADR-0004 decision 7c). This pack holds no
untouched benign device, so the run says nothing about false quarantines.

## What this says

1. **The detector does not transfer to unseen captures.** On validation it flagged 94.5 %
   of malicious windows. On the seed-1 test split, 41.2 %. Here: 0 %, 0 % and 1.5 %.
   Three independent evaluations, one direction.
2. **A seen family does not help.** 48-1 is Mirai and the development pack contains Mirai
   (34-1), yet the model flagged nothing. Whatever it learned from 34-1 does not describe
   Mirai in 48-1. This is the strongest evidence so far for the device-and-environment
   confound recorded in KAN-21 and in the methodology document.
3. **The pipeline is alive.** 20-1 produced 253 flags and two real quarantines with a
   correct 10.5 s delay, so the extractor, the model load and the policy replay all ran.
   A zero here is the model's answer, not a dead code path.
4. **The frozen threshold is the mechanism.** `features-1` is volume-dominated (KAN-20),
   and these captures differ in device, period and traffic scale from the development
   set. A threshold chosen at a 1 % window-FPR budget on one benign honeypot does not
   carry to them. It is the same failure the KAN-52 test confirmation measured, larger.

## What must not happen next

The holdout is spent. Under ADR-0004 decision 7b and the KAN-71 conditions, **no model,
threshold, N or lease may be adjusted in response to these numbers**, and no second run
may be made on this pack. Any later tuning has to be judged on data this project has not
read, which at the moment does not exist.

What the result does justify is the work already queued: a benign source that is not one
honeypot (KAN-65, KAN-68), a model candidate trained with wider coverage (KAN-67), and a
new untouched holdout for that candidate (KAN-70). Those cards are blocked on review and
approval, not on this result.

## Limits

- **Three captures, one dataset, one collection environment.** Not a population estimate
  of detection rate; what the frozen policy did on these three files.
- **48-1 carries an approved deviation:** its final 8-byte record is treated as a
  truncated tail. Rebuilding the development pack with the same builder reproduced
  `4b97fb95…` and `8ea8c310…` byte for byte, so the deviation moved no frozen number.
- **Malware-only.** No benign device is in this pack, so no false-quarantine statement
  follows from it in either direction.
- **Device identity** came from the capture file names, declared in the spec before any
  byte was read; the audit then confirmed EGRESS traffic from each declared device.

## Evidence

| Artifact | SHA-256 |
|---|---|
| Spec (`data/holdout/score_spec.json`) | `30d6b4c35a265c08debf1844bca88b9758330d32d816c5058ee2a25f1191b01f` |
| Selection manifest | `8c305c8507fd86f9c08db6cdd2627b8f4928b469134ae05104b96c4d852a264c` |
| Pack windows | `7205c961ee559567f09faa78b0ff51170243b1a1835e8432c8fc9dd417ca53ec` |
| Run report (`holdout_report.json`, kept outside Git) | `4ba02ad54b71fe98902403e739e99062841218eda441041a5f809d08bb235002` |
| One-shot record (committed) | `data/holdout/score_record.json` |
