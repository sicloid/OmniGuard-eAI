#!/usr/bin/env bash
# Dedicated amd64 lab only: no host network, PID, Docker socket or bind mounts.
set -Eeuo pipefail
[[ $(uname -m) == x86_64 ]] || { echo 'Capture oracle image is amd64-only' >&2; exit 2; }
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
docker build -t omniguard-capture:local -f "$ROOT/lab/Dockerfile.capture" "$ROOT"
mkdir -p "$ROOT/artifacts"
EVIDENCE=$(mktemp -d "$ROOT/artifacts/live-capture.XXXXXXXX")
container=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN \
    --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
    omniguard-capture:local)
cleanup() {
    docker cp "$container:/tmp/." "$EVIDENCE/" || true
    docker rm -f "$container" >/dev/null
    echo "Evidence: $EVIDENCE"
}
trap cleanup EXIT
docker start -a "$container" | tee "$EVIDENCE/run.log"
[[ $(docker inspect -f '{{.State.ExitCode}}' "$container") == 0 ]]
