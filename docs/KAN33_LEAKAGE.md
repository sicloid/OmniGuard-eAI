# KAN-33 — containment leakage measurement

This card measures **delivered L3 packets/bytes**, not the model's EGRESS feature
count. The independent observation point is the sink-side `og-c0` interface.

## Timing model

A single point estimate would hide two real uncertainty intervals:

- **t0** is a source/replay submission interval: `begin_ns..end_ns`.
- **apply** is the controller interval from immediately before
  `NftEnforcer.quarantine()` until it returns after successful kernel readback.

The report therefore keeps five buckets:

1. before t0;
2. inside the t0 interval;
3. definitely after t0 and before apply begins;
4. inside the apply interval;
5. after apply ACK/readback.

The reported lower bound is bucket 3. The upper bound is buckets 2+3+4.
Post-ACK packets are **not** folded into the upper bound. A downstream packet can
have crossed the gateway before the apply ACK and only reach userspace afterwards;
alternatively it can indicate a bypass. The raw post-ACK count remains visible.

If containment is never ACKed, the sink reports drops/incompleteness, or a run is
explicitly marked timeout/miss, the run is **CENSORED**. Its observed traffic is
preserved; lower/upper leakage bounds are not fabricated. When more than one cause is
true (for example detector miss + incomplete sink), every cause is retained in the
summary rather than letting the first one hide the others.

## Dedicated safe fixture

Run from the repository root on a Linux Docker host:

```sh
bash lab/run_leakage_docker.sh
```

The container is created with `--network none` and the existing isolated
`og-a -> og-b -> og-c` namespace lab. The fixture sends harmless fixed IPv4/UDP
datagrams. The source continues after quarantine so the experiment can distinguish
"generator stopped" from "gateway contained traffic".

The sink uses `AF_PACKET` on `og-c0`, filters the fixed source/destination/ports,
and records the IPv4 header's actual `total_length` as L3 bytes. It also reads
Linux `PACKET_STATISTICS`; nonzero raw-socket drops make the result censored.

All three participants record `/proc/sys/kernel/random/boot_id`. Monotonic
nanoseconds are correlated only when that boot identity matches.

Evidence is copied to `artifacts/leakage.*`, including source events, sink events,
t0 marker, before/after parent routes/rules and `summary.json`.

## Scope and claim boundary

The fixture covers the explicit path **IPv4 unicast UDP, og-a -> og-b -> og-c**.
It does not measure IPv6 or multicast. Those paths must be reported as not measured,
not as zero leakage. The counter does not use `Direction.EGRESS` as its truth source.

This is a measurement-path validation, not a G8 result. G8 must use the real audited
capture/extractor/RF chain and its declared attack-start reference.
