#!/usr/bin/env bash
# KAN-42 sealed run, inside the G8 lab container (see measure/run_kan42.sh).
#
# The lab is lab/container_g8_iot23_probe.sh itself: this script copies it and changes
# exactly one thing — the core runs under measure.kan42_core, which times the real
# objects' stages. The substitution is checked to have happened once.
#
# Order: the manifest owner freezes first; a counting host-side UDS adapter listens
# so the exporter stage has a real socket behind it; the lab runs; the owner closes.
set -Eeuo pipefail
EVIDENCE=/tmp/g8-iot23-evidence
OUT=/tmp/kan42
SOCKET=/run/kan42/gateway.sock
mkdir -p "$EVIDENCE" "$OUT"

python -m measure.kan42_manifest --model-dir /opt/g8-model --evidence "$EVIDENCE" \
    --out "$OUT" > "$EVIDENCE/manifest-owner.log" 2>&1 &
owner=$!
for _ in $(seq 1 100); do
    [[ -f $EVIDENCE/manifest.frozen ]] && break
    kill -0 "$owner"
    sleep 0.1
done
[[ -f $EVIDENCE/manifest.frozen ]]

python - "$SOCKET" "$EVIDENCE" > "$EVIDENCE/adapter.log" 2>&1 <<'EOF' &
import json, sys, threading, time
from dataclasses import asdict
from pathlib import Path
from telemetry.outcomes import HandoffOutcome
from telemetry.uds import UnixSocketAdapter

class CountingSink:
    accepted = 0
    def submit(self, event, *, now):
        self.accepted += 1
        return HandoffOutcome.ACCEPTED

socket_path, evidence = Path(sys.argv[1]), Path(sys.argv[2])
sink = CountingSink()
adapter = UnixSocketAdapter(socket_path, sink, clock=time.time, timeout=0.5)
adapter.bind()
threading.Thread(target=adapter.serve_forever, daemon=True).start()
while not (evidence / "lab.done").exists():
    time.sleep(0.1)
adapter.stop()
adapter.close()
counters = {k: str(v) if k == "peer_verification" else v for k, v in asdict(adapter.counters).items()}
(evidence / "adapter.json").write_text(json.dumps(counters | {"sink_accepted": sink.accepted}, sort_keys=True) + "\n")
EOF
adapter=$!
for _ in $(seq 1 50); do [[ -S $SOCKET ]] && break; sleep 0.1; done
[[ -S $SOCKET ]]

probe=$(mktemp)
sed 's|ip netns exec og-b python -m lab.g8_core|ip netns exec og-b python -m measure.kan42_core --stages-out "$EVIDENCE/stages.json"|' \
    lab/container_g8_iot23_probe.sh > "$probe"
[[ $(grep -c 'measure.kan42_core' "$probe") == 1 ]]
[[ $(grep -c 'python -m lab.g8_core' "$probe") == 0 ]]

status=0
G10_EVENT_SOCKET=$SOCKET bash "$probe" || status=$?
echo "$status" > "$EVIDENCE/lab.done"
wait "$adapter" || true
wait "$owner"
exit "$status"
