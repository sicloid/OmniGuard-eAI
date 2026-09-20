# KAN-54 results freeze inventory — preparation, 20 September 2026

**Status: not frozen.** This inventory names evidence that already has stable
bytes and the measurements still missing for G13. It is not the G13 result set,
a release manifest, or permission to choose a policy after seeing holdout data.
The [reproduction guide](REPRODUCE.md) explains how to regenerate each path.

## Existing byte-pinned inputs

| Input | SHA-256 or recorded identity | Scope |
|---|---|---|
| KAN-19 `model.joblib` (external to Git) | `d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b` | Frozen seed-1 operating model; verify the actual binary before loading. |
| `model/frozen/kan19-seed1/model.meta.json` | `917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad` | Feature schema, model version and threshold. |
| `model/frozen/kan19-seed1/threshold.policy.json` | `4a9491b5ce0be6a5225ce8f0e0b4d72022e67a62ba38c6cf62aeb051acc7bcdb` | Validation-only 1% window-FPR budget; not external FPR. |
| `model/frozen/kan19-seed1/split.manifest.json` | `b4abc85f8a2d5f00be0789327d2a76e331399396a50c9dcbd289ff222f56be67` | Development capture split. |
| KAN-19 development `windows.jsonl` (external) | `4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625` | Same windows in the v1/v2 packs; manifest version must be named separately. |
| `model/frozen/kan20/ablation_report.json` | `4c85add98f2af26fe38e9dbae69b7bc8b32977e13384b3ae19277b3246ca6d87` | Development validation ablation; Mac timing ranks sets, not gateway/Pi cost. |
| `data/holdout/selection.json` | `7e12f6a0bed01b0c32c1914490e9662b481c2f9ac04c3fa7273c8d3302860890` | Holdout selection definition, not a scored holdout result. |

The KAN-21 fold report in [KAN21_HOLDOUT.md](KAN21_HOLDOUT.md) is an
unseen-family experiment on the already-used IoT-23 source. It reports failures
to meet the validation budget and transfer FPR up to 63.1%; it must not be
silently relabelled as the untouched final holdout or omitted from limitations.
The G8 development-validation replay is an integration observation of a
transformed 8-1 capture, not an accuracy or FPR estimate.

## Missing before G13 can pass

1. **KAN-52:** the declared main false-quarantine/FPR and containment-leakage
   experiment, including all misses, censored runs, source-attempt windows,
   benign interruption and interval uncertainty. This card was `Yapılacaklar`
   on 20 September; no final plot can be invented from the G8 lab probe.
2. **KAN-51 and KAN-42/43/45 as applicable:** policy N/lease, real-run manifests,
   stage costs and telemetry volume with complete provenance. A blank field is
   missing, not zero. Freeze only figures whose accepted runs exist.
3. **KAN-49 and KAN-50:** independent owner review of real G8 and real
   StateEvent→UDS→MQTT→PostgreSQL→Grafana G10. CI, Compose health and seeded
   dashboards have narrower scope.
4. **KAN-53:** a separate Pi 5/ARM64 run only if actual hardware and KAN-46
   load/throttle evidence exist; never copy a laptop number into that column.
5. **Final inventory:** exact Git commit, hashes of every input/output and plot,
   run IDs, environment/image/package versions, clock/boot mapping, declared
   data role, threshold/N/lease and reviewer decision. Include failed or
   incomplete runs and reasons. Record the set *before* drawing summary plots.

KAN-54 remains `Yapılacaklar` until these inputs are accepted and a frozen
manifest/plot set is produced. KAN-60 must use that exact frozen set, not a
later hand-picked subset.
