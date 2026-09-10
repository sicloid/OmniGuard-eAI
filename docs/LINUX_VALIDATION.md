# Linux continuation evidence — 2026-09-10

## Environment and existing review

CachyOS x86_64, kernel `7.1.6-1-cachyos`, Docker 29.7.2, Compose 5.4.0.
Application virtual environment: Python 3.14.6, dpkt 1.9.8, Ruff 0.15.6;
editable build uses setuptools 82.0.1. CI reference is Python 3.14.7.
PR #1 was merged as `cfc118e` at 02:45:52 UTC; Windows/Linux checks succeeded.
All three GitHub collaborators are present. Team contract approval was explicitly
confirmed by Şükrü in this continuation; no independent meeting transcript is claimed.

## Real network proof (KAN-24/KAN-25)

Command: `bash lab/run_docker.sh`. Runs the reviewed lab in a disposable Docker
container with no external network and no host mounts; same CachyOS kernel.
Tool userland: Debian Bookworm, Python 3.11.2 (stdlib-only UDP probe), nftables
1.0.6, conntrack 1.4.7. This is not the application interpreter.

Initial real execution exposed a race: one second of echo traffic was insufficient
for UDP ASSURED state on this kernel. The smoke now polls actual state for up to
five seconds, retaining a failure if assurance never arrives. It also explicitly
checks that ASSURED state remains during quarantine; no conntrack flush is used.

Final recorded run:

```text
PASS: baseline=20 blocked_delta=0 restored=20
PASS: setup/teardown idempotence and namespace cleanup
```

- A→C ping traverses B. All three namespaces have no default/public route.
- UDP `10.203.1.2:49001 → 10.203.2.2:49000` is `[ASSURED]` before and during block.
- Quarantine sink growth after drain: 0; source and sink remain alive.
- nftables quarantine counter: 9 packets / 423 L3 bytes.
- Release restores 20 sink packets in the observation interval.
- Container parent rules/routes compare equal before/after; lab namespaces removed.

Raw local evidence: `artifacts/linux-lab.3P0eVGbK/`, including `run.log`, parent
snapshots and `omniguard-smoke.EcSdosSh/{conntrack-before.txt,conntrack-quarantined.txt,
drops.json,ruleset.txt,ping.txt,sink.txt}`. Each rerun creates a new directory.
The brief drain interval is deliberately excluded; these values are not leakage
metrics, ML effectiveness, G8, TCP/IPv6 coverage or Pi/ARM64 validation.

## Platform proof (KAN-36/KAN-37)

Commands: `python3 platform/init_secrets.py`, `docker compose -f
platform/compose.yaml up -d --wait`, `python3 platform/smoke.py`.

```text
PASS: three healthy services; PostgreSQL SELECT 1; MQTT QoS1 pub/sub;
anonymous/unauthorized-topic rejection; Grafana HTTP health and admin login.
```

The same checks passed after service restart and repeated initialization (existing
credentials preserved). MQTT/Grafana publish loopback-only endpoints; PostgreSQL
has no host port. Docker 29 did not publish ports from an internal-only network,
so MQTT/Grafana have a separate local-access network. Packet namespaces are not
connected to either Compose network. Mosquitto 2.0 emits a negative PUBACK warning
with exit status 0 for a forbidden topic; the smoke checks the rejection text.

Image manifests are pinned in Compose for Mosquitto 2.0.22, PostgreSQL 17.6 and
Grafana 12.1.1. Credentials and runtime artifacts are ignored by Git and Docker
build context. Service restart preserves named volumes. Services are left running.
New R3 code is provided for Gabriel's review; no application event database,
consumer, datasource/dashboard, real StateEvent chain or G10 success is claimed.

## Application checks

Fresh editable install succeeded. 21 unittest cases pass, including classic PCAP
parsing/CLI, contract roundtrip, frozen `0.1.0` and rejection of the old draft.
Ruff lint/format pass. The deterministic smoke reports G8/G10 false as intended.
The CI workflow adds the unprivileged platform smoke; no privileged lab test is
scheduled on shared GitHub runners. Current PR Checks is the hosted CI authority.

## Publication and Jira readback

[PR #2](https://github.com/sicloid/OmniGuard-eAI/pull/2), implementation `281cf32`.
Both push and PR workflows passed Windows, Linux (including ShellCheck), and
platform jobs: [PR run](https://github.com/sicloid/OmniGuard-eAI/actions/runs/34449640577).
CODEOWNERS errors API returned an empty list for the published feature branch.
Jira descriptions were updated with evidence and read back: KAN-7/8/11/24/25/26
are Done; new KAN-36/37 are In Review for Gabriel. PR #2 remains open for review.
