# R3 — Gabriel

Develop with `stubs.fake_telemetry.fake_telemetry()` and `core.schema.TelemetryPayload`.
Real gateway events cross a Unix socket; do not add a lab Internet route.

## Transport contract

[ADR-0003](../docs/adr/0003-telemetry-framing.md) defines framing, identity,
topic, QoS, spool and ACK semantics. It is **PROPOSED**: the modules here follow
it, but the contract is not team-approved and no new wire envelope is added to
the frozen `0.1.0` payload.

| Module | Responsibility |
|---|---|
| `canonical.py` | one deterministic JSON encoding, used on the wire and for `event_id` |
| `framing.py` | four-byte length prefix, `MAX_FRAME` checked before the body is read |
| `identity.py` | producer/boot/sequence, `device_id` rules, UUID5 `event_id` |
| `spool.py` | byte and age bounds, oldest-first eviction, permanent drop counters |
| `publisher.py` | topic, QoS 1, injected transport, spool fallback and drain |

The transport is injected so the fault matrix runs as unit tests. Those tests are
not delivery evidence; the real broker and database path is proved on Compose
under KAN-50. Remaining work: UDS host adapter (KAN-38), database schema and
migrations (KAN-39), consumer (KAN-40), dashboard (KAN-41).

## V3 design follow-up

V3: StateEvent karar bilgisidir; applied firewall state veya anomaly score
alanlarını ondan uydurmayın. Ek versioned envelope, sequence/dedup, bounded spool
ve crash/retry semantiği [ADR-0002 önerisindedir](../docs/adr/0002-bounded-containment.md).
Docker lab ile UDS dosya görünürlüğü ayrı mount/permission tasarımı gerektirir.
