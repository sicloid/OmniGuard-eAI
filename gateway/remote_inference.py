"""Optional FastAPI comparison surface; the production gateway stays local."""

from core.schema import FeatureVector


def decode_vector(payload: dict) -> FeatureVector:
    expected = {
        "device_id",
        "window_start",
        "window_end",
        "feature_schema_version",
        "feature_order",
        "values",
    }
    if type(payload) is not dict or set(payload) != expected:
        raise ValueError("request must contain exactly the FeatureVector fields")
    return FeatureVector(
        payload["device_id"],
        payload["window_start"],
        payload["window_end"],
        payload["feature_schema_version"],
        tuple(payload["feature_order"]),
        tuple(payload["values"]),
    )


def predict_payload(detector, payload: dict) -> dict:
    result = detector.predict(decode_vector(payload))
    return {
        "device_id": result.device_id,
        "window_ts": result.window_ts,
        "model_id": result.model_id,
        "model_version": result.model_version,
        "score": result.score,
        "classification": result.classification.value,
        "threshold": result.threshold,
    }


def create_app(detector):
    """Build an optional comparison app without changing the local runtime path."""
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:
        raise RuntimeError("install the remote comparison dependencies") from exc

    app = FastAPI(title="OmniGuard remote inference comparison", version="0.1.0")

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "mode": "comparison-only"}

    @app.post("/v1/predict")
    async def predict(payload: dict):
        try:
            return predict_payload(detector, payload)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return app
