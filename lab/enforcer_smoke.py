"""KAN-31 real NftEnforcer lease/restart smoke inside the owned Linux lab."""

import argparse
import subprocess
import sys
import time

from gateway.enforcer import DeviceBinding, EnforcementAction, NftEnforcer

BINDING = DeviceBinding("lab-camera", "10.203.1.2")


def status(expected: str) -> int:
    active = NftEnforcer().is_quarantined(BINDING)
    wanted = expected == "active"
    if active != wanted:
        raise RuntimeError(f"expected kernel quarantine {expected}, observed active={active}")
    return 0


def child(mode: str, *extra: str) -> None:
    subprocess.run(
        [sys.executable, __file__, mode, *extra],
        check=True,
        timeout=5,
    )


def orchestrate() -> int:
    enforcer = NftEnforcer()
    enforcer.release(BINDING)

    receipt = enforcer.quarantine(BINDING, lease_seconds=1.0, max_lease_seconds=2.0)
    if receipt.action is not EnforcementAction.APPLIED:
        raise RuntimeError(f"expected APPLIED, got {receipt.action}")
    child("status", "active")

    # No userspace process renews or releases this one-second lease.
    time.sleep(1.3)
    child("status", "inactive")

    receipt = enforcer.quarantine(BINDING, lease_seconds=10.0, max_lease_seconds=10.0)
    if receipt.action is not EnforcementAction.APPLIED:
        raise RuntimeError(f"expected fresh APPLIED, got {receipt.action}")
    child("release")
    child("status", "inactive")

    print("PASS: NftEnforcer apply/readback, fresh-process observation, kernel expiry and release")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("run", "status", "release"), nargs="?", default="run")
    parser.add_argument("expected", choices=("active", "inactive"), nargs="?")
    args = parser.parse_args()

    if args.mode == "run":
        return orchestrate()
    if args.mode == "status":
        if args.expected is None:
            parser.error("status requires active|inactive")
        return status(args.expected)

    NftEnforcer().release(BINDING)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
