# Development status — 2026-09-10 (Linux continuation)

PR #1 merged into main at 02:45:52 UTC. Its Windows/Linux CI checks passed.
GitHub collaborators verified: sicloid, pondilungs (Onur), Gabi8347 (Gabriel).
Şükrü explicitly confirmed approval of the existing architecture/contracts by all
three teammates. ADR-0001 is accepted; contracts are promoted to frozen `0.1.0`.
The former draft wire identifier is rejected; regenerate synthetic event fixtures.

## KAN-29 implementation follow-up

A model-independent checked detector boundary is implemented in gateway/detector.py.
It uses existing FeatureVector/DetectionResult contracts, validates compatibility
and never converts inference failure into NORMAL. Seven targeted tests pass;
real artifact loading, training, scheduling and policy remain separate work.
Owner review is required before Jira closure. See the gateway README.

## KAN-27 live adapter follow-up

Linux LAN ingress capture shares PacketNormalizer with PCAP and fails on socket
loss/truncation/timestamp faults. Isolated capture/drop/release and overflow
evidence: [LIVE_VALIDATION.md](LIVE_VALIDATION.md). Runtime health/window
integration remains separate.

## Completed technical validation

- PCAP adapter and contracts: 21 unit tests, Ruff lint/format and synthetic smoke
  pass on CachyOS Python 3.14.6. Hosted reference remains Python 3.14.7.
- KAN-24/KAN-25: real A→B→C namespaces, no public route, ASSURED UDP state
  before/during quarantine, sink stop, positive drops and release restore.
  Container setup/teardown is idempotent; parent rules/routes remain unchanged.
- KAN-36/KAN-37: digest-pinned Compose services, generated local credentials,
  Mosquitto QoS1 pub/sub/auth/ACL checks, PostgreSQL query and Grafana HTTP/login.
  Restart and repeated secret initialization preserve working credentials/state.
  New platform implementation needs Gabriel's PR review.
- Docker/WSL environment blockers from Windows are resolved on this Linux device.

See [Linux evidence](LINUX_VALIDATION.md), [lab runbook](../lab/README.md),
[platform runbook](../platform/README.md), and [team decision](G1_REVIEW.md).
[WEEK_ONE_R2.md](WEEK_ONE_R2.md) is retained as the historical Windows snapshot.

## Remaining sequence

1. R1: feature catalog/data audit, artifact compatibility, extractor and actual
   capture-aware train/validation/test split; train RF and calibrate on validation.
2. R2: live adapter, windows, state machine, runtime
   enforcement/release, replay/leakage and UDS bridge.
3. R3: full dependency lock (KAN-10), telemetry adapter, migrations, MQTT consumer,
   PostgreSQL datasource/dashboard and measurement harnesses.
4. G5/G8: integrate actual traffic/extractor/RF/state/enforcement, prove sink stop
   and release restore independently of telemetry. The lab probe is not this gate.
5. G10: real StateEvent→UDS→MQTT→PostgreSQL→Grafana. Service health is not this gate.
6. ARM64/Pi validation, experiments, results freeze and reproducible final demo.

Pi hardware, data/ML implementation and real integration gates remain separate
work; none is claimed complete from synthetic fixtures or this x86_64 lab run.
