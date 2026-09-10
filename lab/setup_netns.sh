#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lab/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
og_preflight
if [[ -e "$OG_STATE/owned" ]]; then
    og_verify
    echo 'Owned lab already exists; no changes made'
    exit 0
fi
for ns in "${OG_NAMES[@]}"; do
    if ip netns list | awk '{print $1}' | grep -qx "$ns"; then
        echo "Namespace $ns exists without ownership; refusing to adopt it" >&2
        exit 2
    fi
done
created=()
rollback() {
    local ns
    for ns in "${created[@]}"; do ip netns del "$ns" || true; done
    rm -f -- "$OG_STATE/owned.tmp"
}
trap rollback ERR
for ns in "${OG_NAMES[@]}"; do
    ip netns add "$ns"
    created+=("$ns")
    ip -n "$ns" link set lo up
    # IPv4-only first lab; no autoconfigured IPv6 escape paths.
    ip netns exec "$ns" sysctl -qw net.ipv6.conf.all.disable_ipv6=1
done
ip -n og-a link add og-a0 type veth peer name og-b0
ip -n og-a link set og-b0 netns og-b
ip -n og-b link add og-b1 type veth peer name og-c0
ip -n og-b link set og-c0 netns og-c
ip -n og-a addr add 10.203.1.2/24 dev og-a0
ip -n og-b addr add 10.203.1.1/24 dev og-b0
ip -n og-b addr add 10.203.2.1/24 dev og-b1
ip -n og-c addr add 10.203.2.2/24 dev og-c0
ip -n og-a link set og-a0 up
ip -n og-b link set og-b0 up
ip -n og-b link set og-b1 up
ip -n og-c link set og-c0 up
# Specific peer subnet routes only. No default route, NAT, bridge or host veth.
ip -n og-a route add 10.203.2.0/24 via 10.203.1.1
ip -n og-c route add 10.203.1.0/24 via 10.203.2.1
ip netns exec og-b sysctl -qw net.ipv4.ip_forward=1
ip netns exec og-b nft -f "$(dirname -- "${BASH_SOURCE[0]}")/ruleset.nft"
for ns in "${OG_NAMES[@]}"; do
    printf '%s %s\n' "$ns" "$(stat -Lc '%d:%i' "/run/netns/$ns")"
done >"$OG_STATE/owned.tmp"
mv -- "$OG_STATE/owned.tmp" "$OG_STATE/owned"
trap - ERR
echo 'Created isolated og-a -> og-b -> og-c; no default routes'
