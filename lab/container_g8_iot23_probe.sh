#!/usr/bin/env bash
# Frozen RF + hash-pinned, explicitly transformed IoT-23 SYN slice in owned lab.
set -Eeuo pipefail
EVIDENCE=/tmp/g8-iot23-evidence
mkdir -p "$EVIDENCE"
pids=()
core_pid=''
resume_sources() {
    for pid in "${pids[@]}"; do kill -CONT "$pid" 2>/dev/null || true; done
}
cleanup() {
    [[ -z $core_pid ]] || kill "$core_pid" 2>/dev/null || true
    resume_sources
    for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
    for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
    bash lab/teardown_netns.sh || true
}
trap cleanup EXIT
nft list ruleset > "$EVIDENCE/parent-before.nft"
ip -j route > "$EVIDENCE/parent-before.routes"
bash lab/setup_netns.sh
ip netns exec og-c python -m lab.udp_probe sink > "$EVIDENCE/udp-sink.log" 2> "$EVIDENCE/udp-sink.err" &
pids+=("$!")
ip netns exec og-c python -m lab.tcp_probe sink > "$EVIDENCE/tcp-sink.log" 2> "$EVIDENCE/tcp-sink.err" &
pids+=("$!")
ip netns exec og-a python -m lab.local_service_probe sink > "$EVIDENCE/local-sink.log" 2> "$EVIDENCE/local-sink.err" &
pids+=("$!")
sleep 0.4
ip netns exec og-a python -m lab.local_service_probe source > "$EVIDENCE/local-source.log" 2> "$EVIDENCE/local-source.err" &
pids+=("$!")
ip netns exec og-a python -m lab.udp_probe source > "$EVIDENCE/udp-source.log" 2> "$EVIDENCE/udp-source.err" &
udp_source=$!
pids+=("$!")
ip netns exec og-a python -m lab.tcp_probe source > "$EVIDENCE/tcp-source.log" 2> "$EVIDENCE/tcp-source.err" &
tcp_source=$!
pids+=("$!")
sleep 1
[[ -s $EVIDENCE/udp-sink.log && -s $EVIDENCE/tcp-sink.log ]]
kill -STOP "$udp_source" "$tcp_source"
ip netns exec og-b python -m lab.g8_core \
    --artifact-dir /opt/g8-model \
    --model-sha256 d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b \
    --metadata-sha256 917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad \
    --seconds 24 --n 1 --lease-seconds 6 \
    > "$EVIDENCE/core.jsonl" 2> "$EVIDENCE/core.err" &
core_pid=$!
for _ in $(seq 1 40); do
    grep -q '"kind": "ready"' "$EVIDENCE/core.jsonl" && break
    kill -0 "$core_pid"
    sleep 0.1
done
grep -q '"kind": "ready"' "$EVIDENCE/core.jsonl"
ip netns exec og-a python -m lab.replay /opt/g8-input/prepared.pcap \
    --provenance /opt/g8-input/provenance.json \
    --output "$EVIDENCE/replay-runs" --speed 1 --reference-record 1 \
    > "$EVIDENCE/replay.log" 2> "$EVIDENCE/replay.err"
for _ in $(seq 1 120); do
    grep -q '"action": "APPLIED"' "$EVIDENCE/core.jsonl" && break
    kill -0 "$core_pid"
    sleep 0.1
done
grep -q '"action": "APPLIED"' "$EVIDENCE/core.jsonl"
resume_sources
wait "$core_pid"
core_pid=''
for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
for pid in "${pids[@]}"; do wait "$pid" 2>/dev/null || true; done
pids=()
python -m lab.g8_iot23_validate "$EVIDENCE" | tee "$EVIDENCE/validation.json"
bash lab/teardown_netns.sh
nft list ruleset > "$EVIDENCE/parent-after.nft"
ip -j route > "$EVIDENCE/parent-after.routes"
cmp "$EVIDENCE/parent-before.nft" "$EVIDENCE/parent-after.nft"
cmp "$EVIDENCE/parent-before.routes" "$EVIDENCE/parent-after.routes"
