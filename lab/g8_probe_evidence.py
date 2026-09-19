"""Independent lab source attempts and sink deliveries on one monotonic clock."""

from pathlib import Path


def times(path: Path) -> list[int]:
    values = [int(line) for line in path.read_text().splitlines() if line.strip()]
    if values != sorted(values):
        raise ValueError(f"non-monotonic timestamps in {path.name}")
    return values


def assess_protocol(
    root: Path,
    protocol: str,
    *,
    applied_ns: int,
    blocked_begin_ns: int,
    blocked_end_ns: int,
    release_ns: int,
) -> dict:
    attempts = times(root / f"{protocol}-source.log")
    deliveries = times(root / f"{protocol}-sink.log")
    before = sum(value < applied_ns for value in deliveries)
    attempted = sum(blocked_begin_ns < value < blocked_end_ns for value in attempts)
    blocked = sum(blocked_begin_ns < value < blocked_end_ns for value in deliveries)
    after_times = [value for value in deliveries if value > release_ns + 300_000_000]
    if before < 3 or attempted < 3 or blocked or len(after_times) < 3:
        raise ValueError(
            f"{protocol} baseline/attempts/block/restore failed: "
            f"{before}/{attempted}/{blocked}/{len(after_times)}"
        )
    return {
        "before": before,
        "attempts_during_block": attempted,
        "blocked": blocked,
        "after": len(after_times),
        "first_post_release_delivery_seconds": round((after_times[0] - release_ns) / 1e9, 6),
    }
