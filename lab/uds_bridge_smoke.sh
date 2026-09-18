#!/usr/bin/env bash
# KAN-34: parent namespace UDS server + og-b sender, with no IP/default route.
set -Eeuo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
readonly HERE
# shellcheck source=lab/common.sh
source "$HERE/common.sh"
og_preflight
og_verify

SOCKET="$OG_STATE/events.sock"
EVIDENCE=$(mktemp -d /tmp/omniguard-uds.XXXXXXXX)
server_pid=''

cleanup() {
    [[ -z "$server_pid" ]] || {
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    }
    rm -f -- "$SOCKET"
}
trap cleanup EXIT

fail() { echo "FAIL: $*; evidence: $EVIDENCE" >&2; exit 1; }

for ns in "${OG_NAMES[@]}"; do
    [[ -z $(ip -n "$ns" route show default) ]] || fail "default route in $ns"
    if ip -n "$ns" route get 198.51.100.1 >/dev/null 2>&1; then
        fail "outside route in $ns"
    fi
done

python3 "$HERE/uds_bridge_probe.py" server "$SOCKET" >"$EVIDENCE/server.json" 2>"$EVIDENCE/server.err" &
server_pid=$!

for ((attempt=0; attempt<50; attempt++)); do
    [[ -S "$SOCKET" ]] && break
    kill -0 "$server_pid" 2>/dev/null || fail "UDS server exited before bind"
    sleep 0.05
done
[[ -S "$SOCKET" ]] || fail "UDS socket was not created"
[[ $(stat -c '%a' "$SOCKET") == 600 ]] || fail "UDS socket mode is not 0600"

ip netns exec og-b python3 "$HERE/uds_bridge_probe.py" gateway "$SOCKET"
wait "$server_pid" || fail "UDS server rejected the gateway event"
server_pid=''

python3 - "$EVIDENCE/server.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    evidence = json.load(handle)
assert evidence["peer_uid"] == 0
assert evidence["socket_mode"] == "0o600"
assert evidence["event"]["device_id"] == "lab-camera"
assert evidence["event"]["new_state"] == "SUSPICIOUS"
PY

for ns in "${OG_NAMES[@]}"; do
    [[ -z $(ip -n "$ns" route show default) ]] || fail "default route appeared in $ns"
    if ip -n "$ns" route get 198.51.100.1 >/dev/null 2>&1; then
        fail "outside route appeared in $ns"
    fi
done

echo "PASS: og-b StateEvent reached parent UDS with peer credentials and no IP/default route; evidence: $EVIDENCE"
