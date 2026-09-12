#!/usr/bin/env bash
set -Eeuo pipefail
cleanup() { bash lab/teardown_netns.sh; }
trap cleanup EXIT
python --version
uname -srmo
nft list ruleset > /tmp/replay-parent-before.nft
ip -j route > /tmp/replay-parent-before.routes
python -m lab.replay_probe
[[ -z $(ip netns list) ]]
nft list ruleset > /tmp/replay-parent-after.nft
ip -j route > /tmp/replay-parent-after.routes
cmp /tmp/replay-parent-before.nft /tmp/replay-parent-after.nft
cmp /tmp/replay-parent-before.routes /tmp/replay-parent-after.routes
echo 'PASS: repeated PCAP replay, independent sink, reference timing, host refusal, cleanup'
