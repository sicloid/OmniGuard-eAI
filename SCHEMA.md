# OmniGuard runtime contracts — 0.1.0

Status: team-approved and frozen on 2026-09-10. Şükrü confirmed that Onur,
Gabriel and Şükrü approved the existing architecture and contracts. Sources:
the supplied V2 planning documents and [ADR-0001](docs/adr/0001-foundation.md).
The initial draft is promoted to `0.1.0` without changing fields or semantics.
Consumers reject the former `0.1.0-draft` wire identifier; regenerate stub events.

Approval provenance update: Gabriel explicitly accepted in his PR #2 review;
Onur approval remains Lead-reported, with direct R1 evidence pending in KAN-63.
See [G1 review](docs/G1_REVIEW.md). This does not approve proposed ADR-0002.

All contracts are immutable Python dataclasses in `core/schema.py`. Constructors
reject malformed required fields, invalid enums and nonfinite numeric values.
They do not perform capture, inference, state policy, firewall or network I/O.

| Contract | Producer → consumer | Fields / meaning |
|---|---|---|
| PacketTuple | R2 source → R1 extractor | timestamp, device_id, src_mac, src_ip, src_port, dst_ip, dst_port, protocol, tcp_flags, packet_length, direction |
| FeatureVector | R1 extractor → model | device_id, window_start, window_end, feature_schema_version, feature_order, values |
| DetectionResult | model → R2 state machine | device_id, window_ts, model_id, model_version, score, classification, threshold |
| StateEvent | R2 state machine → enforcement / telemetry | device_id, previous_state, new_state, reason, timestamp, expires_at |
| TelemetryPayload | R3 adapter → consumer | schema_version, run_id, event_id, nested StateEvent |

## Network and time semantics

- Packet length is L3 IP length in bytes, excluding Ethernet headers. IPv6
  jumbograms are outside this initial draft.
- Protocol is the IP protocol number; flags are a TCP bitmask, zero for non-TCP.
- Ports are null when unavailable (e.g. ICMP or noninitial fragments); they must
  never be inferred by filling in a guessed transport port.
- `src_mac` may be null for captures lacking Ethernet metadata. MAC normalization
  belongs to the future source adapter.
- EGRESS: source in configured LAN, destination outside. INGRESS: reverse.
  LOCAL: both inside. Both outside must be excluded by the adapter, not relabeled.
- `device_id` is an internal stable mapping, not an ML feature. Primary extraction
  will use EGRESS. Mapping and LAN membership are R2 responsibilities.
- Event/packet timestamps are UTC Unix seconds. Feature windows are half-open
  `[window_start, window_end)`; baseline duration is 5 seconds, aligned to Unix epoch.
  `window_ts` denotes window start. Runtime performance durations will use a
  separate monotonic clock; never subtract timestamps from different clock domains.

## Features and model output

Feature names and values are ordered tuples of equal nonzero length with unique
names and finite numeric values. The actual feature catalog remains R1's G2 task.
`stub-0.1` with `stub_packet_count, stub_l3_bytes` is synthetic integration data,
not the production feature catalog or an implementation of the shared extractor.

RF score draft range is [0,1]; `score >= threshold` means ANOMALOUS, otherwise
NORMAL. This does not imply a calibrated probability. A future Isolation Forest
requires an explicit score contract decision. Models never emit state/firewall decisions.

States are NORMAL, SUSPICIOUS, QUARANTINED. StateEvent validates the envelope and
expiry ordering, not the allowable transition graph or N policy. R2 owns those
rules. A synthetic QUARANTINED event is never proof that traffic stopped.

## Telemetry

`TelemetryPayload.to_dict()` produces JSON-compatible data with nested event fields.
No raw packet, IP/MAC or payload bytes are included. Consumer must reject unknown
schema versions. The producer must preserve event_id across retries; real UUID
generation, deduplication, UDS framing and MQTT topic/QoS policy remain R2/R3 work.
Stable stub IDs are fixture-only, not suitable for real repeated experiment runs.

## Model artifact contract — KAN-9

`model.joblib` + `model.meta.json` must contain model_id/version, schema_version,
feature_schema_version, feature_order, window_seconds/semantics, threshold,
training manifest SHA-256, Python/sklearn/numpy versions. The metadata document
also requires `meta_format` (`omniguard-model-meta/1`) and `model_sha256`.
These artifact fields document R1's PR #11 proposal and the authorized Lead review
follow-up; they do not change the five runtime 0.1.0 envelopes.

`model/artifact.py` checks format, pinned bytes and runtime compatibility before
deserialization. Deployment must pin both the model SHA-256 and the SHA-256 of
the exact metadata bytes outside the artifact directory. Metadata includes the
threshold, identity and feature order: checking only the model hash leaves those
fields unprotected. Do not derive expected pins from candidate files at load time.
Read/deserialization failure produces an ArtifactError, never a NORMAL decision.

Only trusted locally produced artifacts may be loaded in an unprivileged process.
Python major.minor and exact sklearn/numpy versions are checked today; the full
dependency lock also records scipy/joblib, but explicit loader checks for those
require a versioned artifact follow-up. No trained production model, real-data
accuracy or Pi compatibility is claimed by the loader tests.

## V3 follow-up proposals (not part of 0.1.0)

[ADR-0002](docs/adr/0002-bounded-containment.md) proposes ObservationHealth,
EnforcementResult and separate detection/health telemetry records. None is added
to these dataclasses by the architecture review. StateEvent describes a policy
transition; it is not evidence of successful firewall application. Current
TelemetryPayload cannot carry anomaly scores or enforcement results implicitly.
