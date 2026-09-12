# KAN-32 — prepared PCAP replay and reference t0

This harness replays an audited, **prepared** classic Ethernet PCAP from the owned
`og-a` namespace through B to C. It is a single-source IPv4 baseline, not automatic
conversion of arbitrary CICIoT2023/IoT-23 captures or interactive botnet execution.
No capture is silently relabelled or IP-rewritten. Data preparation and label/time
mapping remain R1/R2 audit work. Protocol replies/stateful application behavior are
not reconstructed by packet replay.

## Prepared input and execution

All records must have ordered nonnegative timestamps, untagged Ethernet, IPv4
without options/fragments, exact frame/IP lengths within the source MTU, valid IPv4
header checksum, source `10.203.1.2`, destination `10.203.2.2`. No record is silently
filtered. Transport checksums must be prepared correctly by the producer; this
harness validates IP headers and parser structure, not every transport checksum.
VLAN, IPv6, bidirectional/scenario conversion and fragmented replay need explicit
preparation policies. These restrictions describe this fixed lab profile.

Supply JSON provenance, for example:

```json
{"source": "benign synthetic oracle", "transformations": ["generated directly with lab IPs"]}
```

For dataset inputs include original parent-capture hash, label mapping/exclusions
and exact preparation commands in this record. The harness records provenance;
it cannot verify the truth of user-supplied labels. Its only automatic rewrite is
Ethernet source/destination to the verified source/gateway interface MACs, recorded
in the manifest. IP headers and transport payload remain unchanged.

Inside the already-created dedicated lab container:

```sh
ip netns exec og-a python -m lab.replay prepared.pcap \
  --provenance preparation.json --output /tmp/replay-runs \
  --speed 1 --reference-record 1
```

`--reference-record` is one-based. By default t0 means replay reference submission;
use `--attack-start` only when that record has an externally audited attack label.
It does not turn a benign fixture into an attack. `--max-bytes` defaults to 256 MiB
of temporary disk snapshot; `--max-seconds` defaults to 3600 capture seconds.
Slower speeds extend wall-clock runtime. Interrupt with Ctrl+C; failed/cancelled
runs are retained. Snapshot memory is chunk-bounded; event log disk grows with the
number of records and must have sufficient space.

Before opening a sender, the entire private input snapshot is audited and hashed.
Sending uses the same snapshot, protecting against later input-path changes.
The guard verifies the root-owned A/B/C ownership record, namespace inode/device,
expected interface names, no IPv4/IPv6 default route, and that the process is
actually in og-a. Host or gateway execution is refused. The socket binds only to
og-a0; the code changes no route/interface/firewall. This is not a sandbox for
untrusted programs; use the dedicated network-none container runner.

## Run evidence and clocks

Each UUID run directory contains an atomic `manifest.json` and `events.jsonl`.
The manifest retains prepared-PCAP SHA-256, source provenance, harness file hash,
Python/dpkt/kernel versions, namespace identities, MAC rewrite, parameters and
status. No raw packet/payload is written to the event log.

Scheduling uses Decimal capture-time deltas scaled by speed and a monotonic origin.
For every packet the log records an intent, scheduled monotonic time, actual
send-call begin and return, original capture timestamp and L3 byte count. The
initial UTC sample is bracketed by two monotonic reads; do not subtract raw UTC
and monotonic timestamps. This is an initial same-host mapping, not clock-drift
correction or synchronization between hosts/time namespaces.

The reference t0 is a source submission interval (`send_begin_ns` to
`send_return_ns`). **A send return is not a wire timestamp, sink receipt, firewall
ACK or containment.** KAN-33 must correlate separate sink/enforcement evidence.
Per-record logging overhead is included in measured schedule lag; this is not a
hard-real-time traffic generator. Do not claim achieved wire rate from scheduling.

On failed/interrupted sends, intent without return means unknown submission,
never a successful packet. The log retains clock mapping and prior returns even
if the final manifest has no completed-run t0 summary. Abrupt kill/power loss can
leave `running`; that is incomplete, not success. Atomic rename does not promise
power-loss durability. Clean completion proves only source submission.

## Reproducible dedicated validation

```sh
bash lab/run_replay_docker.sh
```

This builds the PR #7 Python 3.14.7 amd64 capture image and runs a separate replay
oracle in network-none Docker, without host network/PID, sockets or bind mounts.
It generates a benign 100-packet PCAP, repeats replay at 2× speed, checks independent
capture/sink counts, distinct run IDs and identical prepared hash, t0 record 21,
495ms scheduled span, parent-namespace refusal and namespace/rule/route cleanup.
Evidence: ignored `artifacts/replay.*`. No PCAP/model/dataset enters Git.

The fixture proves harness behavior, not dataset validity, RF accuracy, leakage,
G8/G10, real malware behavior or ARM64 performance. See
[measured evidence](../docs/REPLAY_VALIDATION.md). Unit tests run without privileges:
`.venv/bin/python -m unittest discover -s tests -p test_replay.py -v`.
