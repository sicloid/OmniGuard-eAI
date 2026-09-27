# OmniGuard eAI — final product path

OmniGuard is a local IoT botnet detection and reversible containment prototype.
Its primary output is an enforced network decision, not a dashboard prediction:

```text
traffic / audited PCAP
  -> AF_PACKET capture and shared feature extractor
  -> pinned Random Forest decision
  -> N-window device policy
  -> nftables quarantine with kernel timeout
  -> independent TCP/UDP traffic stops
  -> release restores traffic

StateEvent (non-blocking side channel)
  -> verified Unix socket peer
  -> MQTT QoS 1
  -> deduplicating PostgreSQL consumer
  -> Grafana dashboard
```

## Demonstrate it

On a Linux host with Docker and Compose:

```sh
./demo.sh
```

This starts and checks MQTT, PostgreSQL and Grafana, runs the isolated
capture-to-nftables wiring demonstration, then verifies the sealed telemetry and
G10 evidence. The core lab uses `--network none` and owned disposable network
namespaces. It does not replay traffic onto the host or a public network.

The default core demonstration trains a clearly labelled synthetic forest to
prove runtime wiring. To rerun the real-model IoT-23 gate with the externally
stored, hash-pinned artifacts:

```sh
./demo.sh real /path/to/omniguard-kan19-model /path/to/g8-prepared-8-1
```

The supplied files must match the hashes enforced by the runner. Historical
real-model G8 and end-to-end G10 evidence is committed under `docs/evidence/` and
can be checked without possessing the model or PCAP:

```sh
./demo.sh evidence
```

## What is complete

- The gateway captures traffic, builds five-second feature windows and loads a
  byte-pinned Random Forest artifact only after compatibility and hash checks.
- Consecutive anomalous windows drive a device policy; observation loss never
  becomes a benign decision.
- nftables blocks the selected device's external TCP and UDP traffic. Kernel
  timeout restores traffic even if the controller process dies.
- Enforcement does not wait for telemetry. UDS/MQTT failure is counted and can
  spool for recovery without changing the kernel decision.
- MQTT redelivery is idempotent in PostgreSQL, and Grafana reads through a
  provisioned read-only database identity.
- The sealed G10 run passed normal, duplicate and broker-outage scenarios with
  every produced state event present at the dashboard boundary.

## Evidence boundary

The real G8 run proves the product chain on the declared IoT-23 validation slice;
it is not a new accuracy estimate. The frozen model transferred poorly to three
unseen IoT-23 malware families in the later holdout experiment, so the prototype
must not be presented as a generally accurate production IDS. Its defensible
result is a working, fail-safe local detection/containment architecture with
measured limitations and reproducible acceptance evidence.
