#!/usr/bin/env bash
# Dedicated disposable lab: no host network/PID namespace, sockets or bind mounts.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
docker build -t omniguard-lab:local -f "$ROOT/lab/Dockerfile" "$ROOT"
mkdir -p "$ROOT/artifacts"
EVIDENCE=$(mktemp -d "$ROOT/artifacts/linux-lab.XXXXXXXX")
container=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN \
    --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
    omniguard-lab:local)
cleanup() {
    docker cp "$container:/tmp/." "$EVIDENCE/" || true
    docker rm -f "$container" >/dev/null
    echo "Evidence: $EVIDENCE"
}
trap cleanup EXIT
docker start -a "$container" | tee "$EVIDENCE/run.log"
[[ $(docker inspect -f '{{.State.ExitCode}}' "$container") == 0 ]]
