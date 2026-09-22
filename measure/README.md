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

`pi_guard.py` wraps a Pi measurement with pre/post host, boot, monotonic-time,
load, temperature and firmware throttle evidence. It rejects missing or contaminated
readings; post-run one-minute load is context because it includes the workload.
The guard keeps Python 3.11-compatible syntax so it can record a reason on a Pi
before the project interpreter is installed; the full project still requires its
locked Python 3.14 environment. The default temperature ceiling is 80 °C, and
the CLI refuses a ceiling above 85 °C. These are conservative experiment
acceptance limits, not a claim about the hardware's precise throttle point;
`vcgencmd get_throttled` remains the direct firmware observation.


## KAN-33 — containment leakage

`measure.leakage` keeps the replay/source t0 interval, the enforcer apply/readback
interval and independent sink deliveries separate. It never collapses either interval
to a point estimate.

For complete runs, the lower bound counts only deliveries definitely after t0 and
before apply begins. The upper bound additionally includes deliveries observed inside
the t0 and apply uncertainty intervals. It is an upper bound on sink-observed
pre-ACK leakage only. Post-ACK deliveries remain a separate in-flight-or-bypass
bucket.

A run with no containment ACK, an incomplete sink, or an explicit timeout/miss reason
is `CENSORED`; observed traffic is retained but leakage bounds are `None`. The
dedicated Linux fixture and exact scope are documented in
[docs/KAN33_LEAKAGE.md](../docs/KAN33_LEAKAGE.md).

A complete result also requires a source attempt window covered by the sink window and
at least one source attempt after the containment ACK. Otherwise the result is censored
instead of allowing an empty delivery list to become a zero-leakage claim.
