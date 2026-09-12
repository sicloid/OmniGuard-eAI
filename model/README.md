# R1 — Onur

Next: capture-aware train/validation/test split, RF baseline,
validation-only threshold calibration.
Use the shared `core/features.py` for both offline and live inputs.
Do not train on `stub-0.1` or report synthetic tests as ML results.
Large datasets and model binaries stay outside Git. See `SCHEMA.md`.

## KAN-9: model artifact contract

`model/artifact.py` implements the `SCHEMA.md` artifact contract. An artifact is
a directory holding `model.joblib` and `model.meta.json`:

| Field | Meaning |
|---|---|
| `meta_format` | `omniguard-model-meta/1`; any other value is rejected |
| `model_id`, `model_version` | identity copied into every `DetectionResult` |
| `schema_version` | runtime contract version; must equal `core.schema.SCHEMA_VERSION` |
| `feature_schema_version`, `feature_order` | extractor catalogue the model was trained on |
| `window_seconds`, `window_semantics` | `5`, `half-open-epoch-aligned` |
| `threshold` | validation-selected, in [0, 1] |
| `model_sha256` | SHA-256 of `model.joblib` |
| `training_manifest_sha256` | SHA-256 of the training/split manifest (KAN-17) |
| `python_version`, `sklearn_version`, `numpy_version` | producing environment |

`load_model(dir, expected_model_sha256=..., expected_metadata_sha256=...)` fails fast, in this order, and
deserializes nothing unless every step passes:

1. strict JSON: exact field set, no duplicate keys, no NaN/Infinity, typed values;
2. SHA-256 of the exact metadata bytes equals the trusted deployment metadata pin;
   the model hash declared inside the metadata also equals the deployment model pin;
3. runtime compatibility: schema, window, Python major.minor, exact scikit-learn
   and numpy (scikit-learn only supports unpickling with the saving version), and
   optionally the extractor's feature version/order;
4. the model bytes, read once into memory, hash to the pinned value;
5. only then are those same bytes passed to `joblib.load`.

All failures raise an `ArtifactError` subclass. Callers must treat that as "no
model", never as a NORMAL decision. Hashing does not make a pickle safe: load only
artifacts produced locally by this team, and pin the hash outside the artifact
directory. Both model and metadata pins must be recorded during trusted artifact
publication. Never calculate the expected metadata hash from the candidate file at
load time: that would let changed thresholds or feature order bypass the check.
Call `load_model` only from a process without capture, firewall or
other elevated privileges; that isolation belongs to runtime orchestration. `build_metadata` + `write_metadata` are the producer side for KAN-18.

KAN-10 provides `requirements-ml.lock` for the scientific stack. Artifact unit
tests inject the deserializer; RF round-trip tests use the actual locked libraries:
`.venv/bin/python -m unittest discover -s tests -p test_artifact.py -v`.
They prove contract behavior, not model quality.

## V3 design follow-up

V3 önceliği: eğitimden önce capture topolojisi/yönü ve device-window etiket
uygunluğunu denetleyin; hazır CSV/live feature eşitliği varsaymayın. Basit rate
kuralını karşılaştırmaya alın; yanlış karantina/device-hour ölçümünü de planlayın.
[Uygulama sırası](../docs/architecture/EXECUTION_V3.md).
