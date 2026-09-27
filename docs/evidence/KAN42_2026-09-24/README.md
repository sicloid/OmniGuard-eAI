# KAN-42 sealed measurement runs — 24 September 2026

    python docs/evidence/KAN42_2026-09-24/verify.py

checks every file against `SHA256SUMS`, confirms each closed manifest carries the
stage and core files it claims, re-derives `t0` from the replay's own clock mapping,
re-hashes both sink logs, and prints the per-stage tables below.

## What ran

`bash measure/run_kan42.sh MODEL_DIR PREPARED_DIR OUT_DIR` on a clean tree, Windows 11
with Docker Desktop's Linux engine (x86_64). The lab is
`lab/container_g8_iot23_probe.sh` with one line substituted — the core runs as
`python -m measure.kan42_core`, which runs `lab/g8_core.py` unchanged and times the real
capture, pipeline, detector, policy, enforcer and bridge objects. Pinned KAN-19 RF
(`d30725a9…57de6b`), IoT-23 8-1 slice (`fc4aa4b9…ac917ee`), N=1, 6 s lease, 24 s core.
A counting UDS adapter in the same container gives the exporter a real socket.

The `/2` manifest was frozen before the lab started by a separate process
(`measure/kan42_manifest.py`) and closed by it after the lab finished:

- **Sealed before the run:** configuration, policy block, SHA-256 of 21 files on the
  measured path and of both model files; R1 provenance copied field by field from the
  frozen model's `provenance.json` (`data_role: development`); R2 `boot_id`, boot time
  and a bracketed monotonic↔UTC calibration (half-width 338 ns in run 1) read from the
  run's own kernel.
- **Observed at close:** `t0_unix` from the replay's clock mapping and first
  `send_begin_ns`, inside the run window; sink evidence as both sink logs' SHA-256
  plus the lab validator's verdict (TCP and UDP blocked 0, kernel drops 0).
- **Not supplied:** `host_id` (a container hostname names the container, not a
  machine), `label_rule_version` (not yet published by R1), `holdout_selection_sha256`
  (not a holdout run).

## The two runs

Run 1 (`801b8c1`) exposed a harness defect: `StageTimer` read CPU before RSS on entry,
so every pass charged the `/proc/self/status` read to the stage, and the
sub-millisecond stages reported more thread CPU than elapsed time. `d73e833` reads
memory first, with a test that fails on the old order; run 2 is the same run on the
fixed harness. Run 1 is kept — its elapsed times and its millisecond stages are
unaffected, and discarding it would hide why the fix exists.

| Stage | Passes | Elapsed total | Longest pass | Thread CPU run 1 → run 2 |
|---|---:|---:|---:|---:|
| `inference` (RF) | 5 | 40.3 ms | 8.9 ms | 36.3 → 40.3 ms |
| `enforcer` (nft) | 2 | 15.6 ms | 10.3 ms | 2.2 → 2.2 ms |
| `features` | 892 | 13.7 ms | 0.45 ms | **44.4 → 16.7 ms** |
| `policy` | 897 | 5.0 ms | 0.14 ms | **29.9 → 7.4 ms** |
| `exporter` | 2 | 0.09 ms | 0.05 ms | 0.22 → 0.10 ms |
| `capture` | 892 | 23.6 s | 251 ms | 206.6 → 203.3 ms |

Figures are run 2's unless marked. Peak process RSS 128.5 MB; 879 packets received,
0 kernel drops; 5 windows scored, 1 quarantine applied and released; exporter 2/2
delivered to a `VERIFIED` peer.

How to read them:

- **`capture` elapsed is waiting for traffic**, not cost. Its CPU is the cost.
- **`enforcer` elapsed is mostly the `nft` subprocess**, which runs outside this
  process; that is why its thread CPU is small.
- **Small-stage CPU still carries ~3 µs per pass of harness cost** — the `read_cpu`
  call and timestamp inside the window after the fix. At 892 passes that is ~3 ms,
  which is why `features` and `policy` CPU remain slightly above their elapsed time.
- **The harness adds more than it measures for small stages**: 79 ms of readings
  around 13.7 ms of `features`. It is reported per stage as
  `measurement_overhead_seconds` and sits outside the elapsed figures.

## Limits

- **x86_64 Docker Desktop VM, not a Raspberry Pi.** No figure here belongs in a Pi
  column; Pi runs are Şükrü's (KAN-42 comment 11147).
- One declared development capture, five scored windows. Inference and enforcer
  figures rest on 5 and 2 passes.
- R2 context was read by the run from its own kernel, following `lab/replay.py`'s
  bracketed calibration; it was not supplied by R2 separately.
