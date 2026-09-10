from core.schema import FeatureVector

STUB_FEATURE_VERSION = "stub-0.1"
STUB_FEATURE_ORDER = ("stub_packet_count", "stub_l3_bytes")


def fake_features(device_id: str = "fixture-device", window_start: float = 0) -> FeatureVector:
    return FeatureVector(
        device_id,
        window_start,
        window_start + 5,
        STUB_FEATURE_VERSION,
        STUB_FEATURE_ORDER,
        (10.0, 600.0),
    )
