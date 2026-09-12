# R1 — Onur

Next: model artifact metadata and fail-fast compatibility tests, capture-aware
train/validation/test split, RF baseline, validation-only threshold calibration.
Use the future shared `core/features.py` for both offline and live inputs.
Do not train on `stub-0.1` or report synthetic tests as ML results.
Large datasets and model binaries stay outside Git. See `SCHEMA.md`.

## V3 design follow-up

V3 önceliği: eğitimden önce capture topolojisi/yönü ve device-window etiket
uygunluğunu denetleyin; hazır CSV/live feature eşitliği varsaymayın. Basit rate
kuralını karşılaştırmaya alın; yanlış karantina/device-hour ölçümünü de planlayın.
[Uygulama sırası](../docs/architecture/EXECUTION_V3.md).
