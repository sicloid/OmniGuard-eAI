# KAN-69 domain-augmented candidate experiment — 28 September 2026

This is a recorded negative development result. It does not authorize runtime
adoption.

The protocol was committed before training. It combined each seed's IoT-23
training groups with 39 device-disjoint CICIoT2023 development-only benign
groups. Nine other CIC development devices formed a domain-validation role.
The 11-device CIC one-shot holdout, IoT-23 test groups and fresh Raspberry Pi
capture were explicitly forbidden and were not scored.

Thresholds maximized IoT-23 validation recall while requiring separate window
FPR budgets of at most 1% on IoT-23 benign validation and CIC domain validation.

| Candidate family | Worst-seed IoT-23 validation recall | Mean recall | Worst-seed CIC domain-validation FPR |
|---|---:|---:|---:|
| ExtraTrees-256 augmented | 82.74% | 93.85% | 1.000% |
| ExtraTrees-128 augmented | 81.38% | 90.85% | 1.000% |
| RandomForest-128 augmented | 42.81% | 60.49% | 0.884% |

The predeclared winner, ExtraTrees-256, is worse on worst-seed recall than the
existing non-augmented ExtraTrees candidate (99.16%). Adding a large amount of
external benign data therefore did not dominate the existing candidate. The
augmented model is rejected rather than promoted from its favourable benign
source metric.

`report.json` records every seed, split, threshold, source-specific FPR, recall,
fit duration and artifact hash. Model binaries stay outside Git. `SHA256SUMS`
pins the report and the exact pre-run spec.
