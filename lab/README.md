# R2 — Şükrü

Implemented scripts: isolated A → B gateway → C sink, owned-resource cleanup,
fixed-device quarantine/release, and established UDP-flow smoke test.

## Dedicated Linux host commands

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

## Current validation limit

Windows unit tests and Bash syntax validation can run here. Real namespace/nftables
execution requires the dedicated Linux host. This PC currently has no WSL distro,
and Docker Desktop startup fails. Do not mark KAN-24/KAN-25 or G8 passed from static
checks. Generic shared CI intentionally does not run privileged lab scripts.
