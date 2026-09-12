# KAN-27 live source evidence — 2026-09-10

Dedicated local CachyOS Docker validation, Python 3.14.7, Linux
7.1.6-1-cachyos x86_64. Image input pins the Python amd64 manifest
`sha256:d893452fcd120ea9a7233972c85ea868255bde289a636fe76ff090427fe8fac9`;
dpkt 1.9.8. Run: `bash lab/run_live_docker.sh`.

| Phase | UDP sent | LAN ingress captured | Independent sink | Socket drops |
|---|---:|---:|---:|---:|
| Baseline | 100 | 100 | 100 | 0 |
| Forwarding quarantined | 100 | 100 | 0 | 0 |
| Released | 100 | 100 | 100 | 0 |

Every target tuple had 60 L3 bytes (20 IPv4 + 8 UDP + 32 known payload), expected
ports 39028→39027, EGRESS direction, camera device mapping and source namespace MAC.
The blocked phase proves this adapter observes at LAN ingress before the ordinary
forwarding drop. Known synthetic packets demonstrate counts, not dataset accuracy.

A separate 10,000-packet burst while a 4 KiB capture socket was deliberately not
read produced **9,991 detected socket drops**. The adapter raised CaptureError;
it did not silently accept the partial stream. Drop counts are run-dependent.
Socket loss evidence says nothing about NIC/driver/upstream losses.

The disposable container had no external network, host network/PID namespace,
Docker socket or bind mount. Container parent firewall/routes matched before/after;
all owned network namespaces were removed. Original evidence (ignored, local):
`artifacts/live-capture.kJBmPaxe/live-validation/summary.json` and sibling JSONL/logs.

31 unit tests passed (21 existing + 10 live tests), including PCAP/live equality
on independently constructed bytes and negative socket/timestamp cases. Ruff lint
and formatting passed. Hosted CI supplies shell syntax/ShellCheck and Windows/Linux
unit validation; no privileged capture runs on shared CI.

Limits: no live feature extraction, trusted idle-watermark protocol, versioned
ObservationHealth, N policy, trained RF, G8/G10 or ARM64 result is claimed. Capture
raw buffers temporarily contain payload; stdout exports metadata only. See
[source runbook](../sources/LIVE.md) for failure semantics and usage.
