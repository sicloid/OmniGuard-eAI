#!/usr/bin/env bash
set -Eeuo pipefail
cleanup() { bash lab/teardown_netns.sh; }
trap cleanup EXIT
uname -srmo
python3 --version
nft --version
conntrack --version
nft list ruleset > /tmp/parent-rules-before.txt
ip -j route > /tmp/parent-routes-before.json
bash lab/setup_netns.sh
bash lab/setup_netns.sh
python3 lab/enforcer_smoke.py
python3 lab/stub_state_enforcement_e2e.py
bash lab/smoke_netns.sh
bash lab/teardown_netns.sh
bash lab/teardown_netns.sh
[[ -z $(ip netns list) ]]
nft list ruleset > /tmp/parent-rules-after.txt
ip -j route > /tmp/parent-routes-after.json
cmp /tmp/parent-rules-before.txt /tmp/parent-rules-after.txt
cmp /tmp/parent-routes-before.json /tmp/parent-routes-after.json
echo 'PASS: setup/teardown idempotence and namespace cleanup'
