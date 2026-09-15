# R3 — Gabriel (leakage jointly with R2)

Next: monotonic stage durations, CPU/RAM, telemetry bytes and experiment metadata.
Containment leakage counts L3 packets/bytes from replay t0 to active containment.
Record raw evidence and run IDs. Keep Pi results separate from controlled x86
compute budgets and never derive benchmark claims from synthetic stubs.

## V3 design follow-up

V3 ölçüm tanımı: t0, karar, apply begin/ACK ve ACK sonrası sink geçişini ayrı
kaydedin. ACK kesin kernel aktivasyon anı değildir; drain byte bilgisini atmayın.
Tespit edilmeyen run'ları dışlamayın. False quarantine/device-hour ve benign blocked
seconds/device-hour ile kullanıcı etkisini ayrıca ölçün. [Mimari](../ARCHITECTURE.md).

## KAN-42 — measurement harness

`clocks.py` keeps UTC and monotonic apart and raises `ClockDomainError` when they are
mixed; `NewType` was rejected for this because it is erased at runtime. `resources.py`
reads CPU and RSS with no new dependency and reports *why* when it cannot. `stages.py`
times the six pipeline stages separately and publishes the harness's own overhead
beside each figure. `manifest.py` writes a versioned run record, frozen before the run
and closed after it; a run that dies leaves an `incomplete` manifest rather than none.

Anything not supplied stays absent and is named — never averaged in as zero. The
provenance fields R1 and R2 must fill, the counters this harness does not own, and the
limits of what these numbers mean are listed in
[docs/KAN42_MEASUREMENT.md](../docs/KAN42_MEASUREMENT.md).

Windows readings prove the code path only. Raspberry Pi figures come from KAN-46/53.
