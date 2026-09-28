# KAN-45 runtime compute budget — 28 September 2026

    python docs/evidence/KAN45_2026-09-28_runtime/verify.py

This is the **gateway runtime** under a cgroup v2 budget: the real G8 pipeline, not a
training job. It complements the 64-tree training benchmark in
`docs/evidence/KAN45_2026-09-28/` (PR #57); neither is router or Raspberry Pi emulation.

## What ran

`measure/run_kan42.sh` at `12c9edf` on a clean tree, twice, same code and inputs
(pinned KAN-19 RF, IoT-23 8-1 slice, N=1, 6 s lease, 24 s core), Windows 11 with
Docker Desktop's Linux engine (x86_64):

- `unbudgeted` — no limits (`cpu.max` = `max 100000`, `memory.max` = `max`);
- `budget-0.5cpu-256m` — `KAN42_CPUS=0.5 KAN42_MEMORY=256m`, i.e. `--cpus 0.5
  --memory 256m --memory-swap 256m` on the whole lab container.

The `/2` manifest seals the limits the container itself reports before the lab starts,
and at close records the container's `cpu.stat` difference across the lab,
`memory.peak` and `memory.events`. Everything else is the KAN-42 sealed run
(`docs/evidence/KAN42_2026-09-24/README.md`).

## Result

| | unbudgeted | 0.5 CPU / 256 MiB |
|---|---:|---:|
| periods throttled | 0 of 0 | **29 of 281** |
| `throttled_usec` | 0 | **7,943,261** |
| container CPU during the lab | 6.26 s | 2.74 s |
| `memory.peak` (container) | 286.2 MB | 187.7 MB |
| OOM / OOM kill | 0 / 0 | 0 / 0 |
| `inference` (5 windows) total / longest | 38.3 / 8.2 ms | 36.5 / 8.3 ms |
| `enforcer` (2 calls) | 17.4 ms | 15.8 ms |
| `features` | 13.5 ms (908) | 13.6 ms (932) |
| `policy` | 4.9 ms (913) | 5.2 ms (937) |
| `exporter` | 0.10 ms | 0.12 ms |
| windows / quarantines / kernel drops | 5 / 1 / 0 | 5 / 1 / 0 |
| sinks during block (TCP / UDP) | 0 / 0 | 0 / 0 |

**The budget bit, and the per-window path did not notice.** The kernel throttled the
container in 29 of 281 periods, yet every stage's elapsed time is within the
run-to-run spread seen across the KAN-42 runs, and the containment result is the same.
The per-window hot path costs about 0.1 s of CPU across the 24 s core, far below
0.5 CPU.

## What is not established

- **When the throttling happened.** There is no per-period timeline. Because no stage
  slowed, it was outside the measured stages — plausibly process start-up and model
  loading — but that is not measured here.
- **Why the container used less CPU under the budget** (2.74 s against 6.26 s for the
  same schedule). Offered traffic was the same (~350 paced source attempts per
  protocol in both). The difference is recorded, not explained.
- **Load.** Five scored windows and one quarantine episode. This shows headroom for
  this workload under this budget, not a capacity limit; a heavier stream or several
  devices could behave differently.
- **Hardware.** x86_64 in a Docker Desktop VM. A cgroup quota does not change CPU
  architecture, cache or clock; nothing here is a Pi figure.
