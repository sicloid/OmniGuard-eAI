#!/usr/bin/env bash
# Real forwarding/established-flow quarantine test. Dedicated Linux lab only.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly HERE
# shellcheck source=lab/common.sh
source "$HERE/common.sh"
og_preflight
og_verify
for tool in python3 ping conntrack; do command -v "$tool" >/dev/null || exit 2; done
# Release lock before invoking the guarded quarantine helper.
flock -u 9
LOGS=$(mktemp -d /tmp/omniguard-smoke.XXXXXXXX)
readonly LOGS
source_pid=''
sink_pid=''

stop_probes() {
    [[ -z "$source_pid" ]] || {
        kill "$source_pid" 2>/dev/null || true
        wait "$source_pid" 2>/dev/null || true
        source_pid=''
    }
    [[ -z "$sink_pid" ]] || {
        kill "$sink_pid" 2>/dev/null || true
        wait "$sink_pid" 2>/dev/null || true
        sink_pid=''
    }
}

cleanup() {
    stop_probes
    bash "$HERE/quarantine.sh" release
}
trap cleanup EXIT
fail() { echo "FAIL: $*; evidence: $LOGS" >&2; exit 1; }

for ns in og-a og-b og-c; do
    [[ -z $(ip -n "$ns" route show default) ]] || fail "default route in $ns"
    if ip -n "$ns" route get 198.51.100.1 >/dev/null 2>&1; then
        fail "outside route in $ns"
    fi
done

ip -n og-b -j link >"$LOGS/gateway-links.json"
ip netns exec og-a ping -c 2 -W 1 10.203.2.2 >"$LOGS/ping.txt" ||
    fail 'A cannot reach C through B'
bash "$HERE/quarantine.sh" release

# --- Established UDP: quarantine must win before established/related. ---
ip netns exec og-c python3 "$HERE/udp_probe.py" sink     >"$LOGS/udp-sink.txt" 2>"$LOGS/udp-sink.err" &
sink_pid=$!
sleep 0.3
ip netns exec og-a python3 "$HERE/udp_probe.py" source     >"$LOGS/udp-source.txt" 2>"$LOGS/udp-source.err" &
source_pid=$!
sleep 1
kill -0 "$source_pid" "$sink_pid" || fail 'UDP probe process exited'
udp_before=$(wc -l <"$LOGS/udp-sink.txt")
((udp_before > 0)) || fail 'no baseline UDP sink traffic'
for ((attempt=0; attempt<50; attempt++)); do
    ip netns exec og-b conntrack -L -p udp         --orig-src 10.203.1.2 --orig-dst 10.203.2.2         >"$LOGS/udp-conntrack-before.txt" 2>"$LOGS/udp-conntrack.err"
    if grep -q ASSURED "$LOGS/udp-conntrack-before.txt"; then break; fi
    kill -0 "$source_pid" "$sink_pid" || fail 'UDP probe exited before flow assurance'
    sleep 0.1
done
grep -q ASSURED "$LOGS/udp-conntrack-before.txt" ||
    fail 'bidirectional established UDP flow not observed'

bash "$HERE/quarantine.sh" apply
# Allow already-in-flight packets to drain; this is not a leakage measurement.
sleep 0.3
udp_blocked_start=$(wc -l <"$LOGS/udp-sink.txt")
sleep 1
udp_blocked_end=$(wc -l <"$LOGS/udp-sink.txt")
kill -0 "$source_pid" "$sink_pid" || fail 'UDP probe died while quarantined'
[[ "$udp_blocked_start" == "$udp_blocked_end" ]] ||
    fail 'established UDP traffic bypasses quarantine'
ip netns exec og-b conntrack -L -p udp     --orig-src 10.203.1.2 --orig-dst 10.203.2.2     >"$LOGS/udp-conntrack-quarantined.txt" 2>>"$LOGS/udp-conntrack.err"
grep -q ASSURED "$LOGS/udp-conntrack-quarantined.txt" ||
    fail 'established UDP state was not preserved'

bash "$HERE/quarantine.sh" release
sleep 1
udp_after=$(wc -l <"$LOGS/udp-sink.txt")
((udp_after > udp_blocked_end)) || fail 'release did not restore same UDP flow'
stop_probes

# --- Established TCP: the same rule ordering must stop a live connection. ---
ip netns exec og-c python3 "$HERE/tcp_probe.py" sink     >"$LOGS/tcp-sink.txt" 2>"$LOGS/tcp-sink.err" &
sink_pid=$!
sleep 0.3
ip netns exec og-a python3 "$HERE/tcp_probe.py" source     >"$LOGS/tcp-source.txt" 2>"$LOGS/tcp-source.err" &
source_pid=$!
for ((attempt=0; attempt<50; attempt++)); do
    if [[ -s "$LOGS/tcp-sink.txt" ]]; then break; fi
    kill -0 "$source_pid" "$sink_pid" || fail 'TCP probe exited before baseline traffic'
    sleep 0.1
done
tcp_before=$(wc -l <"$LOGS/tcp-sink.txt")
((tcp_before > 0)) || fail 'no baseline TCP sink traffic'
ip netns exec og-b conntrack -L -p tcp     --orig-src 10.203.1.2 --orig-dst 10.203.2.2     >"$LOGS/tcp-conntrack-before.txt" 2>"$LOGS/tcp-conntrack.err"
grep -q ESTABLISHED "$LOGS/tcp-conntrack-before.txt" ||
    fail 'established TCP flow not observed'

bash "$HERE/quarantine.sh" apply
sleep 0.3
tcp_blocked_start=$(wc -l <"$LOGS/tcp-sink.txt")
sleep 1
tcp_blocked_end=$(wc -l <"$LOGS/tcp-sink.txt")
kill -0 "$source_pid" "$sink_pid" || fail 'TCP probe died while quarantined'
[[ "$tcp_blocked_start" == "$tcp_blocked_end" ]] ||
    fail 'established TCP traffic bypasses quarantine'
ip netns exec og-b conntrack -L -p tcp     --orig-src 10.203.1.2 --orig-dst 10.203.2.2     >"$LOGS/tcp-conntrack-quarantined.txt" 2>>"$LOGS/tcp-conntrack.err"
grep -q ESTABLISHED "$LOGS/tcp-conntrack-quarantined.txt" ||
    fail 'established TCP state was not preserved'

bash "$HERE/quarantine.sh" release
sleep 2
tcp_after=$(wc -l <"$LOGS/tcp-sink.txt")
((tcp_after > tcp_blocked_end)) || fail 'release did not restore same TCP flow'
stop_probes

# --- Kernel lease survives controller exit and expires without a userspace timer. ---
ip netns exec og-b nft add element inet omniguard quarantined_v4     '{ 10.203.1.2 timeout 1s }'
ip netns exec og-b nft get element inet omniguard quarantined_v4     '{ 10.203.1.2 }' >"$LOGS/kernel-lease-active.txt" ||
    fail 'kernel lease was not active immediately after apply'
sleep 1.3
if ip netns exec og-b nft get element inet omniguard quarantined_v4     '{ 10.203.1.2 }' >"$LOGS/kernel-lease-after-expiry.txt" 2>&1; then
    fail 'kernel timeout did not release the element after controller exit'
fi

ip netns exec og-b nft -j list counter inet omniguard quarantine_drops >"$LOGS/drops.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert any(x.get("counter",{}).get("packets",0)>0 for x in d["nftables"])'     "$LOGS/drops.json" || fail 'no drop evidence'
ip netns exec og-b nft list table inet omniguard >"$LOGS/ruleset.txt"

printf 'PASS: UDP baseline=%s blocked_delta=%s restored=%s; TCP baseline=%s blocked_delta=%s restored=%s; kernel_expiry=PASS; evidence: %s\n'     "$udp_before" "$((udp_blocked_end-udp_blocked_start))" "$((udp_after-udp_blocked_end))"     "$tcp_before" "$((tcp_blocked_end-tcp_blocked_start))" "$((tcp_after-tcp_blocked_end))" "$LOGS"
