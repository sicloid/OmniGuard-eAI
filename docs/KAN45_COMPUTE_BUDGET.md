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
0.5 CPU and 256 MiB memory. The command exited zero in 10.493 s wall time,
used 5.253 s child CPU and reached 170,052 KiB peak child RSS. Raw values and
their sidecar hash are in `docs/evidence/KAN45_2026-09-28/model-benchmark.json`.

This small run demonstrates sensitivity under one controlled budget. It is not
the frozen 200-tree training run, a throughput capacity result, Pi performance,
or router emulation.
