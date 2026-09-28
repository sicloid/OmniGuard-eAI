# KAN-54 results freeze inventory — final preparation, updated 28 September 2026

**Status: freeze inputs complete; immutable manifest is generated from the clean
decision commit.** The declaration is `G13_FREEZE_DECLARATION.json`. The
[reproduction guide](REPRODUCE.md) explains how to regenerate each path.

## Existing byte-pinned inputs

| Input | SHA-256 or recorded identity | Scope |
|---|---|---|
| KAN-19 `model.joblib` (external to Git) | `d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b` | Frozen seed-1 operating model; verify the actual binary before loading. |
| `model/frozen/kan19-seed1/model.meta.json` | `917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad` | Feature schema, model version and threshold. |
| `model/frozen/kan19-seed1/threshold.policy.json` | `4a9491b5ce0be6a5225ce8f0e0b4d72022e67a62ba38c6cf62aeb051acc7bcdb` | Validation-only 1% window-FPR budget; not external FPR. |
| `model/frozen/kan19-seed1/split.manifest.json` | `b4abc85f8a2d5f00be0789327d2a76e331399396a50c9dcbd289ff222f56be67` | Development capture split. |
| KAN-19 development `windows.jsonl` (external) | `4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625` | Same windows in the v1/v2 packs; manifest version must be named separately. |
| Supplied v2 `manifest.json` (external) | `8ea8c310d6b66a82515a693e5347da274a622146e5347e381f11c4f80821d2a7` | `window-label-1` pack metadata used for the 20 September clean-checkout training replay; verifying this hash does not re-extract six source PCAPs. |
| `model/frozen/kan20/ablation_report.json` | `4c85add98f2af26fe38e9dbae69b7bc8b32977e13384b3ae19277b3246ca6d87` | Development validation ablation; Mac timing ranks sets, not gateway/Pi cost. |
| `data/holdout/selection.json` | `7e12f6a0bed01b0c32c1914490e9662b481c2f9ac04c3fa7273c8d3302860890` | Holdout selection definition, not a scored holdout result. |
| `model/frozen/kan51/nlease_report.json` | `6d5d934d8666cc725dcc1f3a9a39caf6dc13fef60efbde0c366d4baa0f434e9a` | Corrected validation grid; N = 2 and lease = 300 s were accepted by the Lead. |
| `model/nlease_spec.json` | `4d00461aed16177719f679887d7639d13bdf0f7d568f0e4363388b1ce1baf71d` | Original pre-run spec bytes. Its historical status text predates the Lead decision; use ADR-0004 decision 7b for the later freeze. Do not rewrite this file and break the run provenance. |

The KAN-21 fold report in [KAN21_HOLDOUT.md](KAN21_HOLDOUT.md) is an
unseen-family experiment on the already-used IoT-23 source. It reports failures
to meet the validation budget and transfer FPR up to 63.1%; it must not be
silently relabelled as the untouched final holdout or omitted from limitations.
The G8 development-validation replay is an integration observation of a
transformed 8-1 capture, not an accuracy or FPR estimate.
The clean-checkout v2 policy replay reproduced the seed-1 threshold
`0.9798815486832`, but its new model binary hash was
`4b6b87dba1a48d450689bfb0ec1e6c2b4a71068150489604380c2759420d1591`,
not the frozen binary hash above. Do not substitute that replay artifact for
the pinned operating model or call its identical threshold a byte-identical
model reproduction.

## Inputs resolved for the final freeze

1. KAN-52 retains the declared false-quarantine/leakage report, censored reasons
   and uncertainty limitations.
2. KAN-42/43/45 real-run manifests and bounded compute/telemetry measurements
   are retained under `docs/evidence`.
3. G8 and G10 raw/validated bundles are retained separately from synthetic demo
   evidence.
4. Both the performance-invalid constrained Pi run and the accepted fresh
   benign Pi run are retained; no laptop value is substituted for Pi timing.
5. The runtime profile pins the selected model, metadata, threshold, N and lease.
   Adverse external-transfer and rejected augmentation results remain included.

KAN-60 must use the generated immutable set rather than a later hand-picked
subset. KAN-59's actual three-person rehearsal remains an organisational gate,
not a missing measurement file.

## Freeze mechanism

`python -m measure.result_freeze create` now builds the final inventory from an
explicit declaration and one or more selected files/directories. It refuses a
dirty repository, paths outside the repository, symlinks, an empty selection
and an existing output. The manifest records the exact Git commit, declaration
content/hash, and every selected file's relative path, byte length and SHA-256.
`python -m measure.result_freeze verify` rechecks those bytes before the demo or
release. The final command will be executed only after the Pi comparison and
model decision are committed and the exact release candidate is clean.
