# KAN-45 controlled compute-budget benchmark

This experiment measures the pipeline while Linux cgroup v2 applies finite CPU
and memory limits. It is **not router emulation**: CPU architecture, cache,
storage, kernel, NIC and scheduler remain those of the host/container runtime.

The runner refuses an unlimited `cpu.max` or `memory.max`, records the limits
visible inside the process, command, monotonic duration, child CPU time, peak
RSS, exit status and a SHA-256 sidecar.

Example with Docker's cgroup v2 controls:

```bash
docker run --rm --cpus 0.5 --memory 256m \
  -v "$PWD:/work:ro" -w /work python:3.14 \
  python -m measure.compute_budget --output /tmp/report.json -- \
  python -m unittest tests.test_pipeline
```

The evidence is valid only when the resulting JSON reports finite limits and
the measured command exits successfully. Comparisons must keep the image,
command, input hashes and host context fixed; they must never be described as
Raspberry Pi or home-router performance.

## Recorded run — 28 September 2026

The sealed IoT-23 sample pack (`windows_sha256` `4b97fb95…6625`) was used for a
single-seed 64-tree training/validation workload inside Docker cgroup v2 with
0.5 CPU and 256 MiB memory. The review-complete v2 command exited zero in
5.297 s wall time, used 2.647 s child CPU and reached 190,016 KiB peak child
RSS. The cgroup reached its 256 MiB limit without an OOM: `memory.peak` was
268,435,456 bytes, `memory.events.max` increased by 393, and both `oom` and
`oom_kill` remained zero. Every one of 53 observed CPU periods was throttled,
with 7.510 s of aggregate throttled time.

The v2 report embeds the exact input hashes, workload scope and container image
ID (`sha256:04164649…3406`). Raw values and their sidecar hash are in
`docs/evidence/KAN45_2026-09-28/model-benchmark-v2.json`. The earlier v1 file is
retained for audit history and is superseded for reporting.

This small run demonstrates that the training/validation workload completes
under one controlled budget while incurring sustained CPU throttling and
reaching the memory ceiling. It is not the frozen 200-tree training run,
gateway runtime, a throughput capacity result, Pi performance, or router
emulation.

## Gateway runtime follow-up

The separate sealed G8 follow-up runs the real gateway path with identical
inputs, once without a declared limit and once at 0.5 CPU / 256 MiB. In the
budgeted run the kernel throttled 29 of 281 periods for 7.943 s aggregate time;
five inference windows, one quarantine episode and containment behavior stayed
within the observed unbudgeted run spread. This small, paced run demonstrates
headroom for that workload only; it is not a capacity boundary.

The complete before/after manifests, stage measurements, raw logs, checksums
and verifier are in `docs/evidence/KAN45_2026-09-28_runtime/`.
