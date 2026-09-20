"""KAN-51: what N and the lease cost, replayed through the real policy.

The threshold answers "is this window anomalous". N and the lease answer "when does a
device get quarantined, and for how long". This runner replays the frozen KAN-19
decisions over the seed-1 validation windows through `gateway.policy.DevicePolicy`
itself, so the numbers come from the code that will run, not from a model of it.

What it does per grid cell:

1. loads the frozen artifact and verifies both pinned hashes;
2. scores each validation window once, with the frozen threshold;
3. feeds each device's results to a fresh DevicePolicy in window order, at
   `window_end + decision_delay`, re-arming after every lease expiry;
4. counts quarantine episodes, blocked seconds, detection delay and containment.

Benign captures and infected captures are kept apart. Only a benign *device* can
produce a false quarantine; the benign windows inside an infected capture belong to
the infected device and are never counted as one. Blocked seconds are policy intent:
whether traffic actually stopped is KAN-33/KAN-52 evidence, not this replay.

    python -m model.nlease_run --pack ~/omniguard-data/samplepack/windows.jsonl \\
        --artifact ~/omniguard-data/runs/kan19/operating \\
        --out ~/omniguard-data/runs/kan51
"""

import argparse
import json
import platform
import sys
from dataclasses import asdict
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import Classification, DetectionResult, DeviceState
from data.samplepack.build import read_windows
from gateway.policy import DevicePolicy
from model.artifact import load_model
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.policy_run import _SHA256
from model.split import split_by_group
from model.train import rf_scores, window_groups

SPEC = Path(__file__).with_name("nlease_spec.json")
REPORT_FILENAME = "nlease_report.json"
WINDOW_SECONDS = 5
SECONDS_PER_HOUR = 3600.0


class SweepSpecError(ValueError):
    """The sweep specification would allow choosing after seeing results."""


def _positive_numbers(values, name: str) -> None:
    if not isinstance(values, list) or not values or len(set(values)) != len(values):
        raise SweepSpecError(f"{name} must be a nonempty list of distinct values")
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise SweepSpecError(f"{name} entries must be positive numbers")


def load_spec(path: Path = SPEC) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SweepSpecError(f"unreadable sweep spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise SweepSpecError("sweep spec must be a JSON object")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise SweepSpecError(f"spec must name the runtime catalogue {FEATURE_SCHEMA_VERSION}")
    if not _SHA256.fullmatch(str(spec.get("development_pack_windows_sha256"))):
        raise SweepSpecError("development_pack_windows_sha256 must be a SHA-256 hex digest")
    frozen = spec.get("frozen_policy")
    if not isinstance(frozen, dict):
        raise SweepSpecError("frozen_policy must be an object")
    for name in ("model_sha256", "metadata_sha256"):
        if not _SHA256.fullmatch(str(frozen.get(name))):
            raise SweepSpecError(f"frozen_policy.{name} must be a SHA-256 hex digest")
    threshold = frozen.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise SweepSpecError("frozen_policy.threshold must be a number")
    if not 0 <= threshold <= 1:
        raise SweepSpecError("frozen_policy.threshold must be in [0, 1]")
    if type(frozen.get("seed")) is not int:
        raise SweepSpecError("frozen_policy.seed must be the split seed of the frozen run")
    grid = spec.get("grid")
    if not isinstance(grid, dict):
        raise SweepSpecError("grid must be an object")
    counts = grid.get("n")
    _positive_numbers(counts, "grid.n")
    if any(type(value) is not int for value in counts):
        raise SweepSpecError("grid.n entries must be integers")
    _positive_numbers(grid.get("lease_seconds"), "grid.lease_seconds")
    replay = spec.get("replay")
    if not isinstance(replay, dict):
        raise SweepSpecError("replay must be an object")
    for name in ("decision_delay_seconds", "max_result_age", "max_lease_seconds"):
        value = replay.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise SweepSpecError(f"replay.{name} must be a positive number")
    if replay["decision_delay_seconds"] > replay["max_result_age"]:
        raise SweepSpecError("a decision later than max_result_age would reject every window")
    if max(grid["lease_seconds"]) > replay["max_lease_seconds"]:
        raise SweepSpecError("every lease must fit inside max_lease_seconds")
    rule = spec.get("selection_rule")
    if not isinstance(rule, dict) or not isinstance(rule.get("n"), str):
        raise SweepSpecError("the selection rule must be declared before the run")
    return spec


def replay_device(results, *, n: int, lease_seconds: float, spec: dict) -> dict:
    """Run one device's results through DevicePolicy and record what the policy did.

    `results` is a list of (window_start, DetectionResult) in window order. The clock
    is the replay clock: a window closes at `start + 5` and is decided
    `decision_delay_seconds` later. Monotonic time equals that instant, so a lease
    expires exactly `lease_seconds` after the decision.
    """
    replay = spec["replay"]
    delay = float(replay["decision_delay_seconds"])
    policy = DevicePolicy(
        results[0][1].device_id,
        n=n,
        lease_seconds=float(lease_seconds),
        max_lease=float(replay["max_lease_seconds"]),
        max_result_age=float(replay["max_result_age"]),
    )
    episodes: list[dict] = []

    def close(now: float, reason: str) -> None:
        if episodes and episodes[-1]["end"] is None:
            episodes[-1]["end"] = now
            episodes[-1]["ended_by"] = reason

    for start, result in results:
        now = start + WINDOW_SECONDS + delay
        # Tick first, so a lease that expired between windows ends before the next
        # decision, exactly as a continuously polled runtime would see it.
        for event in policy.tick(now=now, mono=now):
            if event.new_state == DeviceState.NORMAL:
                close(now, event.reason)
        if policy.state == DeviceState.NORMAL and not policy.armed:
            policy.rearm()
        for event in policy.observe(result, now=now, mono=now):
            if event.new_state == DeviceState.QUARANTINED:
                episodes.append({"start": now, "window_ts": start, "end": None, "ended_by": None})
            elif event.new_state == DeviceState.NORMAL:
                close(now, event.reason)

    # An episode still open when the capture ends lasted until its lease would expire,
    # or until observation stopped, whichever came first.
    last_seen = results[-1][0] + WINDOW_SECONDS + delay
    for episode in episodes:
        if episode["end"] is None:
            episode["end"] = min(episode["start"] + float(lease_seconds), last_seen)
            episode["ended_by"] = "still quarantined when the capture ended"
    blocked = sum(episode["end"] - episode["start"] for episode in episodes)
    return {
        "episodes": episodes,
        "quarantines": len(episodes),
        "blocked_seconds": round(blocked, 3),
        "rejections": dict(policy.rejections),
        "resets": dict(policy.resets),
    }


def _capture_rows(windows, model, threshold: float, meta) -> dict:
    """Score every window once and group the results by capture, in window order."""
    scores = rf_scores(model, windows)
    rows: dict[str, list] = {}
    for window, score in zip(windows, scores, strict=True):
        vector = window.vector
        result = DetectionResult(
            vector.device_id,
            vector.window_start,
            meta.model_id,
            meta.model_version,
            float(score),
            Classification.ANOMALOUS if score >= threshold else Classification.NORMAL,
            threshold,
        )
        rows.setdefault(window.group_id, []).append((vector.window_start, result, window.malicious))
    for group in rows:
        rows[group].sort(key=lambda row: row[0])
    return rows


def _observed(rows) -> dict:
    """Two different denominators, kept apart on purpose.

    `observed_*` counts only the seconds the device was actually seen sending, which
    is the honest denominator for a per-window rate. `span_*` is wall-clock from the
    first window to the last, which is the denominator a quarantine lives in: a lease
    keeps running through a silent gap. Dividing blocked wall-clock seconds by
    observed seconds would report more than 3600 blocked seconds per hour.
    """
    windows = len(rows)
    seconds = windows * WINDOW_SECONDS
    span = rows[-1][0] + WINDOW_SECONDS - rows[0][0]
    return {
        "windows": windows,
        "observed_seconds": seconds,
        "observed_hours": round(seconds / SECONDS_PER_HOUR, 4),
        "span_seconds": span,
        "span_hours": round(span / SECONDS_PER_HOUR, 4),
        "observed_fraction_of_span": round(seconds / span, 4) if span else None,
        "malicious_windows": sum(1 for _, _, malicious in rows if malicious),
        "anomalous_windows": sum(
            1 for _, result, _ in rows if result.classification == Classification.ANOMALOUS
        ),
    }


def select_cell(cells, infected, *, containment_floor: float = 0.9) -> dict:
    """Apply the declared rule: no false quarantine first, then the smallest lease.

    A benign capture is one that is not infected. Only those can produce a false
    quarantine; the benign windows inside an infected capture belong to the infected
    device and are excluded by construction.
    """
    clean = []
    for cell in cells:
        benign = [c for group, c in cell["captures"].items() if group not in infected]
        if benign and all(c["quarantines"] == 0 for c in benign):
            clean.append(cell)
    if not clean:
        return {"status": "no_clean_n", "n": None, "lease_seconds": None}
    smallest_n = min(cell["n"] for cell in clean)
    qualifying = [
        cell
        for cell in clean
        if cell["n"] == smallest_n
        and all(
            (c["contained_fraction_of_malicious_time"] or 0) >= containment_floor
            for group, c in cell["captures"].items()
            if group in infected
        )
    ]
    if not qualifying:
        return {"status": "no_lease_contains", "n": smallest_n, "lease_seconds": None}
    chosen = min(qualifying, key=lambda cell: cell["lease_seconds"])
    return {
        "status": "selected",
        "n": chosen["n"],
        "lease_seconds": chosen["lease_seconds"],
        "containment_floor": containment_floor,
    }


def run(
    pack: Path,
    artifact_dir: Path,
    out_dir: Path,
    spec_path: Path = SPEC,
    manifest: Path | None = None,
    *,
    log=print,
) -> dict:
    spec = load_spec(spec_path)
    spec_sha256 = _sha256(Path(spec_path))
    pack, out_dir = Path(pack), Path(out_dir)
    provenance = verify_pack(pack, manifest)
    if provenance.windows_sha256 != spec["development_pack_windows_sha256"]:
        raise PackIntegrityError(f"{pack.name} is not the development pack the spec names")
    windows = read_windows(pack)
    if _sha256(pack) != provenance.windows_sha256:
        raise PackIntegrityError(f"{pack.name} changed while it was being read")

    frozen = spec["frozen_policy"]
    artifact = load_model(
        Path(artifact_dir),
        expected_model_sha256=frozen["model_sha256"],
        expected_metadata_sha256=frozen["metadata_sha256"],
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
    )
    meta = artifact.metadata
    if meta.threshold != frozen["threshold"]:
        raise SweepSpecError(
            f"artifact threshold {meta.threshold} is not the frozen {frozen['threshold']}"
        )

    split = split_by_group(window_groups(windows), seed=frozen["seed"])
    validation = set(split.validation)
    replayed = [w for w in windows if w.group_id in validation]
    if not replayed:
        raise SweepSpecError("the validation split holds no windows")
    out_dir.mkdir(parents=True, exist_ok=False)

    rows = _capture_rows(replayed, artifact.model, meta.threshold, meta)
    infected = {group for group, entries in rows.items() if any(m for _, _, m in entries)}
    observed = {group: _observed(entries) for group, entries in rows.items()}

    cells = []
    for n in spec["grid"]["n"]:
        for lease in spec["grid"]["lease_seconds"]:
            captures = {}
            for group, entries in rows.items():
                outcome = replay_device(
                    [(start, result) for start, result, _ in entries],
                    n=n,
                    lease_seconds=lease,
                    spec=spec,
                )
                hours = observed[group]["observed_hours"]
                span_hours = observed[group]["span_hours"]
                span_seconds = observed[group]["span_seconds"]
                malicious_seconds = observed[group]["malicious_windows"] * WINDOW_SECONDS
                first_malicious = next((start for start, _, m in entries if m), None)
                detected_at = outcome["episodes"][0]["start"] if outcome["episodes"] else None
                captures[group] = {
                    "infected": group in infected,
                    **outcome,
                    "quarantines_per_observed_hour": round(outcome["quarantines"] / hours, 3)
                    if hours
                    else None,
                    "quarantines_per_span_hour": round(outcome["quarantines"] / span_hours, 3)
                    if span_hours
                    else None,
                    "blocked_seconds_per_span_hour": round(
                        outcome["blocked_seconds"] / span_hours, 1
                    )
                    if span_hours
                    else None,
                    "blocked_fraction_of_span": round(outcome["blocked_seconds"] / span_seconds, 4)
                    if span_seconds
                    else None,
                    "detected": detected_at is not None,
                    "detection_delay_seconds": round(detected_at - first_malicious, 3)
                    if detected_at is not None and first_malicious is not None
                    else None,
                    "contained_fraction_of_malicious_time": round(
                        min(outcome["blocked_seconds"], malicious_seconds) / malicious_seconds, 4
                    )
                    if malicious_seconds
                    else None,
                }
            cells.append({"n": n, "lease_seconds": lease, "captures": captures})
            summary = " ".join(
                f"{group}:{captures[group]['quarantines']}q/"
                f"{captures[group]['blocked_seconds']:.0f}s"
                for group in sorted(captures)
            )
            log(f"n={n} lease={lease:>5} {summary}")

    selection = select_cell(cells, infected)
    report = {
        "card": "KAN-51",
        "status": selection["status"],
        "spec": {"path": str(spec_path), "sha256": spec_sha256, **spec},
        "pack": {"path": str(pack), **asdict(provenance)},
        "artifact": {
            "path": str(artifact_dir),
            "model_id": meta.model_id,
            "model_version": meta.model_version,
            "threshold": meta.threshold,
            "model_sha256": frozen["model_sha256"],
            "metadata_sha256": frozen["metadata_sha256"],
        },
        "evaluated_split": "validation",
        "validation_captures": sorted(rows),
        "infected_captures": sorted(infected),
        "observed": observed,
        "environment": {
            "python": sys.version.split()[0],
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "selection": selection,
        "cells": cells,
    }
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--artifact", type=Path, required=True, help="frozen KAN-19 artifact dir")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC)
    args = parser.parse_args()
    report = run(args.pack, args.artifact, args.out, args.spec, args.manifest)
    selection = report["selection"]
    print(f"selection: {selection['status']} n={selection['n']} lease={selection['lease_seconds']}")
    raise SystemExit(0 if selection["status"] == "selected" else 1)


if __name__ == "__main__":
    main()
