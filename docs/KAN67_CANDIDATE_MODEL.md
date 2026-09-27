# KAN-67 exploratory candidate comparison

This is a development-validation experiment on the sealed KAN-22 sample pack. It
does not replace the frozen KAN-19 artifact and it does not constitute an unseen
holdout result. The existing malware holdout was already consumed by KAN-71.

The run used three seeds, parent-group disjoint train/validation splits, a 1%
validation FPR budget, and the already frozen N=2 / 300 s policy. No holdout was
scored and no runtime model pin was changed.

| Candidate | Worst-seed validation recall | Mean validation recall | Validation FPR budget |
|---|---:|---:|---:|
| ExtraTrees 128, regularized | 99.16% | 99.60% | met in all seeds |
| Random Forest 64, regularized | 83.66% | 90.58% | met in all seeds |
| HistGradientBoosting 100 | 35.63% | 64.11% | met in all seeds |
| Random Forest 200 reference | 26.52% | 68.99% | met in all seeds |

The exploratory ranking selects the regularized ExtraTrees candidate because it
has the strongest worst-seed and mean validation recall. A deployment-shaped
artifact was built and runtime prediction parity was checked, but
`runtime_adopted=false` remains deliberate. A reviewer must approve a new
independent holdout design before this candidate can replace the frozen model.

The result also explains why the baseline looked unstable: a single seed can
hide the weakness of an apparently reasonable model. The table is therefore a
candidate-screening result, not a claim that the system generalizes to new
benign devices. Report the validation split, seed count, FPR budget and
holdout limitation whenever these numbers are shown.

## 28 September domain-augmentation check

The downloaded CICIoT2023 benign corpus was also used in a separately frozen
development experiment. Thirty-nine CIC development devices were added only to
training and nine other development devices were used for a separate domain-FPR
budget. The protected 11-device CIC holdout, IoT-23 test and Pi were excluded.

The best augmented family, ExtraTrees-256, achieved 82.74% worst-seed IoT-23
validation recall with at most 1% FPR on each benign validation source. This is
worse than the existing candidate's 99.16% worst-seed recall, so augmentation
was rejected as a runtime replacement. The full negative result is retained in
[`KAN69_DOMAIN_AUGMENTED_2026-09-28`](evidence/KAN69_DOMAIN_AUGMENTED_2026-09-28/README.md).
