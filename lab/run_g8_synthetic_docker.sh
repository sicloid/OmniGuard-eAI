#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
[[ $(uname -m) == x86_64 ]] || { echo 'This lab image is amd64-only' >&2; exit 2; }
docker build -t omniguard-g8:local -f "$ROOT/lab/Dockerfile.g8" "$ROOT"
mkdir -p "$ROOT/artifacts"
EVIDENCE=$(mktemp -d "$ROOT/artifacts/g8-synthetic.XXXXXXXX")
container=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
    --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
    omniguard-g8:local bash lab/container_g8_synthetic.sh)
cleanup() {
    docker cp "$container:/tmp/g8-synthetic-evidence/." "$EVIDENCE/" || true
    docker rm -f "$container" >/dev/null
    echo "Synthetic-only evidence: $EVIDENCE"
}
trap cleanup EXIT
docker start -a "$container" | tee "$EVIDENCE/run.log"
[[ $(docker inspect -f '{{.State.ExitCode}}' "$container") == 0 ]]
