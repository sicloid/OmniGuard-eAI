#!/usr/bin/env bash
set -Eeuo pipefail
cleanup() { bash lab/teardown_netns.sh; }
trap cleanup EXIT
python --version
uname -srmo
nft list ruleset > /tmp/capture-parent-before.nft
ip -j route > /tmp/capture-parent-before.routes
python -m lab.live_probe run
[[ -z $(ip netns list) ]]
nft list ruleset > /tmp/capture-parent-after.nft
ip -j route > /tmp/capture-parent-after.routes
cmp /tmp/capture-parent-before.nft /tmp/capture-parent-after.nft
cmp /tmp/capture-parent-before.routes /tmp/capture-parent-after.routes
echo 'PASS: live metadata/counts, pre-drop capture, detected overflow, cleanup'
