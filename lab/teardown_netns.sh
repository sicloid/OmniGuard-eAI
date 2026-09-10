#!/usr/bin/env bash
set -Eeuo pipefail
# shellcheck source=lab/common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
og_preflight
if [[ ! -e "$OG_STATE/owned" ]]; then
    echo 'No ownership record; no changes made'
    exit 0
fi
og_verify
# Never kill arbitrary namespace occupants. Stop the lab test/capture first.
for ns in "${OG_NAMES[@]}"; do
    [[ -z $(ip netns pids "$ns") ]] || { echo "$ns has running processes; stop them first" >&2; exit 2; }
done
for ns in "${OG_NAMES[@]}"; do ip netns del "$ns"; done
rm -- "$OG_STATE/owned"
echo 'Deleted only owned lab namespaces'
