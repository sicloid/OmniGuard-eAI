"""Validate disposable RF wiring smoke against independent sink timestamps."""

import json
import sys
from pathlib import Path


def _times(path: Path) -> list[int]:
    return [int(line) for line in path.read_text().splitlines() if line.strip()]


def main() -> int:
    root = Path(sys.argv[1])
    records = [json.loads(line) for line in (root / "core.jsonl").read_text().splitlines()]
    ready = next(record for record in records if record["kind"] == "ready")
    if ready["model_id"] != "SYNTHETIC-WIRING-NOT-G8":
        raise RuntimeError("smoke did not use its labelled synthetic artifact")
    actions = [
        record
        for record in records
        if record["kind"] == "kernel_receipt"
        and record["action"] in ("APPLIED", "RELEASED", "ALREADY_RELEASED")
    ]
    applied = next(record for record in actions if record["action"] == "APPLIED")
    released = next(
        record
        for record in actions
        if record["action"] in ("RELEASED", "ALREADY_RELEASED")
        and record["mono_ns"] > applied["mono_ns"]
    )
    summary = next(record for record in records if record["kind"] == "summary")
    if not (summary["windows"] >= 1 and summary["quarantines"] >= 1):
        raise RuntimeError("real extractor/RF/state path did not quarantine")
    if summary["capture_stats"]["kernel_drops"] or summary["kernel_quarantined"]:
        raise RuntimeError("capture lost packets or kernel block remained after release")
    # Kernel TTL can expire before the controller's next readback. In that case
    # ALREADY_RELEASED proves absence; traffic may resume slightly before tick.
    blocked_end = min(
        released["mono_ns"] - 100_000_000,
        applied["mono_ns"] + int(ready["lease_seconds"] * 1_000_000_000) - 100_000_000,
    )
    result = {}
    for protocol in ("udp", "tcp"):
        times = _times(root / f"{protocol}-sink.log")
        before = sum(t < applied["mono_ns"] for t in times)
        blocked = sum(applied["mono_ns"] + 300_000_000 < t < blocked_end for t in times)
        after = sum(t > released["mono_ns"] + 300_000_000 for t in times)
        if before < 3 or blocked or after < 3:
            raise RuntimeError(
                f"{protocol} sink did not show baseline/stop/restore: "
                f"before={before}, blocked={blocked}, after={after}"
            )
        result[protocol] = {"before": before, "blocked": blocked, "after": after}
    print(
        json.dumps(
            {"synthetic_only_not_g8": True, "sink": result, "summary": summary}, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
