#!/usr/bin/env bash
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MODEL_DIR=${1:?usage: bash lab/run_g8_iot23_docker.sh MODEL_DIR PREPARED_DIR}
PREPARED_DIR=${2:?usage: bash lab/run_g8_iot23_docker.sh MODEL_DIR PREPARED_DIR}
MODEL_DIR=$(realpath -- "$MODEL_DIR")
PREPARED_DIR=$(realpath -- "$PREPARED_DIR")
[[ $(sha256sum "$MODEL_DIR/model.joblib" | cut -d ' ' -f 1) == d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b ]]
[[ $(sha256sum "$MODEL_DIR/model.meta.json" | cut -d ' ' -f 1) == 917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad ]]
[[ -f "$PREPARED_DIR/prepared.pcap" && -f "$PREPARED_DIR/provenance.json" ]]
[[ $(sha256sum "$PREPARED_DIR/prepared.pcap" | cut -d ' ' -f 1) == fc4aa4b9bbdc89a7845fa0fb8b0fd19ce13f71c82a25346e390ad7863ac917ee ]]
[[ $(sha256sum "$PREPARED_DIR/provenance.json" | cut -d ' ' -f 1) == f3336d1ade84a869db71c37573d5bc6b30898388e8a763997d530de2f8fbde12 ]]
[[ $(uname -m) == x86_64 ]]
docker build -t omniguard-g8:local -f "$ROOT/lab/Dockerfile.g8" "$ROOT"
mkdir -p "$ROOT/artifacts"
EVIDENCE=$(mktemp -d "$ROOT/artifacts/g8-iot23.XXXXXXXX")
container=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
    --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
    --mount "type=bind,src=$MODEL_DIR,dst=/opt/g8-model,readonly" \
    --mount "type=bind,src=$PREPARED_DIR,dst=/opt/g8-input,readonly" \
    omniguard-g8:local bash lab/container_g8_iot23_probe.sh)
cleanup() {
    docker cp "$container:/tmp/g8-iot23-evidence/." "$EVIDENCE/" || true
    docker rm -f "$container" >/dev/null
    echo "Real-model IoT-23 evidence: $EVIDENCE"
}
trap cleanup EXIT
docker start -a "$container" | tee "$EVIDENCE/run.log"
[[ $(docker inspect -f '{{.State.ExitCode}}' "$container") == 0 ]]
