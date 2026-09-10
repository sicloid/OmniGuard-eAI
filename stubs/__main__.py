import json

from stubs.fake_detector import FakeDetector
from stubs.fake_features import fake_features
from stubs.fake_telemetry import fake_telemetry


def main() -> None:
    detector = FakeDetector()
    scores = [detector.predict(fake_features(window_start=i * 5)).score for i in range(5)]
    print(
        json.dumps(
            {
                "mode": "synthetic-contract-smoke-only",
                "scores": scores,
                "events": [payload.to_dict() for payload in fake_telemetry()],
                "g8_passed": False,
                "g10_passed": False,
            },
            allow_nan=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
