#!/usr/bin/env bash
# Disposable wiring smoke; synthetic RF is explicitly not the G8 gate artifact.
set -Eeuo pipefail
mkdir -p /tmp/g8-synthetic-evidence
EVIDENCE=/tmp/g8-synthetic-evidence
source_pids=()
core_pid=''
stop_probes() {
    for pid in "${source_pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    for pid in "${source_pids[@]}"; do wait "$pid" 2>/dev/null || true; done
    source_pids=()
}
cleanup() {
    [[ -z $core_pid ]] || kill "$core_pid" 2>/dev/null || true
    stop_probes
    bash lab/teardown_netns.sh || true
}
trap cleanup EXIT
nft list ruleset > "$EVIDENCE/parent-before.nft"
ip -j route > "$EVIDENCE/parent-before.routes"
bash lab/setup_netns.sh
python -m lab.g8_synthetic_model /tmp/g8-synthetic-model > "$EVIDENCE/pins.json"
read -r model_sha metadata_sha < <(python -c \
    'import json,sys; d=json.load(open(sys.argv[1])); print(d["model_sha256"], d["metadata_sha256"])' \
    "$EVIDENCE/pins.json")
ip netns exec og-c python -m lab.udp_probe sink > "$EVIDENCE/udp-sink.log" 2> "$EVIDENCE/udp-sink.err" &
source_pids+=("$!")
ip netns exec og-c python -m lab.tcp_probe sink > "$EVIDENCE/tcp-sink.log" 2> "$EVIDENCE/tcp-sink.err" &
source_pids+=("$!")
sleep 0.4
ip netns exec og-a python -m lab.udp_probe source > "$EVIDENCE/udp-source.log" 2> "$EVIDENCE/udp-source.err" &
source_pids+=("$!")
ip netns exec og-a python -m lab.tcp_probe source > "$EVIDENCE/tcp-source.log" 2> "$EVIDENCE/tcp-source.err" &
source_pids+=("$!")
sleep 1
[[ -s $EVIDENCE/udp-sink.log && -s $EVIDENCE/tcp-sink.log ]]
ip netns exec og-b python -m lab.g8_core \
    --artifact-dir /tmp/g8-synthetic-model \
    --model-sha256 "$model_sha" --metadata-sha256 "$metadata_sha" \
    --seconds 18 --n 1 --lease-seconds 4 \
    > "$EVIDENCE/core.jsonl" 2> "$EVIDENCE/core.err" &
core_pid=$!
wait "$core_pid"
core_pid=''
python -m lab.g8_synthetic_validate "$EVIDENCE" | tee "$EVIDENCE/validation.json"
stop_probes
bash lab/teardown_netns.sh
nft list ruleset > "$EVIDENCE/parent-after.nft"
ip -j route > "$EVIDENCE/parent-after.routes"
cmp "$EVIDENCE/parent-before.nft" "$EVIDENCE/parent-after.nft"
cmp "$EVIDENCE/parent-before.routes" "$EVIDENCE/parent-after.routes"
echo 'PASS: synthetic RF wiring, TCP/UDP independent sink stop/restore; NOT G8'
