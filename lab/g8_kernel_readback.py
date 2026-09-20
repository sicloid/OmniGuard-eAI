"""Read owned kernel quarantine state after controller death without mutating it."""

import json
import time

from gateway.enforcer import DeviceBinding, NftEnforcer


def main() -> None:
    active = NftEnforcer().is_quarantined(DeviceBinding("camera", "10.203.1.2"))
    print(json.dumps({"mono_ns": time.monotonic_ns(), "kernel_quarantined": active}))


if __name__ == "__main__":
    main()
