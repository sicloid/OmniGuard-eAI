#!/usr/bin/env bash
# KAN-42 sealed measurement run on the real G8 pipeline.
#
#   bash measure/run_kan42.sh MODEL_DIR PREPARED_DIR OUT_DIR
#
# MODEL_DIR and PREPARED_DIR are the hash-pinned KAN-19 model and IoT-23 slice that
# lab/run_g8_iot23_docker.sh takes; both stay outside Git. The lab image is built from
# this checkout, and measure/ is mounted read-only beside it. OUT_DIR receives the
# closed manifest and every file the lab wrote. Works from Linux or from Git Bash on
# Windows with Docker Desktop's Linux engine. This is not a Pi measurement.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MODEL_DIR=${1:?usage: bash measure/run_kan42.sh MODEL_DIR PREPARED_DIR OUT_DIR}
PREPARED_DIR=${2:?usage: bash measure/run_kan42.sh MODEL_DIR PREPARED_DIR OUT_DIR}
OUT=${3:?usage: bash measure/run_kan42.sh MODEL_DIR PREPARED_DIR OUT_DIR}
export MSYS_NO_PATHCONV=1

native() {
    if command -v cygpath >/dev/null; then cygpath -m "$1"; else realpath -- "$1"; fi
}
sha() { sha256sum "$1" | cut -d ' ' -f 1; }

[[ $(sha "$MODEL_DIR/model.joblib") == d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b ]]
[[ $(sha "$MODEL_DIR/model.meta.json") == 917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad ]]
[[ $(sha "$PREPARED_DIR/prepared.pcap") == fc4aa4b9bbdc89a7845fa0fb8b0fd19ce13f71c82a25346e390ad7863ac917ee ]]
[[ $(sha "$PREPARED_DIR/provenance.json") == f3336d1ade84a869db71c37573d5bc6b30898388e8a763997d530de2f8fbde12 ]]

REPO=$(native "$ROOT")
mkdir -p "$OUT"
OUT=$(cd -- "$OUT" && pwd)
git -C "$REPO" rev-parse HEAD > "$OUT/commit"
git -C "$REPO" status --porcelain > "$OUT/worktree-status"
docker build -q -t omniguard-g8:local -f "$REPO/lab/Dockerfile.g8" "$REPO" > "$OUT/image"

container=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
    --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
    --mount "type=bind,src=$(native "$MODEL_DIR"),dst=/opt/g8-model,readonly" \
    --mount "type=bind,src=$(native "$PREPARED_DIR"),dst=/opt/g8-input,readonly" \
    --mount "type=bind,src=$REPO/measure,dst=/opt/omniguard/measure,readonly" \
    omniguard-g8:local bash measure/container_kan42.sh)
status=0
docker start -a "$container" > "$OUT/run.log" 2>&1 || status=$?
mkdir -p "$OUT/lab"
docker cp "$container:/tmp/g8-iot23-evidence/." "$(native "$OUT")/lab/" >/dev/null
docker cp "$container:/tmp/kan42/." "$(native "$OUT")/" >/dev/null
docker rm -f "$container" >/dev/null
echo "$status" > "$OUT/exit"
exit "$status"
