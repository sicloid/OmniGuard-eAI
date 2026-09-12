# R2 — Şükrü

Implemented scripts: isolated A → B gateway → C sink, owned-resource cleanup,
fixed-device quarantine/release, and established UDP-flow smoke test.

## Dedicated Linux host commands

CachyOS with Docker running, from the repository root:

```sh
bash lab/run_docker.sh
```

The validated runner creates a disposable container with `--network none`, adds
NET_ADMIN/SYS_ADMIN capabilities and unconfines system paths for namespace-local
sysctl writes. No host filesystem/socket/network/PID namespace is mounted.
This is for the reviewed benign probes, not a sandbox for untrusted code.
Logs/counters survive success or failure in `artifacts/linux-lab.*`; the runner
removes its own container. Docker access is required; sudo is not.
The base image digest is pinned; distro packages follow Bookworm updates and
executed tool versions are printed in evidence.

For direct dedicated CachyOS execution, equivalent packages are:
`sudo pacman -S --needed iproute2 nftables conntrack-tools iputils util-linux python procps-ng`.
The recorded run used Docker on CachyOS; the direct-host path is documented below.

Requires root, Bash, iproute2, nftables, conntrack, iputils-ping, util-linux
(flock), Python 3, procps (sysctl), coreutils, awk and grep. Debian/Ubuntu packages:

```sh
sudo apt-get install iproute2 nftables conntrack iputils-ping util-linux python3 procps
sudo bash lab/setup_netns.sh
sudo bash lab/smoke_netns.sh
sudo bash lab/teardown_netns.sh
```

No external replay or malicious traffic is used. The probe sends fixed benign
UDP echo messages at a bounded rate solely between 10.203.1.2 and 10.203.2.2.
Network layout:

```text
og-a / og-a0    10.203.1.2/24
       ↕
og-b / og-b0    10.203.1.1/24
og-b / og-b1    10.203.2.1/24
       ↕
og-c / og-c0    10.203.2.2/24
```

Only specific peer-subnet routes are configured. No default route, host-side veth,
NAT, bridge, Tailscale advertisement or host sysctl change. IPv6 is disabled inside
the lab namespaces only. The forwarding firewall exists only in og-b, in table
`inet omniguard`; no host ruleset flush or conntrack flush.

The smoke test requires baseline sink packets, an ASSURED bidirectional conntrack
entry, zero sink growth during quarantine with the source still alive, nft drop
counter growth, and restored traffic after release. It retains evidence under
`/tmp/omniguard-smoke.*`. The drain interval is explicitly not a leakage measurement.
It is a G1/G2 network proof, not RF integration or the G8 core gate.

Quarantine drop precedes established/related accept in the same forward chain;
existing connection state is preserved to prove it cannot bypass the drop.
No flowtable/offload is configured. See the official
[nftables chain semantics](https://netfilter.org/projects/nftables/manpage.html).

Ownership recorded in root-only `/run/omniguard-lab/owned` includes namespace inode
identities. Unowned collisions or changed identities are refused. Setup is
idempotent for an owned lab; teardown refuses namespaces with live processes and
never kills unrelated processes. Stop captures/probes before cleanup. If a host
crashes during setup, inspect any orphan namespaces manually; do not adopt them.

## Validation — 2026-09-10

Real Linux container execution passed on CachyOS kernel 7.1.6: A→B→C ping,
no default/public route, ASSURED UDP before/during quarantine, zero quarantine
sink growth, positive drops, and release restore. Setup/teardown idempotence,
namespace cleanup and unchanged parent rules/routes passed. The test now polls
up to five seconds for UDP assurance. See [evidence](../docs/LINUX_VALIDATION.md).
This is KAN-24/KAN-25 proof, not G8, general runtime enforcement, TCP/IPv6 coverage,
throughput or a containment-leakage measurement.

## Live source validation (KAN-27)

`bash lab/run_live_docker.sh` validates ingress capture/counts before forwarding
drop, release recovery and forced socket-overflow detection in a separate pinned
Python 3.14.7 amd64 container. See [source runbook](../sources/LIVE.md). This command
is dedicated-host-only; it does not pass G8 or validate a production enforcer.

## Prepared PCAP replay (KAN-32)

See [REPLAY.md](REPLAY.md) for owned-namespace replay, input preparation, run manifests
and t0 semantics. `bash lab/run_replay_docker.sh` validates repeated source/capture/
sink counts in the dedicated Docker lab; source send completion is not containment.
