"""KAN-48 dedicated Linux proof using deterministic stubs and the real nft enforcer."""

import json

from gateway.controller import StateEnforcementController
from gateway.detector import CheckedDetector, DetectorSpec
from gateway.enforcer import DeviceBinding, NftEnforcer
from gateway.policy import DevicePolicy
from stubs.fake_detector import FakeDetector
from stubs.fake_features import STUB_FEATURE_ORDER, STUB_FEATURE_VERSION, fake_features


def main() -> int:
    detector = CheckedDetector(
        FakeDetector(scores=(0.9, 0.9), threshold=0.5),
        DetectorSpec(
            "STUB-NOT-TRAINED",
            "0.1",
            STUB_FEATURE_VERSION,
            STUB_FEATURE_ORDER,
            0.5,
        ),
    )
    policy = DevicePolicy("lab-camera", n=2, lease_seconds=10.0, max_lease=20.0)
    binding = DeviceBinding("lab-camera", "10.203.1.2")
    enforcer = NftEnforcer()
    controller = StateEnforcementController(detector, policy, enforcer, binding)

    enforcer.release(binding)
    first = controller.process(fake_features("lab-camera", 100), now=105, mono=105)
    if enforcer.is_quarantined(binding):
        raise RuntimeError("N=2 quarantined after only one anomaly")

    second = controller.process(fake_features("lab-camera", 105), now=110, mono=110)
    if not enforcer.is_quarantined(binding):
        raise RuntimeError("nth anomaly did not create the nft quarantine element")

    released = controller.release(now=111, mono=111)
    if enforcer.is_quarantined(binding):
        raise RuntimeError("explicit release did not remove the nft quarantine element")

    print(
        json.dumps(
            {
                "first_state": policy_state(first),
                "second_state": policy_state(second),
                "second_receipt": second.receipts[-1].action.value,
                "release_receipt": released.receipts[-1].action.value,
                "kernel_after_release": False,
            },
            sort_keys=True,
        )
    )
    return 0


def policy_state(step) -> str:
    return step.events[-1].new_state.value if step.events else "UNCHANGED"


if __name__ == "__main__":
    raise SystemExit(main())
