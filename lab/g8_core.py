"""Run the real pinned RF core in the disposable, owned og-b namespace.

This records detector/state/kernel evidence.  Independent sink stop/restore and
the audited traffic source are separate G8 observations, not inferred here.
"""

import argparse
import json
import math
import os
import time
from dataclasses import asdict
from pathlib import Path

from core.schema import DeviceState
from gateway.controller import StateEnforcementController
from gateway.enforcer import DeviceBinding, NamespaceOwnershipVerifier, NftEnforcer
from gateway.pipeline import WindowFeaturePipeline
from gateway.policy import DevicePolicy
from gateway.real_detector import load_pinned_rf_detector
from gateway.runtime import GatewayCore
from sources.live import LiveCapture
from sources.packets import PacketNormalizer
from sources.reorder import BoundedReorderCapture

LAB_DEVICE = "camera"
LAB_IPV4 = "10.203.1.2"
LAB_NAMESPACE = "og-b"


def _in_owned_gateway_namespace() -> None:
    NamespaceOwnershipVerifier()(LAB_NAMESPACE)
    current = Path("/proc/self/ns/net").stat()
    owned = Path(f"/run/netns/{LAB_NAMESPACE}").stat()
    if (current.st_dev, current.st_ino) != (owned.st_dev, owned.st_ino):
        raise RuntimeError("run this probe inside the owned og-b network namespace")


def _record(kind: str, **fields) -> None:
    print(
        json.dumps(
            {"kind": kind, "mono_ns": time.monotonic_ns(), **fields},
            sort_keys=True,
            allow_nan=False,
        ),
        flush=True,
    )


def _record_step(step) -> None:
    if step.detection is not None:
        _record("detection", **asdict(step.detection))
    if step.detector_error is not None:
        _record("observation_loss", error=step.detector_error)
    for event in step.events:
        _record("state_event", **asdict(event))
    for receipt in step.receipts:
        _record("kernel_receipt", **asdict(receipt))


def run(args) -> int:
    if not 5 <= args.seconds <= 3600:
        raise ValueError("seconds must be in [5, 3600]")
    if not 1 <= args.n <= 5:
        raise ValueError("n must be in [1, 5]")
    if not 1 <= args.lease_seconds <= 60:
        raise ValueError("lease must be in [1, 60] seconds")
    _in_owned_gateway_namespace()
    detector = load_pinned_rf_detector(
        args.artifact_dir,
        expected_model_sha256=args.model_sha256,
        expected_metadata_sha256=args.metadata_sha256,
    )
    binding = DeviceBinding(LAB_DEVICE, LAB_IPV4)
    enforcer = NftEnforcer()
    policy = DevicePolicy(
        LAB_DEVICE,
        n=args.n,
        lease_seconds=args.lease_seconds,
        max_lease=60,
    )
    controller = StateEnforcementController(detector, policy, enforcer, binding)
    _record_step(controller.reconcile(now=time.time(), mono=time.monotonic()))
    controller.rearm()
    start = math.floor(time.time() / 5) * 5
    pipeline = WindowFeaturePipeline(start)
    runtime = GatewayCore(pipeline, controller, on_control_step=_record_step)
    normalizer = PacketNormalizer(["10.203.1.0/24"], {LAB_IPV4: LAB_DEVICE})
    windows = 0
    quarantines = 0
    deadline = time.monotonic() + args.seconds
    with LiveCapture("og-b0", normalizer, strict_order=False) as raw_capture:
        capture = BoundedReorderCapture(raw_capture)
        _record(
            "ready",
            model_id=detector.spec.model_id,
            model_version=detector.spec.model_version,
            start=start,
            threshold=detector.spec.threshold,
            n=args.n,
            lease_seconds=args.lease_seconds,
            pid=os.getpid(),
        )
        try:
            while time.monotonic() < deadline:
                cycle = runtime.poll(capture)
                for step in cycle.windows:
                    _record_step(step)
                    windows += step.detection is not None
                    quarantines += any(e.new_state == DeviceState.QUARANTINED for e in step.events)
        finally:
            if policy.state != DeviceState.NORMAL and not controller.faulted:
                _record_step(controller.release(now=time.time(), mono=time.monotonic()))
            _record(
                "summary",
                windows=windows,
                quarantines=quarantines,
                policy_rejections=policy.rejections,
                policy_resets=policy.resets,
                capture_stats=asdict(raw_capture.stats),
                reorder_stats=capture.stats,
                kernel_quarantined=enforcer.is_quarantined(binding),
            )
    return int(windows == 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--metadata-sha256", required=True)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--n", type=int, default=2)
    parser.add_argument("--lease-seconds", type=float, default=10)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
