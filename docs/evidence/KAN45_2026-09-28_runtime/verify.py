"""Recompute the KAN-45 runtime-budget comparison from the committed raw files.

    python docs/evidence/KAN45_2026-09-28_runtime/verify.py

Checks every file against `SHA256SUMS`, confirms both runs used this checkout's code,
that the budgeted run's sealed limits are finite and the unbudgeted run's are not,
that each manifest carries the stage file its core wrote, and prints the comparison.
Exits nonzero if any check fails.
"""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = {"unbudgeted": False, "budget-0.5cpu-256m": True}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run(name: str, budgeted: bool) -> tuple[dict, list[str]]:
    directory = HERE / name
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    measured = manifest["measurements"]
    lab = directory / "lab"
    limits = manifest["config"]["cgroup"]
    during = measured["cgroup"]["during_lab"]
    drift = sorted(
        path
        for path, digest in manifest["config"]["code_sha256"].items()
        if sha256(ROOT / path) != digest
    )
    checks = {
        "status_completed": manifest["status"] == "completed",
        "code_is_this_checkout": drift == [],
        "worktree_was_clean": (directory / "worktree-status").read_text().strip() == "",
        "sealed_budget_matches_declaration": limits.get("budgeted") is budgeted,
        "stage_summary_is_the_core_file": measured["stages_sha256"] == sha256(lab / "stages.json"),
        "no_oom": during["memory_events"].get("oom_kill", 0) == 0,
        "no_kernel_drops": measured["stages"]["counters"]["kernel_packet_drops"] == 0,
        "sinks_blocked": "blocked tcp=0 udp=0" in manifest["provenance"]["r2"]["sink_evidence"],
    }
    stages = measured["stages"]["stages"]
    report = {
        "run_id": manifest["run_id"],
        "limits": limits,
        "cgroup_during_lab": during,
        "stages_ms": {
            stage: {
                "passes": stages[stage]["passes"],
                "elapsed_total": round(stages[stage]["elapsed_seconds_total"] * 1e3, 3),
                "elapsed_max": round(stages[stage]["elapsed_seconds_max"] * 1e3, 3),
                "thread_cpu": round(stages[stage]["thread_cpu_seconds"] * 1e3, 3),
            }
            for stage in ("inference", "enforcer", "features", "policy", "exporter", "capture")
        },
        "checks": checks,
        "code_drift": drift,
    }
    return report, [f"{name}: {check}" for check, ok in checks.items() if not ok]


def main() -> int:
    failures = []
    for line in (HERE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        if sha256(HERE / name) != digest:
            failures.append(f"hash mismatch: {name}")
    runs = {}
    for name, budgeted in RUNS.items():
        runs[name], failed = verify_run(name, budgeted)
        failures += failed
    print(json.dumps({"runs": runs, "failures": failures}, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
