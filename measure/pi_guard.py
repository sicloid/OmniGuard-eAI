"""Run a Pi 5 measurement with pre/post load and throttling evidence (KAN-46).

This guard cannot certify measurements on another host.  Missing sensors,
historical throttling, an overloaded host or a failed command invalidate the run.
The evidence directory is claimed once and kept even if the command fails.
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

THROTTLED = re.compile(r"\Athrottled=0x([0-9a-fA-F]+)\Z")
TEMPERATURE = re.compile(r"\Atemp=([0-9]+(?:\.[0-9]+)?)'C\Z")
MODEL_PATH = Path("/proc/device-tree/model")


def _vcgencmd(subcommand: str) -> str | None:
    try:
        result = subprocess.run(
            ["vcgencmd", subcommand], capture_output=True, text=True, timeout=5, check=False
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def probe() -> dict:
    """Read the current machine without substituting zero for missing evidence."""
    try:
        model = MODEL_PATH.read_bytes().rstrip(b"\0").decode("utf-8")
    except OSError, UnicodeError:
        model = None
    try:
        load_1m = os.getloadavg()[0]
    except OSError:
        load_1m = None
    throttle = _vcgencmd("get_throttled")
    temperature = _vcgencmd("measure_temp")
    throttle_match = THROTTLED.fullmatch(throttle) if throttle is not None else None
    temperature_match = TEMPERATURE.fullmatch(temperature) if temperature is not None else None
    return {
        "utc_ns": time.time_ns(),
        "machine": platform.machine(),
        "model": model,
        "cpu_count": os.cpu_count(),
        "load_1m": load_1m,
        "throttled_bits": int(throttle_match.group(1), 16) if throttle_match else None,
        "temperature_c": float(temperature_match.group(1)) if temperature_match else None,
    }


def assess(
    before: dict,
    after: dict,
    command_exit: int,
    *,
    max_load_per_core: float,
    max_temperature_c: float,
) -> list[str]:
    """Return all invalidation causes.  No single reason hides another."""
    reasons = []
    if before.get("machine") != "aarch64" or after.get("machine") != "aarch64":
        reasons.append("not_aarch64")
    if "Raspberry Pi 5" not in (before.get("model") or "") or before.get("model") != after.get(
        "model"
    ):
        reasons.append("not_verified_pi5")
    if command_exit != 0:
        reasons.append("command_failed")
    for phase, reading in (("before", before), ("after", after)):
        bits = reading.get("throttled_bits")
        if bits is None:
            reasons.append(f"{phase}_throttling_missing")
        elif bits != 0:
            # vcgencmd includes sticky "has occurred" bits as well as current state.
            # An already-contaminated boot cannot certify a clean measurement.
            reasons.append(f"{phase}_throttling_or_undervoltage")
        temperature = reading.get("temperature_c")
        if temperature is None:
            reasons.append(f"{phase}_temperature_missing")
        elif temperature >= max_temperature_c:
            reasons.append(f"{phase}_temperature_high")
        cores, load = reading.get("cpu_count"), reading.get("load_1m")
        if not isinstance(cores, int) or cores <= 0 or not isinstance(load, int | float):
            reasons.append(f"{phase}_load_missing")
        elif load / cores > max_load_per_core:
            reasons.append(f"{phase}_load_high")
    return reasons


def _write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, required=True, help="new, never reused evidence directory"
    )
    parser.add_argument("--max-load-per-core", type=float, required=True)
    parser.add_argument("--max-temperature-c", type=float, default=80.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or not 0 < args.max_load_per_core <= 1 or not 0 < args.max_temperature_c <= 85:
        parser.error("supply a command, max-load-per-core in (0,1] and max-temperature-c in (0,85]")
    args.out.mkdir(parents=True, exist_ok=False)
    before = probe()
    _write(args.out / "before.json", before)
    exit_code = 1
    try:
        exit_code = subprocess.run(command, check=False).returncode
    except OSError:
        exit_code = 127
    finally:
        after = probe()
        _write(args.out / "after.json", after)
        reasons = assess(
            before,
            after,
            exit_code,
            max_load_per_core=args.max_load_per_core,
            max_temperature_c=args.max_temperature_c,
        )
        _write(
            args.out / "verdict.json",
            {
                "status": "invalid" if reasons else "environment_accepted",
                "reasons": reasons,
                "command_exit": exit_code,
                "max_load_per_core": args.max_load_per_core,
                "max_temperature_c": args.max_temperature_c,
                "scope": "pre/post host guard only; measurement quality needs separate review",
            },
        )
    verdict = "invalid" if reasons else "accepted"
    print(f"Pi environment: {verdict} ({', '.join(reasons) or 'no guard violations'})")
    print(f"Evidence: {args.out}")
    return 1 if reasons else 0


if __name__ == "__main__":
    sys.exit(main())
