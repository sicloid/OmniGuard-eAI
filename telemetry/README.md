# R3 — Gabriel

Develop with `stubs.fake_telemetry.fake_telemetry()` and `core.schema.TelemetryPayload`.
Next: settle MQTT topic/QoS, UDS framing and event deduplication in a reviewed ADR,
then implement UDS host adapter, publisher and PostgreSQL consumer.
Real gateway events cross a Unix socket; do not add a lab Internet route.
