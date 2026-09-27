"""Run a command inside an already constrained cgroup v2 and seal the evidence.

The launcher (Docker, systemd-run or a lab operator) owns limit creation.  This
module verifies the limits visible to the process and refuses to call an
unlimited host run a controlled-compute result.
"""

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

try:
    import resource
except ImportError:  # Windows imports the contract but cannot run Linux cgroups.
    resource = None


def _read(path: Path) -> str:
    return path.read_text().strip()


def read_limits(root: Path = Path("/sys/fs/cgroup")) -> dict[str, object]:
    controllers = set(_read(root / "cgroup.controllers").split())
    if not {"cpu", "memory"}.issubset(controllers):
        raise RuntimeError("cgroup v2 cpu and memory controllers are required")
    cpu_raw = _read(root / "cpu.max").split()
    memory_raw = _read(root / "memory.max")
    if len(cpu_raw) != 2:
        raise RuntimeError("invalid cpu.max")
    quota, period = cpu_raw
    if quota == "max" or memory_raw == "max":
        raise RuntimeError("controlled benchmark requires finite cpu.max and memory.max")
    quota_us, period_us, memory_bytes = int(quota), int(period), int(memory_raw)
    if min(quota_us, period_us, memory_bytes) <= 0:
        raise RuntimeError("cgroup limits must be positive")
    return {
        "cgroup_version": 2,
        "cpu_quota_us": quota_us,
        "cpu_period_us": period_us,
        "cpu_cores": quota_us / period_us,
        "memory_max_bytes": memory_bytes,
    }


def run(command: list[str], output: Path, root: Path = Path("/sys/fs/cgroup")) -> int:
    if resource is None:
        raise RuntimeError("controlled cgroup benchmark requires Linux resource accounting")
    limits = read_limits(root)
    started_utc_ns = time.time_ns()
    started = time.monotonic_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    completed = subprocess.run(command, check=False)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    ended = time.monotonic_ns()
    report = {
        "schema": "omniguard.compute-budget/1",
        "claim": "controlled compute budget; not router emulation",
        "command": command,
        "limits": limits,
        "started_utc_ns": started_utc_ns,
        "duration_ns": ended - started,
        "child_cpu_seconds": (after.ru_utime + after.ru_stime)
        - (before.ru_utime + before.ru_stime),
        "child_max_rss_kib": after.ru_maxrss,
        "exit_code": completed.returncode,
    }
    encoded = json.dumps(report, indent=2, sort_keys=True).encode() + b"\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encoded)
    (output.with_suffix(output.suffix + ".sha256")).write_text(
        f"{hashlib.sha256(encoded).hexdigest()}  {output.name}\n"
    )
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    return run(command, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
