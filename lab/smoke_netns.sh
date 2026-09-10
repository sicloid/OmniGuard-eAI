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
cleanup() {
    [[ -z "$source_pid" ]] || { kill "$source_pid" 2>/dev/null || true; wait "$source_pid" 2>/dev/null || true; }
    [[ -z "$sink_pid" ]] || { kill "$sink_pid" 2>/dev/null || true; wait "$sink_pid" 2>/dev/null || true; }
    bash "$HERE/quarantine.sh" release
}
trap cleanup EXIT
fail() { echo "FAIL: $*; evidence: $LOGS" >&2; exit 1; }
for ns in og-a og-b og-c; do
    [[ -z $(ip -n "$ns" route show default) ]] || fail "default route in $ns"
    if ip -n "$ns" route get 198.51.100.1 >/dev/null 2>&1; then fail "outside route in $ns"; fi
done
ip -n og-b -j link >"$LOGS/gateway-links.json"
ip netns exec og-a ping -c 2 -W 1 10.203.2.2 >"$LOGS/ping.txt" || fail 'A cannot reach C through B'
bash "$HERE/quarantine.sh" release
ip netns exec og-c python3 "$HERE/udp_probe.py" sink >"$LOGS/sink.txt" 2>"$LOGS/sink.err" &
sink_pid=$!
sleep 0.3
ip netns exec og-a python3 "$HERE/udp_probe.py" source >"$LOGS/source.txt" 2>"$LOGS/source.err" &
source_pid=$!
sleep 1
kill -0 "$source_pid" "$sink_pid" || fail 'probe process exited'
before=$(wc -l <"$LOGS/sink.txt")
((before > 0)) || fail 'no baseline sink traffic'
# UDP stream assurance may require several seconds on newer kernels. Poll the
# actual state instead of assuming that one second of echo traffic is enough.
for ((attempt=0; attempt<50; attempt++)); do
    ip netns exec og-b conntrack -L -p udp --orig-src 10.203.1.2 --orig-dst 10.203.2.2 >"$LOGS/conntrack-before.txt" 2>"$LOGS/conntrack.err"
    if grep -q ASSURED "$LOGS/conntrack-before.txt"; then break; fi
    kill -0 "$source_pid" "$sink_pid" || fail 'probe exited before flow assurance'
    sleep 0.1
done
grep -q ASSURED "$LOGS/conntrack-before.txt" || fail 'bidirectional established flow not observed'
bash "$HERE/quarantine.sh" apply
# Allow already-in-flight packets to drain; this is not a leakage measurement.
sleep 0.3
blocked_start=$(wc -l <"$LOGS/sink.txt")
sleep 1
blocked_end=$(wc -l <"$LOGS/sink.txt")
kill -0 "$source_pid" "$sink_pid" || fail 'probe died while quarantined'
[[ "$blocked_start" == "$blocked_end" ]] || fail 'established traffic bypasses quarantine'
ip netns exec og-b conntrack -L -p udp --orig-src 10.203.1.2 --orig-dst 10.203.2.2 >"$LOGS/conntrack-quarantined.txt" 2>>"$LOGS/conntrack.err"
grep -q ASSURED "$LOGS/conntrack-quarantined.txt" || fail 'established state was not preserved'
ip netns exec og-b nft -j list counter inet omniguard quarantine_drops >"$LOGS/drops.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert any(x.get("counter",{}).get("packets",0)>0 for x in d["nftables"])' "$LOGS/drops.json" || fail 'no drop evidence'
bash "$HERE/quarantine.sh" release
sleep 1
after=$(wc -l <"$LOGS/sink.txt")
((after > blocked_end)) || fail 'release did not restore same flow'
ip netns exec og-b nft list table inet omniguard >"$LOGS/ruleset.txt"
printf 'PASS: baseline=%s blocked_delta=%s restored=%s; evidence: %s\n' "$before" "$((blocked_end-blocked_start))" "$((after-blocked_end))" "$LOGS"
