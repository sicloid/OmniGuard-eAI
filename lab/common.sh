#!/usr/bin/env bash
# Fixed, isolated lab resources; never source this from untrusted locations.
set -Eeuo pipefail
readonly OG_STATE=/run/omniguard-lab
readonly OG_NAMES=(og-a og-b og-c)

og_preflight() {
    [[ $(uname -s) == Linux && $EUID -eq 0 ]] || { echo 'Linux root required' >&2; exit 2; }
    for tool in ip nft flock stat; do
        command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 2; }
    done
    [[ ! -L "$OG_STATE" ]] || { echo 'Unsafe state symlink' >&2; exit 2; }
    if [[ ! -d "$OG_STATE" ]]; then mkdir -m 700 "$OG_STATE"; fi
    [[ $(stat -c '%u:%a' "$OG_STATE") == 0:700 ]] || { echo 'Unsafe state owner/mode' >&2; exit 2; }
    [[ ! -L "$OG_STATE/lock" ]] || exit 2
    exec 9>"$OG_STATE/lock"
    flock -n 9 || { echo 'Another lab command is running' >&2; exit 2; }
}

og_verify() {
    [[ -f "$OG_STATE/owned" && ! -L "$OG_STATE/owned" ]] || {
        echo 'No owned lab; run setup first' >&2; return 1;
    }
    local ns expected actual
    for ns in "${OG_NAMES[@]}"; do
        expected=$(awk -v ns="$ns" '$1 == ns {print $2}' "$OG_STATE/owned")
        actual=$(stat -Lc '%d:%i' "/run/netns/$ns")
        [[ -n "$expected" && "$expected" == "$actual" ]] || {
            echo "Namespace identity changed: $ns; refusing mutation" >&2; return 1;
        }
    done
}
