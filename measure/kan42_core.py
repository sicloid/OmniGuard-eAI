"""KAN-42: the real G8 core, unchanged, with each stage timed where it actually runs.

`lab/g8_core.py` is imported and run as it is. Before it runs, the constructors it
calls are replaced — in its own module namespace only — by factories that build the
same real objects and wrap one or two of their methods in a `RunRecorder` stage:

| Stage | What is timed |
|---|---|
| `capture` | `BoundedReorderCapture.read_progress`, **including the wait for a packet** |
| `features` | `WindowFeaturePipeline.ingest` / `advance` — packet to closed-window vector |
| `inference` | `CheckedDetector.predict` on the pinned RF |
| `policy` | `DevicePolicy.observe` / `tick` / `invalidate` / `release` |
| `enforcer` | `NftEnforcer.quarantine` / `release`, i.e. the nft calls and readback |
| `exporter` | `GatewayEventBridge.submit` — the producer-side telemetry handoff |

The objects stay the real classes, so the controller's `isinstance` checks and every
code path are the shipped ones. A stage entered while the same stage is already open
on the thread (the policy calls its own `tick`) is not timed twice. The measured
cost of every reading is reported beside it by `measure.stages`.

`capture` is dominated by waiting for traffic: its elapsed time is not a cost, its
CPU is. The summary says so rather than leaving a reader to find out.

    python -m measure.kan42_core --stages-out PATH [lab.g8_core arguments...]
"""

import argparse
import functools
import json
import sys
import threading
from pathlib import Path

import lab.g8_core as g8_core
from measure.stages import RunCounters, RunRecorder

_active = threading.local()


def _timed(recorder: RunRecorder, stage: str, method):
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        open_stages = getattr(_active, "stages", set())
        if stage in open_stages:
            return method(*args, **kwargs)
        _active.stages = open_stages | {stage}
        try:
            with recorder.stage(stage):
                return method(*args, **kwargs)
        finally:
            _active.stages = open_stages

    return wrapper


def _instrumented(factory, recorder: RunRecorder, stage: str, methods: tuple[str, ...], built):
    """A drop-in for `factory` that returns the real object with `methods` timed."""

    @functools.wraps(factory)
    def build(*args, **kwargs):
        instance = factory(*args, **kwargs)
        for name in methods:
            setattr(instance, name, _timed(recorder, stage, getattr(instance, name)))
        built.append(instance)
        return instance

    return build


def instrument(recorder: RunRecorder) -> dict:
    """Swap g8_core's constructors for instrumented ones; return what was built."""
    built = {name: [] for name in ("capture", "pipeline", "detector", "policy", "enforcer")}
    built["bridge"] = []
    g8_core.BoundedReorderCapture = _instrumented(
        g8_core.BoundedReorderCapture, recorder, "capture", ("read_progress",), built["capture"]
    )
    g8_core.WindowFeaturePipeline = _instrumented(
        g8_core.WindowFeaturePipeline,
        recorder,
        "features",
        ("ingest", "advance"),
        built["pipeline"],
    )
    g8_core.load_pinned_rf_detector = _instrumented(
        g8_core.load_pinned_rf_detector, recorder, "inference", ("predict",), built["detector"]
    )
    g8_core.DevicePolicy = _instrumented(
        g8_core.DevicePolicy,
        recorder,
        "policy",
        ("observe", "tick", "invalidate", "release"),
        built["policy"],
    )
    g8_core.NftEnforcer = _instrumented(
        g8_core.NftEnforcer, recorder, "enforcer", ("quarantine", "release"), built["enforcer"]
    )
    g8_core.GatewayEventBridge = _instrumented(
        g8_core.GatewayEventBridge, recorder, "exporter", ("submit",), built["bridge"]
    )
    return built


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--stages-out", type=Path, required=True)
    ours, rest = parser.parse_known_args()
    recorder = RunRecorder()
    built = instrument(recorder)
    sys.argv = ["lab.g8_core", *rest]
    status = None
    try:
        status = g8_core.main()
        return status
    finally:
        captures = built["capture"]
        bridges = built["bridge"]
        raw = getattr(captures[0], "capture", None) if captures else None
        stats = getattr(raw, "stats", None)
        recorder.counters = RunCounters(
            kernel_packet_drops=getattr(stats, "kernel_drops", None),
            telemetry_queue_overflows=bridges[0].counters.overflowed if bridges else None,
            telemetry_events_dropped=bridges[0].counters.failures if bridges else None,
        )
        summary = recorder.summary()
        summary["core_exit"] = status
        summary["notes"] = {
            "capture": "elapsed includes waiting for packets; its CPU is the cost",
            "policy": "nested calls of an already open stage are not timed twice",
            "pipeline_queue_overflows": "g8_core has no pipeline queue; not applicable",
        }
        ours.stages_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
