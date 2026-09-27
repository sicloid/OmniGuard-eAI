"""KAN-42 sealed run: the process that owns the manifest from before the run to after it.

`ExperimentManifest` must be frozen before the first packet and closed by the object
that froze it. The measured core is a separate process in another network namespace,
so this process holds the manifest: it freezes it, signals that the run may start,
waits for the lab to finish, then closes it with what the run left behind.

Before `freeze()` it seals:

- the run configuration, the policy block and the SHA-256 of every file on the
  measured path;
- R1 provenance, copied field by field from the frozen model's own `provenance.json`
  (the mapping is `docs/KAN42_MEASUREMENT.md`'s), with `data_role: development`;
- R2 machine context read from this kernel — `boot_id`, `btime` — and a bracketed
  monotonic↔UTC calibration taken the way `lab/replay.py` takes one (UTC read between
  two monotonic reads; the half-width is sealed beside the offset).

At `close()` it adds the only two observations that cannot exist before the run:
`t0_unix`, from the replay's own clock mapping and its first `send_begin_ns`, and the
sink evidence, as the SHA-256 of both sink logs plus the lab validator's verdict.

    python -m measure.kan42_manifest --model-dir DIR --evidence DIR --out DIR
"""

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

from measure.manifest import (
    FAILED,
    POLICY_CONFIG_KEY,
    POLICY_CONFIG_VERSION,
    ExperimentManifest,
    ObservedFromR2,
    ProvenanceFromR1,
    ProvenanceFromR2,
)

ROOT = Path(__file__).resolve().parent.parent
MEASURED_PATH = (
    "measure/kan42_core.py",
    "measure/kan42_manifest.py",
    "measure/container_kan42.sh",
    "measure/stages.py",
    "measure/resources.py",
    "measure/clocks.py",
    "measure/manifest.py",
    "lab/g8_core.py",
    "lab/container_g8_iot23_probe.sh",
    "lab/replay.py",
    "gateway/runtime.py",
    "gateway/controller.py",
    "gateway/pipeline.py",
    "gateway/policy.py",
    "gateway/enforcer.py",
    "gateway/detector.py",
    "gateway/real_detector.py",
    "gateway/event_bridge.py",
    "sources/live.py",
    "sources/reorder.py",
    "core/features.py",
)
# What lab/container_g8_iot23_probe.sh passes to g8_core; sealed so the record names it.
POLICY = {
    "policy_config_version": POLICY_CONFIG_VERSION,
    "n": 1,
    "lease_seconds": 6.0,
    "max_lease": 60.0,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration() -> dict:
    before = time.monotonic_ns()
    utc = time.time_ns()
    after = time.monotonic_ns()
    return {"utc_ns": utc, "monotonic_before_ns": before, "monotonic_after_ns": after}


def offset_seconds(mapping: dict) -> float:
    middle = (mapping["monotonic_before_ns"] + mapping["monotonic_after_ns"]) // 2
    return (mapping["utc_ns"] - middle) / 1e9


def r1_from(model_dir: Path) -> ProvenanceFromR1:
    frozen = json.loads((model_dir / "provenance.json").read_text(encoding="utf-8"))
    return ProvenanceFromR1(
        pack_manifest_sha256=frozen["manifest_sha256"],
        windows_sha256=frozen["windows_sha256"],
        split_manifest_sha256=frozen["training_manifest_sha256"],
        model_sha256=frozen["model_sha256"],
        model_meta_sha256=frozen["metadata_sha256"],
        threshold_policy_sha256=frozen["threshold_policy_sha256"],
        feature_schema_version=frozen["feature_schema_version"],
        data_role="development",
    )


def r2_now(mapping: dict) -> ProvenanceFromR2:
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    btime = next(
        int(line.split()[1])
        for line in Path("/proc/stat").read_text().splitlines()
        if line.startswith("btime ")
    )
    return ProvenanceFromR2(
        boot_id=boot_id,
        boot_started_at=float(btime),
        monotonic_to_unix_offset=offset_seconds(mapping),
    )


def observed(run_id: str, evidence: Path) -> ObservedFromR2:
    replay = json.loads(next(evidence.glob("replay-runs/*/manifest.json")).read_text())
    mapping = replay["clock_mapping"]
    send_begin = replay["reference_t0"]["send_begin_ns"]
    middle = (mapping["monotonic_before_ns"] + mapping["monotonic_after_ns"]) // 2
    t0_unix = (mapping["utc_ns"] + (send_begin - middle)) / 1e9
    validation = json.loads((evidence / "validation.json").read_text())
    sinks = validation["sinks"]
    sink_evidence = (
        f"tcp-sink.log sha256={sha256(evidence / 'tcp-sink.log')}; "
        f"udp-sink.log sha256={sha256(evidence / 'udp-sink.log')}; "
        f"validator status={validation['status']}; blocked tcp={sinks['tcp']['blocked']} "
        f"udp={sinks['udp']['blocked']}; kernel_drops={validation['kernel_drops']}"
    )
    return ObservedFromR2(run_id=run_id, t0_unix=t0_unix, sink_evidence=sink_evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=24)
    args = parser.parse_args()

    run_id = "kan42-" + uuid.uuid4().hex
    mapping = calibration()
    config = {
        "card": "KAN-42",
        "pipeline": "lab/container_g8_iot23_probe.sh with lab.g8_core run by measure.kan42_core",
        "core_seconds": args.seconds,
        POLICY_CONFIG_KEY: POLICY,
        "calibration": mapping
        | {"half_width_ns": (mapping["monotonic_after_ns"] - mapping["monotonic_before_ns"]) // 2},
        "code_sha256": {name: sha256(ROOT / name) for name in MEASURED_PATH},
        "input_sha256": {
            "model.joblib": sha256(args.model_dir / "model.joblib"),
            "model.meta.json": sha256(args.model_dir / "model.meta.json"),
        },
    }
    manifest = ExperimentManifest(
        run_id,
        args.out / run_id,
        config,
        r1=r1_from(args.model_dir),
        r2=r2_now(mapping),
        notes=(
            "x86_64 Docker Desktop Linux VM, not a Raspberry Pi result. R2 machine context "
            "and the calibration were read by this run from its own kernel, following the "
            "method of lab/replay.py; host_id is not supplied (a container hostname names "
            "the container). label_rule_version is not yet published by R1."
        ),
    )
    manifest.freeze()
    (args.evidence / "manifest.frozen").write_text(run_id + "\n")
    done = args.evidence / "lab.done"
    while not done.exists():
        time.sleep(0.2)
    lab_status = done.read_text().strip()
    stages_path = args.evidence / "stages.json"
    try:
        stages = json.loads(stages_path.read_text())
        core = [
            json.loads(line) for line in (args.evidence / "core.jsonl").read_text().splitlines()
        ]
        summary = next(record for record in core if record["kind"] == "summary")
        measurements = {
            "stages": stages,
            "core_summary": summary,
            "lab_exit": lab_status,
            "stages_sha256": sha256(stages_path),
            "core_jsonl_sha256": sha256(args.evidence / "core.jsonl"),
        }
        # A lab that did not exit cleanly is closed as failed, with what it did record.
        status = "completed" if lab_status == "0" else FAILED
        manifest.close(
            measurements=measurements,
            status=status,
            r2_observed=observed(run_id, args.evidence),
        )
    except Exception as error:
        manifest.close(
            measurements={"lab_exit": lab_status}, status=FAILED, outcome={"error": repr(error)}
        )
        raise
    print(manifest.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
