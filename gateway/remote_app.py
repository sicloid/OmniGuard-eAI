"""Uvicorn import target for the optional KAN-47 comparison service."""

import os
from pathlib import Path

from gateway.real_detector import load_pinned_rf_detector
from gateway.remote_inference import create_app


def app_from_environment():
    required = (
        "OMNIGUARD_MODEL_DIR",
        "OMNIGUARD_MODEL_SHA256",
        "OMNIGUARD_METADATA_SHA256",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"missing remote comparison environment: {', '.join(missing)}")
    detector = load_pinned_rf_detector(
        Path(os.environ["OMNIGUARD_MODEL_DIR"]),
        expected_model_sha256=os.environ["OMNIGUARD_MODEL_SHA256"],
        expected_metadata_sha256=os.environ["OMNIGUARD_METADATA_SHA256"],
    )
    return create_app(detector)


app = app_from_environment()
