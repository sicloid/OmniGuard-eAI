# KAN-32 evidence — 2026-09-10

`bash lab/run_replay_docker.sh` passed on CachyOS Linux 7.1.6-1-cachyos x86_64,
in the pinned Python 3.14.7/dpkt 1.9.8 capture container from PR #7.

Prepared benign fixture hash:
`7a47dd853300191ea1ce96c0c7890f99451b104110e4e5a9a8103f29a8d554d9`.
100 packets over 0.99 capture seconds, replayed at speed 2; scheduled span 495ms.

| Run | Sent | LAN capture | Independent sink | Maximum schedule lag |
|---|---:|---:|---:|---:|
| 5dabfac9-13f0-4db6-84bd-d27b6e71dd4c | 100 | 100 | 100 | 177,739ns |
| 593e6f0f-b22a-413a-a0a7-854cca3b1306 | 100 | 100 | 100 | 275,387ns |

Both runs recorded reference packet 21, capture timestamp `1700000000.200000000`,
and ordered scheduled/send-begin/send-return times. The manifest explicitly labels
this benign run's reference as replay submission, not attack onset or containment.
Observed scheduling lag is a local fixture result, not a guaranteed performance bound.

A real attempt in the container parent namespace was rejected with exit 2, before
sender creation, and retained a failed manifest. Container parent rules/routes
matched before/after; all A/B/C namespaces were removed. Evidence was copied to
`artifacts/replay.2gvvW9qI/replay-validation/` (ignored, local), including generated
PCAP, manifests, per-send logs, capture/sink output and host-refusal error.

Nine added unprivileged tests cover immutable snapshot/hash, input duration/size/MTU,
late malformed records, ordered timing/speed/t0, failed-send evidence, failed-run
manifest, unique IDs and platform guard. Total suite: 40 passing tests, including
31 tests from the PR #7 base. Ruff lint/format and shell syntax pass locally;
hosted Linux CI additionally runs ShellCheck.

Scope: prepared unidirectional Ethernet/IPv4 lab traffic only. Real dataset
conversion/label audit, sink leakage correlation, runtime enforcement/ACK,
trained RF, G8/G10 and ARM64 remain separate. See [runbook](../lab/REPLAY.md).
