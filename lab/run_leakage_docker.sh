#!/usr/bin/env bash
# Dedicated KAN-33 leakage run. No host network, PID namespace, socket or bind mount.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
docker build -t omniguard-leakage:local -f "$ROOT/lab/Dockerfile.leakage" "$ROOT"
mkdir -p "$ROOT/artifacts"
EVIDENCE=$(mktemp -d "$ROOT/artifacts/leakage.XXXXXXXX")
container=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN \
    --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
    omniguard-leakage:local)
cleanup() {
    docker cp "$container:/tmp/leakage-validation/." "$EVIDENCE/" 2>/dev/null || true
    docker rm -f "$container" >/dev/null
    echo "Evidence: $EVIDENCE"
}
trap cleanup EXIT
docker start -a "$container" | tee "$EVIDENCE/run.log"
[[ $(docker inspect -f '{{.State.ExitCode}}' "$container") == 0 ]]
