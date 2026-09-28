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


def _key_values(path: Path) -> dict[str, int]:
    result = {}
    for line in _read(path).splitlines():
        key, value = line.split()
        result[key] = int(value)
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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


def run(
    command: list[str],
    output: Path,
    root: Path = Path("/sys/fs/cgroup"),
    *,
    inputs: list[Path] | None = None,
    container_image_digest: str | None = None,
    workload_scope: str = "unspecified command",
) -> int:
    if resource is None:
        raise RuntimeError("controlled cgroup benchmark requires Linux resource accounting")
    limits = read_limits(root)
    started_utc_ns = time.time_ns()
    started = time.monotonic_ns()
    cpu_before = _key_values(root / "cpu.stat")
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    completed = subprocess.run(command, check=False)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_after = _key_values(root / "cpu.stat")
    ended = time.monotonic_ns()
    cpu_delta = {
        key: cpu_after.get(key, 0) - cpu_before.get(key, 0)
        for key in sorted(cpu_after.keys() | cpu_before.keys())
    }
    input_records = [
        {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in (inputs or [])
    ]
    report = {
        "schema": "omniguard.compute-budget/2",
        "claim": "controlled compute budget; not router emulation",
        "command": command,
        "limits": limits,
        "cgroup_observation": {
            "cpu_stat_delta": cpu_delta,
            "memory_peak_bytes": int(_read(root / "memory.peak")),
            "memory_events": _key_values(root / "memory.events"),
        },
        "provenance": {
            "container_image_digest": container_image_digest,
            "inputs": input_records,
            "workload_scope": workload_scope,
        },
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
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--container-image-digest")
    parser.add_argument("--workload-scope", default="unspecified command")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")
    return run(
        command,
        args.output,
        inputs=args.input,
        container_image_digest=args.container_image_digest,
        workload_scope=args.workload_scope,
    )


if __name__ == "__main__":
    raise SystemExit(main())
