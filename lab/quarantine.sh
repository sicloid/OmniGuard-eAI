#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lab/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
[[ $# -eq 1 && ( $1 == apply || $1 == release ) ]] || {
    echo 'Usage: quarantine.sh apply|release (fixed test device 10.203.1.2)' >&2; exit 2;
}
og_preflight
og_verify
# This G2 smoke helper is intentionally fixed to the isolated fixture device.
# Every applied element is bounded even in smoke tests; runtime policy lives in
# gateway/enforcer.py and refuses silent renewal of an existing lease.
if [[ $1 == apply ]]; then
    if ! ip netns exec og-b nft get element inet omniguard quarantined_v4 '{ 10.203.1.2 }' >/dev/null 2>&1; then
        ip netns exec og-b nft add element inet omniguard quarantined_v4 '{ 10.203.1.2 timeout 30s }'
    fi
else
    if ip netns exec og-b nft get element inet omniguard quarantined_v4 '{ 10.203.1.2 }' >/dev/null 2>&1; then
        ip netns exec og-b nft delete element inet omniguard quarantined_v4 '{ 10.203.1.2 }'
    fi
fi
