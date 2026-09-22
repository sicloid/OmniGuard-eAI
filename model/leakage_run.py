"""KAN-52: what a false quarantine costs, and how much of the attack still gets out.

KAN-51 chose N and the lease. This card measures the trade-off those two numbers sit
on and draws the headline plot from the measurement itself. For every cell of the same
grid it replays the frozen KAN-19 decisions through `gateway.policy.DevicePolicy` and
records two quantities that belong to different devices and are never pooled:

* **benign cost** — quarantine episodes and blocked seconds per benign device-hour.
  A benign device produces these for nothing; they are the user-visible price.
* **containment leakage** — the share of observed malicious window-time during which
  the infected device was *not* quarantined, measured as interval overlap.

Leakage here is a policy decision, not a packet count. The bytes that reach a sink
before the kernel ACK are KAN-33's fixture and KAN-49's G8 run; the two numbers are
reported side by side and never added.

Every cell also carries a moving block bootstrap interval, drawn from the capture's
own windows in blocks and replayed through the same policy, so the plot shows the
temporal variability inside a capture instead of a bare point. One capture cannot say
how a different device would behave, and the report repeats that where it matters.

    python -m model.leakage_run --pack ~/omniguard-data/samplepack/windows.jsonl \\
        --artifact ~/omniguard-data/runs/kan19/operating \\
        --out ~/omniguard-data/runs/kan52
"""

import argparse
import json
import platform
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import Classification
from data.samplepack.build import read_windows
from model.artifact import load_model
from model.baseline_run import PackIntegrityError, _sha256, verify_pack
from model.nlease_run import (
    SECONDS_PER_HOUR,
    WINDOW_SECONDS,
    _capture_rows,
    _observed,
    malicious_overlap_seconds,
    replay_device,
)
from model.policy_run import _SHA256
from model.split import split_by_group
from model.train import window_groups

SPEC = Path(__file__).with_name("leakage_spec.json")
REPORT_FILENAME = "leakage_report.json"
TRIMMED_FILENAME = "leakage_report.trimmed.json"
PLOT_FILENAME = "kan52_headline.svg"
ROLES = ("validation", "test")


class LeakageSpecError(ValueError):
    """The measurement specification would allow a choice after seeing results."""


def load_spec(path: Path = SPEC) -> dict:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LeakageSpecError(f"unreadable spec: {exc}") from exc
    if not isinstance(spec, dict):
        raise LeakageSpecError("the spec must be a JSON object")
    if spec.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise LeakageSpecError(f"the spec must name the runtime catalogue {FEATURE_SCHEMA_VERSION}")
    if not _SHA256.fullmatch(str(spec.get("development_pack_windows_sha256"))):
        raise LeakageSpecError("development_pack_windows_sha256 must be a SHA-256 hex digest")
    frozen = spec.get("frozen_policy")
    if not isinstance(frozen, dict):
        raise LeakageSpecError("frozen_policy must be an object")
    for name in ("model_sha256", "metadata_sha256"):
        if not _SHA256.fullmatch(str(frozen.get(name))):
            raise LeakageSpecError(f"frozen_policy.{name} must be a SHA-256 hex digest")
    threshold = frozen.get("threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        raise LeakageSpecError("frozen_policy.threshold must be a number")
    if type(frozen.get("seed")) is not int:
        raise LeakageSpecError("frozen_policy.seed must be the split seed of the frozen run")
    point = frozen.get("operating_point")
    if not isinstance(point, dict) or type(point.get("n")) is not int:
        raise LeakageSpecError("frozen_policy.operating_point must name the frozen N")
    grid = spec.get("grid")
    if not isinstance(grid, dict) or not isinstance(grid.get("n"), list):
        raise LeakageSpecError("grid.n must be a list")
    if point["n"] not in grid["n"] or point.get("lease_seconds") not in grid.get(
        "lease_seconds", []
    ):
        # A plot whose highlighted point is not one of the measured cells would show a
        # claim the run never made.
        raise LeakageSpecError("the frozen operating point must be one of the measured cells")
    bootstrap = spec.get("uncertainty")
    if not isinstance(bootstrap, dict):
        raise LeakageSpecError("uncertainty must be an object")
    for name in ("block_seconds", "resamples", "seed"):
        if type(bootstrap.get(name)) is not int or bootstrap[name] <= 0:
            raise LeakageSpecError(f"uncertainty.{name} must be a positive integer")
    if bootstrap["block_seconds"] % spec["replay"]["window_seconds"]:
        # Blocks are shifted whole; a length off the window grid would misalign every
        # window after the first join and DevicePolicy would reject the lot.
        raise LeakageSpecError("uncertainty.block_seconds must be a multiple of the window")
    if bootstrap["block_seconds"] <= max(grid["lease_seconds"]):
        # A block shorter than the lease cannot contain one quarantine episode, so the
        # resampled series would cut episodes at joins that the capture never had.
        raise LeakageSpecError("uncertainty.block_seconds must exceed the longest lease")
    roles = spec.get("data_roles")
    if not isinstance(roles, dict) or roles.get("primary") not in ROLES:
        raise LeakageSpecError("data_roles.primary must name a measurable split")
    return spec


def test_role_allowed(spec: dict) -> bool:
    """The test split is scored once, and only against a recorded approval.

    The approval lives in the committed spec, so using the test split leaves a diff in
    review rather than a flag in somebody's shell history.
    """
    approval = spec["data_roles"].get("test_approval")
    return (
        isinstance(approval, dict)
        and approval.get("card") == "KAN-52"
        and bool(str(approval.get("approved_by", "")).strip())
        and bool(str(approval.get("date", "")).strip())
    )


def activity_segments(rows) -> dict:
    """Contiguous stretches of traffic, and the silences between them.

    IoT-23 does not label idle, active, startup or update, so this is what the capture
    can actually answer about its own shape (KAN-52, 10 September V3 review). It
    describes observation; it is not a mode label.
    """
    starts = [start for start, _, _ in rows]
    segments, gaps = [], []
    begin = previous = starts[0]
    for start in starts[1:]:
        if start != previous + WINDOW_SECONDS:
            segments.append(previous + WINDOW_SECONDS - begin)
            gaps.append(start - (previous + WINDOW_SECONDS))
            begin = start
        previous = start
    segments.append(previous + WINDOW_SECONDS - begin)
    return {
        "segments": len(segments),
        "longest_segment_seconds": max(segments),
        "median_segment_seconds": sorted(segments)[len(segments) // 2],
        "gaps": len(gaps),
        "silent_seconds": sum(gaps),
        "longest_gap_seconds": max(gaps) if gaps else 0,
    }


def time_blocks(rows, block_seconds: float) -> list:
    """Cut the capture into consecutive blocks of wall-clock time.

    Blocks are lengths of time, not counts of windows, because silence is part of what
    the policy sees: a gap resets the series and a lease keeps running through it.
    Drawing fixed counts of windows would quietly build a busier device than the one
    that was captured. A block with no window in it is kept — it is real silence.
    """
    origin = rows[0][0]
    span = rows[-1][0] + WINDOW_SECONDS - origin
    count = max(1, int((span - 1e-9) // block_seconds) + 1)
    buckets: list[list] = [[] for _ in range(count)]
    for row in rows:
        buckets[min(count - 1, int((row[0] - origin) // block_seconds))].append(row)
    return [(origin + index * block_seconds, bucket) for index, bucket in enumerate(buckets)]


def stitch(blocks, block_seconds: float) -> list:
    """Lay blocks end to end, each keeping its own duration.

    Each block keeps its windows, its inner gaps and the silence at its edges, so the
    rebuilt series has the same density and the same total span as the capture.
    `DevicePolicy` requires window starts to be multiples of the window period; every
    shift here is a multiple of the block length, which the spec keeps a multiple of
    the window period, so the alignment survives.
    """
    rebuilt, cursor = [], 0.0
    for origin, rows in blocks:
        offset = cursor - origin
        for start, result, malicious in rows:
            moved = start + offset
            rebuilt.append((moved, replace(result, window_ts=moved), malicious))
        cursor += block_seconds
    return rebuilt


def resample_series(rows, *, block_seconds: float, resamples: int, seed: int) -> list:
    """Block bootstrap over one capture's timeline, replayed as the capture is.

    Windows next to each other are dependent — that dependence is exactly what N
    exploits — so single windows are never drawn. Whole blocks of time are, with
    replacement, as many as the capture itself holds.
    """
    rng = random.Random(seed)
    blocks = time_blocks(rows, block_seconds)
    series = []
    for _ in range(resamples):
        drawn = [rng.choice(blocks) for _ in blocks]
        rebuilt = stitch(drawn, block_seconds)
        if rebuilt:
            # The span is the blocks' own length, not the last window's timestamp: a
            # resample whose final block ends in silence still occupied that time.
            series.append({"rows": rebuilt, "span_seconds": len(blocks) * block_seconds})
    return series


def percentile(values, fraction: float) -> float:
    """Nearest-rank percentile, so every reported bound is a value that was measured."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def cell_metrics(rows, *, n: int, lease_seconds: float, spec: dict, infected: bool) -> dict:
    """Replay one capture at one grid cell and describe what the policy did."""
    outcome = replay_device(
        [(start, result) for start, result, _ in rows], n=n, lease_seconds=lease_seconds, spec=spec
    )
    observed = _observed(rows)
    hours = observed["observed_hours"]
    span_hours = observed["span_hours"]
    span_seconds = observed["span_seconds"]
    malicious_seconds = observed["malicious_windows"] * WINDOW_SECONDS
    overlap = malicious_overlap_seconds(outcome["episodes"], [s for s, _, m in rows if m])
    first_malicious = next((start for start, _, m in rows if m), None)
    detected_at = outcome["episodes"][0]["start"] if outcome["episodes"] else None
    metrics = {
        "infected": infected,
        **outcome,
        "quarantines_per_observed_hour": round(outcome["quarantines"] / hours, 3)
        if hours
        else None,
        "quarantines_per_span_hour": round(outcome["quarantines"] / span_hours, 3)
        if span_hours
        else None,
        "blocked_seconds_per_span_hour": round(outcome["blocked_seconds"] / span_hours, 1)
        if span_hours
        else None,
        "blocked_fraction_of_span": round(outcome["blocked_seconds"] / span_seconds, 4)
        if span_seconds
        else None,
        "malicious_seconds_blocked": round(overlap, 3),
        "containment_leakage": round(1 - overlap / malicious_seconds, 4)
        if malicious_seconds
        else None,
        "detected": detected_at is not None,
        "detection_delay_seconds": round(detected_at - first_malicious, 3)
        if detected_at is not None and first_malicious is not None
        else None,
    }
    if infected:
        benign_inside = [row for row in rows if not row[2]]
        metrics["benign_windows_inside_infected_capture"] = len(benign_inside)
        metrics["benign_windows_inside_infected_capture_flagged"] = sum(
            1 for _, result, _ in benign_inside if result.classification == Classification.ANOMALOUS
        )
    return metrics


def summarise(values, measured: float, *, digits: int, bounds=(0.0, None)) -> dict:
    """Describe one statistic's resamples honestly, measurement included.

    Three numbers, because a single pair of brackets would hide what it is made of:

    * `resample_spread` is where the resampled runs landed;
    * `bias` is how far their mean sits from the measurement. A resample cannot
      reproduce structure longer than one block, so a statistic that depends on such
      structure shows a bias here, and the spread alone would understate it;
    * `interval` is the basic bootstrap interval, `2 * measured - spread` reversed,
      which is the usual answer to that bias: it is centred on what was measured
      rather than on what the resampling scheme happens to produce.
    """
    low, high = percentile(values, 0.025), percentile(values, 0.975)
    interval = [2 * measured - high, 2 * measured - low]
    floor, ceiling = bounds
    if floor is not None:
        interval = [max(floor, value) for value in interval]
    if ceiling is not None:
        interval = [min(ceiling, value) for value in interval]
    return {
        "measured": round(measured, digits),
        "interval": [round(interval[0], digits), round(interval[1], digits)],
        "resample_spread": [round(low, digits), round(high, digits)],
        "bias": round(sum(values) / len(values) - measured, digits),
        # When the resamples do not even straddle the measurement, the bias is larger
        # than the spread: the blocks cannot reproduce what this cell did, and the
        # interval is too narrow to mean what an interval usually means. Reflecting it
        # does not repair that, so the cell is flagged and the figure draws it dotted.
        "reproduced": bool(low <= measured <= high),
    }


def bootstrap_interval(
    series, measured: dict, *, n: int, lease_seconds: float, spec: dict, infected: bool
) -> dict:
    """Replay every resample of one capture and summarise what they say."""
    observed_rates, span_rates, leakage = [], [], []
    for sample in series:
        rows = sample["rows"]
        outcome = replay_device(
            [(start, result) for start, result, _ in rows],
            n=n,
            lease_seconds=lease_seconds,
            spec=spec,
        )
        observed_rates.append(
            outcome["quarantines"] / (len(rows) * WINDOW_SECONDS / SECONDS_PER_HOUR)
        )
        span_rates.append(outcome["quarantines"] / (sample["span_seconds"] / SECONDS_PER_HOUR))
        malicious_seconds = sum(1 for _, _, m in rows if m) * WINDOW_SECONDS
        if malicious_seconds:
            overlap = malicious_overlap_seconds(outcome["episodes"], [s for s, _, m in rows if m])
            leakage.append(1 - overlap / malicious_seconds)
    summary = {
        "resamples": len(series),
        "quarantines_per_observed_hour": summarise(
            observed_rates, measured["quarantines_per_observed_hour"], digits=3
        ),
        "quarantines_per_span_hour": summarise(
            span_rates, measured["quarantines_per_span_hour"], digits=3
        ),
    }
    if infected and leakage:
        summary["containment_leakage"] = summarise(
            leakage, measured["containment_leakage"], digits=4, bounds=(0.0, 1.0)
        )
    return summary


def measure(
    pack: Path,
    artifact_dir: Path,
    out_dir: Path,
    spec_path: Path = SPEC,
    manifest: Path | None = None,
    *,
    role: str = "validation",
    log=print,
) -> dict:
    spec = load_spec(spec_path)
    if role not in ROLES:
        raise LeakageSpecError(f"role must be one of {ROLES}")
    if role == "test" and not test_role_allowed(spec):
        raise LeakageSpecError(
            "the test split needs a Lead approval recorded in data_roles.test_approval"
        )
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
        raise LeakageSpecError(
            f"artifact threshold {meta.threshold} is not the frozen {frozen['threshold']}"
        )

    split = split_by_group(window_groups(windows), seed=frozen["seed"])
    groups = set(getattr(split, role))
    scored = [w for w in windows if w.group_id in groups]
    if not scored:
        raise LeakageSpecError(f"the {role} split holds no windows")
    if out_dir.exists():
        raise FileExistsError(f"{out_dir} already exists; every run needs a new directory")

    rows = _capture_rows(scored, artifact.model, meta.threshold, meta)
    for group, entries in rows.items():
        devices = {result.device_id for _, result, _ in entries}
        if len(devices) != 1:
            # Every per-device rate in this report rests on one capture being one device.
            raise LeakageSpecError(f"{group} holds {len(devices)} devices; expected exactly one")
    infected = {group for group, entries in rows.items() if any(m for _, _, m in entries)}
    observed = {
        group: {**_observed(entries), "activity": activity_segments(entries)}
        for group, entries in rows.items()
    }

    bootstrap = spec["uncertainty"]
    # The same resamples are replayed at every cell, so two cells differ by their policy
    # and not by which windows the random number generator happened to draw.
    series = {
        group: resample_series(
            entries,
            block_seconds=bootstrap["block_seconds"],
            resamples=bootstrap["resamples"],
            seed=bootstrap["seed"],
        )
        for group, entries in rows.items()
    }

    cells = []
    for n in spec["grid"]["n"]:
        for lease in spec["grid"]["lease_seconds"]:
            captures = {}
            for group, entries in rows.items():
                measured = cell_metrics(
                    entries, n=n, lease_seconds=lease, spec=spec, infected=group in infected
                )
                captures[group] = {
                    **measured,
                    "bootstrap": bootstrap_interval(
                        series[group],
                        measured,
                        n=n,
                        lease_seconds=lease,
                        spec=spec,
                        infected=group in infected,
                    ),
                }
            cells.append({"n": n, "lease_seconds": lease, "captures": captures})
            log(
                f"n={n} lease={lease:>5} "
                + " ".join(
                    f"{group}:{captures[group]['quarantines']}q"
                    + (
                        f"/leak {captures[group]['containment_leakage']:.3f}"
                        if captures[group]["containment_leakage"] is not None
                        else ""
                    )
                    for group in sorted(captures)
                )
            )

    report = {
        "card": "KAN-52",
        "spec": {"path": str(spec_path), "sha256": _sha256(Path(spec_path)), **spec},
        "pack": {"path": str(pack), **asdict(provenance)},
        "artifact": {
            "path": str(artifact_dir),
            "model_id": meta.model_id,
            "model_version": meta.model_version,
            "threshold": meta.threshold,
            "model_sha256": frozen["model_sha256"],
            "metadata_sha256": frozen["metadata_sha256"],
        },
        "evaluated_split": role,
        "captures": sorted(rows),
        "infected_captures": sorted(infected),
        "benign_captures": sorted(set(rows) - infected),
        "observed": observed,
        "operating_point": frozen["operating_point"],
        "environment": {
            "python": sys.version.split()[0],
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "cells": cells,
    }
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    (out_dir / TRIMMED_FILENAME).write_text(
        json.dumps(trimmed_report(report), indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def trimmed_report(report: dict) -> dict:
    """The committed form: no per-episode lists, no local paths."""
    trimmed = json.loads(json.dumps(report))
    trimmed["episodes_note"] = (
        "Per-episode lists are dropped; each capture keeps its episode count and first "
        "three episodes. Produced by model.leakage_run.trimmed_report from the full report."
    )
    for section in ("spec", "pack", "artifact"):
        if isinstance(trimmed.get(section), dict) and "path" in trimmed[section]:
            trimmed[section]["path"] = Path(trimmed[section]["path"]).name
    for cell in trimmed["cells"]:
        for capture in cell["captures"].values():
            capture["first_episodes"] = capture.pop("episodes")[:3]
    return trimmed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--artifact", type=Path, required=True, help="frozen KAN-19 artifact dir")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--role", default="validation", choices=ROLES)
    args = parser.parse_args()
    report = measure(args.pack, args.artifact, args.out, args.spec, args.manifest, role=args.role)
    from model.leakage_plot import write_plot

    plot = write_plot(report, args.out / PLOT_FILENAME)
    print(f"{len(report['cells'])} cells measured on the {report['evaluated_split']} split")
    print(f"plot: {plot}")


if __name__ == "__main__":
    main()
