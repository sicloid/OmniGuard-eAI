"""Recompute the KAN-42 figures from the committed raw files.

Run from the repository root:

    python docs/evidence/KAN42_2026-09-24/verify.py

For each run it checks the SHA-256 index, reads the closed manifest, confirms that the
stage summary in the manifest is the stage file the core wrote, re-derives t0 from the
replay's own clock mapping, re-hashes both sink logs against the sink evidence, and
prints the per-stage table. Run 2's sealed code hashes must match this checkout; run 1
used the harness before the CPU-window fix and is expected to differ in
`measure/stages.py` only. Exits nonzero if any check fails.
"""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = {"run1-801b8c1": {"measure/stages.py"}, "run2-d73e833": set()}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(name: str, expected_code_drift: set[str]) -> tuple[dict, list[str]]:
    directory = HERE / name
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    lab = directory / "lab"
    stages_file = json.loads((lab / "stages.json").read_text(encoding="utf-8"))
    measured = manifest["measurements"]
    replay = json.loads(next(lab.glob("replay-runs/*/manifest.json")).read_text(encoding="utf-8"))
    mapping, t0 = replay["clock_mapping"], replay["reference_t0"]
    middle = (mapping["monotonic_before_ns"] + mapping["monotonic_after_ns"]) // 2
    t0_unix = (mapping["utc_ns"] + (t0["send_begin_ns"] - middle)) / 1e9
    sink = manifest["provenance"]["r2"]["sink_evidence"]
    drift = {
        path
        for path, digest in manifest["config"]["code_sha256"].items()
        if sha256(ROOT / path) != digest
    }
    checks = {
        "manifest_format_is_2": manifest["manifest_format"] == "omniguard-experiment-manifest/2",
        "status_completed": manifest["status"] == "completed",
        "r2_observed_at_close": manifest["provenance"]["r2_observation_phase"] == "at-close",
        "stage_summary_is_the_core_file": measured["stages"] == stages_file
        and measured["stages_sha256"] == sha256(lab / "stages.json"),
        "core_log_is_the_one_closed": measured["core_jsonl_sha256"] == sha256(lab / "core.jsonl"),
        "t0_rederived_from_replay": abs(manifest["provenance"]["r2"]["t0_unix"] - t0_unix) < 1e-6,
        "t0_inside_run_window": manifest["started_at_unix"]
        <= t0_unix
        <= manifest["closed_at_unix"],
        "tcp_sink_hash_matches": sha256(lab / "tcp-sink.log") in sink,
        "udp_sink_hash_matches": sha256(lab / "udp-sink.log") in sink,
        "sinks_blocked": "blocked tcp=0 udp=0" in sink,
        "no_kernel_drops": measured["stages"]["counters"]["kernel_packet_drops"] == 0,
        "no_failed_stage": measured["stages"]["failed_stages"] == [],
        "code_drift_is_the_declared_one": drift == expected_code_drift,
        "worktree_was_clean": (directory / "worktree-status").read_text().strip() == "",
    }
    table = {
        stage: {
            "passes": v["passes"],
            "elapsed_ms_total": round(v["elapsed_seconds_total"] * 1e3, 3),
            "elapsed_ms_max": round(v["elapsed_seconds_max"] * 1e3, 3),
            "thread_cpu_ms": round(v["thread_cpu_seconds"] * 1e3, 3),
            "process_cpu_ms": round(v["process_cpu_seconds"] * 1e3, 3),
            "overhead_ms": round(v["measurement_overhead_seconds"] * 1e3, 3),
        }
        for stage, v in measured["stages"]["stages"].items()
    }
    report = {
        "run_id": manifest["run_id"],
        "commit": (directory / "commit").read_text().strip(),
        "checks": checks,
        "code_drift_from_this_checkout": sorted(drift),
        "stages": table,
        "peak_rss_mb": round(
            max(v["peak_rss_bytes"] for v in measured["stages"]["stages"].values()) / 2**20, 1
        ),
        "not_supplied": manifest["provenance"]["not_supplied"],
    }
    return report, [f"{name}: {check}" for check, ok in checks.items() if not ok]


def main() -> int:
    failures = []
    for line in (HERE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        if sha256(HERE / name) != digest:
            failures.append(f"hash mismatch: {name}")
    runs = {}
    for name, drift in RUNS.items():
        runs[name], failed = verify_run(name, drift)
        failures += failed
    print(json.dumps({"runs": runs, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
