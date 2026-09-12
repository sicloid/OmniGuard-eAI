# R3 — Gabriel

Develop with `stubs.fake_telemetry.fake_telemetry()` and `core.schema.TelemetryPayload`.
Next: settle MQTT topic/QoS, UDS framing and event deduplication in a reviewed ADR,
then implement UDS host adapter, publisher and PostgreSQL consumer.
Real gateway events cross a Unix socket; do not add a lab Internet route.

## V3 design follow-up

V3: StateEvent karar bilgisidir; applied firewall state veya anomaly score
alanlarını ondan uydurmayın. Ek versioned envelope, sequence/dedup, bounded spool
ve crash/retry semantiği [ADR-0002 önerisindedir](../docs/adr/0002-bounded-containment.md).
Docker lab ile UDS dosya görünürlüğü ayrı mount/permission tasarımı gerektirir.
