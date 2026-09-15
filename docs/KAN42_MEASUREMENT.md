# KAN-42 — measurement harness: what it does, and what it needs from whom

Owner: Gabriel / R3. Status: harness landed, **run manifests cannot be completed yet**
because two of their three provenance sections are filled by other roles. This page is
the handover list so nobody has to read the code to find out what is expected of them.

## What is in `measure/`

| Module | What it is for |
|---|---|
| `clocks.py` | `UnixInstant`, `MonotonicInstant`, `Duration`, `WallOffset`. Mixing domains raises `ClockDomainError` at runtime |
| `resources.py` | CPU and RSS readings. Linux via `/proc`, Windows via psapi, anything else reports why it could not read |
| `stages.py` | `RunRecorder` / `StageTimer`: per-stage latency and CPU, plus the cost of measuring |
| `manifest.py` | `ExperimentManifest`: versioned run record, frozen at the start, closed at the end |

Usage is one context manager per stage:

```python
recorder = RunRecorder(counters=RunCounters(kernel_packet_drops=capture.stats.kernel_drops))
with recorder.stage("features"):
    vector = extract_features(...)
manifest.freeze()
...
manifest.close(measurements=recorder.summary(), outcome={...})
```

## What R1 (Onur) supplies

Fill `ProvenanceFromR1`. Every field left `None` is published in the manifest under
`provenance.not_supplied.r1`, so an unfilled run is visibly incomplete rather than
quietly wrong.

| Field | What it should be |
|---|---|
| `sample_pack_sha256` | The pack the run read |
| `windows_sha256` | `windows.jsonl` hash — the one KAN-18/KAN-21 already pin |
| `split_manifest_sha256` | Train/validation/test split identity |
| `model_sha256` | Model artifact hash |
| `model_meta_sha256` | Hash of the exact metadata bytes (KAN-9 requires both, not just the model) |
| `feature_schema_version` | `features-1` today |
| `label_version` | Label set the pack was built with |

## What R2 (Şükrü) supplies

Fill `ProvenanceFromR2`. Same rule: unfilled fields are published as not supplied.

| Field | What it should be |
|---|---|
| `host_id` | Which machine produced the run |
| `boot_id`, `boot_started_at` | Boot identity, so runs from different boots are not merged |
| `monotonic_to_unix_offset` | The mapping between the two clock domains for this boot. **The harness will not compute this**: deriving it from a single pair of readings is exactly the wrong-domain arithmetic `clocks.py` refuses |
| `t0_unix` | Replay/experiment start, as defined by ADR-0002 |
| `sink_evidence` | Independent evidence of where traffic actually went — required because `Direction.EGRESS` alone cannot establish it (see the KAN-33 note of 14 September) |

## Cross-owner change in this PR

`pyproject.toml` gains `"measure*"` in `tool.setuptools.packages.find`. That file is
covered by `* @sicloid`, so this needs R2's review even though `/measure/` is R3's.
Nothing else outside `/measure/`, `/tests/` and `/docs/` is touched.

## What this harness does not claim

- **RSS is not attributed to a stage.** It is a process-wide gauge sampled at stage
  boundaries. Allocators do not return memory promptly, so a per-stage RSS delta would
  read as "this stage used this much", which is not what it means. Peak RSS for the run
  is reported where the platform exposes it.
- **CPU is per thread, and the remainder is shown.** `thread_cpu_seconds` is the
  calling thread; `process_cpu_seconds` covers all threads. The telemetry worker
  (`telemetry/handoff.py`) runs on its own thread, so the difference between the two is
  the exporter's cost appearing *beside* the stage rather than inside it. Do not
  subtract it away.
- **The harness's own cost is reported, not hidden.** `measurement_overhead_seconds`
  per stage, and `overhead_share` per pass. A latency figure whose overhead share is
  large is a measurement of the harness as much as of the stage.
- **Platform cost is not in these numbers.** Mosquitto, PostgreSQL and Grafana run in
  containers, in other processes. Their cost belongs to the platform cards and must be
  reported separately, never folded into a stage.
- **No figure measured on Windows is a result.** The development machine is Windows;
  the target is a Raspberry Pi. Windows readings prove the code path works. Hardware
  numbers come from KAN-46 and KAN-53 and must not be substituted from here.
- **Absent is not zero.** Anything the platform or another role did not supply is
  `None` and is listed in `unavailable`, `counters_not_supplied` or
  `provenance.not_supplied`. Averaging a missing reading as 0 is the failure mode this
  shape exists to prevent.

## Counters this harness does not own

`RunCounters` carries them but never invents them. The caller passes them in:

| Counter | Source |
|---|---|
| `kernel_packet_drops` | `sources/live.py`, `CaptureStats.kernel_drops` |
| `pipeline_queue_overflows` | `gateway/pipeline.py` |
| `telemetry_queue_overflows`, `telemetry_events_dropped` | `telemetry/handoff.py`, `telemetry/spool.py` |

## Why not `psutil`

It would mean regenerating both hash-pinned lock files, which are R2's, for figures the
standard library already provides. `resources.py` reads `/proc` on Linux and calls
psapi through `ctypes` on Windows instead. If a future card needs per-CPU or per-cgroup
detail this trade should be revisited deliberately, as a lock change with R2.

## What is still open before KAN-42 can close

1. R1 and R2 fill the two provenance sections above.
2. A real end-to-end run is recorded through the actual pipeline rather than the
   synthetic exercises in the tests.
3. Owner review.

Until then the harness is usable and the manifests it writes are honest, but no
measurement result is being claimed. `python -m stubs` still reports `g8_passed: false`
and `g10_passed: false`.
