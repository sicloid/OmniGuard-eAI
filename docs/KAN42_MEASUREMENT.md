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
| `manifest.py` | `ExperimentManifest`: versioned run record, sealed at the start, closed at the end |

`manifest.py` enforces three things rather than asking for them. The configuration and
both provenance sections are deep-copied at `freeze()` and cannot be changed afterwards
— not by editing a nested value, not by replacing the attribute. **One run directory
holds one run**: `freeze()` claims `manifest.json` with an exclusive create, so a second
run pointed at the same directory fails there instead of replacing the first run's
evidence, and only the run that claimed the file may close it. And a write that fails
leaves the run retryable: `freeze()`/`close()` mark themselves done only once the
document is on disk.

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

Field names follow the names R1's merged runners already write, so the same bytes are
never published twice under two names. The mapping was agreed on the PR #32 review
(R1 comment of 15 September, Lead decision the same day):

| Field | What it should be | Where R1 already writes it |
|---|---|---|
| `pack_manifest_sha256` | The pack's `manifest.json` — it pins `windows_sha256` and every `pcap_sha256`/`conn_log_sha256`, so it identifies the whole pack | `PackProvenance.manifest_sha256` |
| `windows_sha256` | `windows.jsonl` hash — the one KAN-18/KAN-21 already pin | `windows_sha256` |
| `split_manifest_sha256` | Hash of `split.manifest.json` | `training_manifest_sha256` (KAN-9 metadata and provenance) |
| `model_sha256` | Model artifact hash | `model_sha256` |
| `model_meta_sha256` | Exact `model.meta.json` bytes | `metadata_sha256` (provenance) |
| `threshold_policy_sha256` | The KAN-19 frozen operating policy, required by ADR-0004 decision 7b | `model/frozen/kan19-seed1/` |
| `data_role` | `development`, `holdout` or `external_transfer` — ADR-0004 decision 7 separates them, and without this a holdout run and a development run write indistinguishable manifests | — |
| `holdout_selection_sha256` | Hash of `data/holdout/selection.json`, when `data_role` is `holdout` | `data/holdout/selection.json` |
| `feature_schema_version` | `features-1` today | KAN-9 `model.meta.json` |
| `label_rule_version` | R1's explicit version for the window-label rule | the versioned pack-manifest update (option a) |

Three notes on the shape:

- **There is no capture-hash field.** The pack manifest already pins every capture and
  parent-capture hash; a second copy here could only disagree with it. The module
  docstring no longer claims one.
- **`label_rule_version` is not derived here.** Option (a) was chosen over hashing the
  manifest's `label_rule` text: a version R1 publishes names the rule, a hash computed
  at this end names bytes R1 never called a version. Historical pinned manifests are
  not relabelled or overwritten; until the versioned update lands the field is absent.
- **N and the lease are not provenance.** They are policy parameters and belong in the
  run's frozen `config`, which is sealed before the run for the same reason 7b wants
  the hashes recorded first. A `data_role: holdout` run that is missing any 7b field
  publishes those field names under `provenance.holdout_preconditions_unmet`, so an
  unqualified holdout run cannot read as a clean one.

Supplied `*_sha256` values must be 64 lowercase hex characters; a shortened hash copied
from a report is rejected rather than published as provenance.

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
- **CPU is per thread, and the remainder is shown but not attributed.**
  `thread_cpu_seconds` is the calling thread; `process_cpu_seconds` covers all threads.
  The difference says work happened on other threads beside the stage — the telemetry
  worker (`telemetry/handoff.py`) is one candidate, a native library's worker threads
  including the RF implementation are others. It is not the exporter's cost, and it is
  not noise to subtract away.
- **The harness's own cost is reported, not hidden — and it sits outside `elapsed`.**
  Readings are taken before the stage window opens and after it closes, so
  `measurement_overhead_seconds` is additional to the latency rather than contained in
  it. `overhead_ratio` per pass is therefore cost *per unit of* stage time, and
  `measured_span_seconds_total` is what the pass cost in wall time altogether. A ratio
  of 0.05 means the harness added 5% on top, not that 5% of the reported latency was
  the harness.
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
