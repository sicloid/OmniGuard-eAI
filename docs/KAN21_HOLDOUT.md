# KAN-21 unseen-family holdout on real IoT-23 data — 14 September 2026

Owner: R1 (Onur). Reproduce with:

```sh
python -m model.holdout_run --pack ~/omniguard-data/samplepack/windows.jsonl \
    --out ~/omniguard-data/runs/kan21 --seed 1 --bootstrap 300 --trees 200 --max-window-fpr 0.01
```

- Pack `windows_sha256`: `4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625`
- Pack `manifest_sha256`: `65c7184c3cb8602105684f80b415e4fd17e4e5bdab5ce1813aa5af9f9bdbdfb0`
- `folds_sha256`: `008e3be08fd3f82520e33f32e36b80868b07b811223e57f9f4d3bf0947b4f00d`

The runner refuses to start unless the pack matches its manifest, as the KAN-18 runner does.
This is a separate result from the KAN-18 baseline, as the card requires. It uses the IoT-23
source proposed in ADR-0004, which the team has not approved yet.

## Method

- **Families.** IoT-23 names them per scenario: 3-1 is Muhstik, 8-1 is Hakai, 34-1 is
  Mirai. Each family is a single capture.
- **Folds.** One family is held out and appears only in test. Of the two remaining
  families, one validates and the other trains. Benign captures rotate through test,
  validation and train. That gives 3 × 2 × 3 = 18 folds.
- **Threshold.** The Random Forest (200 trees, seed 1) trains on train windows only. KAN-19's
  `calibrate_threshold` then picks the highest-recall threshold whose validation window FPR
  is at most 1 %. The threshold is frozen before any test window is scored. If no threshold
  meets the budget, the fold is recorded as having none; the budget is never relaxed.
- **Reported per fold.** Recall on the held-out family's capture and FPR on the unseen benign
  capture, each at the frozen threshold and at a fixed 0.5 reference.

Every capture sits on the test side of some fold. These results must not be used to tune
features, thresholds or N and then be re-scored on the same captures. A final quality claim
needs captures that were not used here.

## Results

| Held out | Validation family | Benign test | Threshold | Recall | Benign FPR | Recall @0.5 | Benign FPR @0.5 |
|---|---|---|---|---|---|---|---|
| Hakai | Mirai | ben-4-1 | none | — | — | 1.000 | 0.001 |
| Hakai | Mirai | ben-5-1 | 0.4150 | 1.000 | **0.126** | 1.000 | 0.076 |
| Hakai | Mirai | ben-7-1 | 0.2300 | 1.000 | 0.000 | 1.000 | 0.000 |
| Hakai | Muhstik | ben-4-1 | none | — | — | 0.999 | **0.958** |
| Hakai | Muhstik | ben-5-1 | none | — | — | 1.000 | **0.807** |
| Hakai | Muhstik | ben-7-1 | 0.7050 | 0.999 | 0.000 | 1.000 | 0.000 |
| Mirai | Hakai | ben-4-1 | 0.9400 | 0.616 | 0.001 | 0.880 | 0.001 |
| Mirai | Hakai | ben-5-1 | 0.9500 | 0.597 | 0.008 | 0.846 | 0.076 |
| Mirai | Hakai | ben-7-1 | 0.8950 | 0.607 | 0.000 | 0.762 | 0.000 |
| Mirai | Muhstik | ben-4-1 | 0.5550 | 0.674 | 0.001 | 0.725 | 0.001 |
| Mirai | Muhstik | ben-5-1 | 0.0750 | 0.903 | **0.631** | 0.638 | 0.001 |
| Mirai | Muhstik | ben-7-1 | 0.0550 | 0.797 | 0.000 | 0.656 | 0.000 |
| Muhstik | Hakai | ben-4-1 | none | — | — | 1.000 | **0.958** |
| Muhstik | Hakai | ben-5-1 | none | — | — | 1.000 | **0.807** |
| Muhstik | Hakai | ben-7-1 | 0.7250 | 0.487 | 0.000 | 0.858 | 0.000 |
| Muhstik | Mirai | ben-4-1 | none | — | — | 0.901 | 0.001 |
| Muhstik | Mirai | ben-5-1 | 0.0750 | 0.991 | **0.631** | 0.892 | 0.001 |
| Muhstik | Mirai | ben-7-1 | 0.1100 | 0.985 | 0.000 | 0.743 | 0.000 |

Summary by held-out family:

| Held out | Folds with a threshold | Recall (frozen) | Benign FPR (frozen) | Recall @0.5 | Benign FPR @0.5 |
|---|---|---|---|---|---|
| Hakai (8-1) | 3 / 6 | 0.999–1.000 | 0.000–0.126 | 0.999–1.000 | 0.000–0.958 |
| Mirai (34-1) | 6 / 6 | 0.597–0.903 | 0.000–0.631 | 0.638–0.880 | 0.000–0.076 |
| Muhstik (3-1) | 3 / 6 | 0.487–0.991 | 0.000–0.631 | 0.743–1.000 | 0.000–0.958 |

## What this shows

1. **The held-out families are mostly still flagged.** Hakai recall is about 1.0 in every
   fold, Mirai ranges 0.60–0.90 and Muhstik 0.49–0.99. It is the most positive R1 signal so
   far, but it cannot yet be read as detecting unseen malware behaviour. Every IoT-23 malware
   capture ran on Raspberry Pi hardware and every benign capture is a real consumer device, so
   "unseen family detected" may mean "Raspberry Pi traffic detected". This experiment cannot
   separate the two.
2. **A threshold frozen on one benign capture does not hold on another.** The budget was 1 %
   window FPR on validation. In 3 of the 12 folds that found a threshold, FPR on the unseen
   benign capture was 12.6 % or 63.1 %, and all three tested Honeypot-5-1. KAN-18 left
   threshold transfer as an untested hypothesis; this measures it for window FPR on these
   captures, and it failed.
3. **Calibration itself fails in 6 of 18 folds.** No threshold kept validation FPR at or below
   1 %. The failures had Honeypot-5-1 (4 folds) or Honeypot-7-1 (2 folds) as the validation
   benign capture. Which training combination causes this was not isolated.
4. **There is no stable operating point.** Across folds the selected threshold ranges from
   0.055 to 0.95, so nothing here supports freezing one runtime threshold from IoT-23
   validation data.
5. **The benign-coverage effect from KAN-18 reappears under different splits.** At 0.5, benign
   FPR reaches 0.958 and 0.807. Both folds trained on Mirai with one benign capture.
6. **Benign windows inside the infected capture.** Mirai's own capture contains 930 benign
   windows, and 2.3–2.6 % of them are flagged. They come from the infected device, so this is
   not the benign-device FPR above.

## Uncertainty and confounds

- **One capture per family.** Family, capture, device, network and recording date are a single
  variable here.
- **One capture per group in each test part.** The capture-bootstrap intervals in
  `holdout_report.json` collapse to a point or span the whole range, so they are not reported
  as confidence intervals.
- **Declared label.** Honeypot-7-1's benign label is declared rather than measured (ADR-0004).
  Folds that train or validate on it inherit that assumption.
- **One seed.** The variation reported comes from the folds, not from RF seeds.
- **Windows, not quarantine decisions.** N-consecutive behaviour, false quarantine per
  device-hour and benign blocked time belong to KAN-51.

## Consequences

- No G5 claim. This is evidence for ADR-0004's proposed second benign source and for the
  KAN-20 device-identity check, not a detector result.
- Do not freeze a runtime threshold from IoT-23 validation alone. Point 2 shows it does not
  carry over to another benign device.
- Next useful test, after ADR-0004 approval: train benign on UNSW-IoTraffic and repeat these
  folds. If recall on Raspberry Pi malware stays high while benign FPR on unseen devices falls,
  the device-type shortcut becomes less likely. If benign FPR stays high, the problem is benign
  coverage rather than the threshold.
