#!/usr/bin/env bash
# KAN-50 / G10: one real gateway StateEvent stream through UDS, MQTT, PostgreSQL and
# Grafana, in three declared scenarios, with every intermediate record kept.
#
#   bash platform/run_g10.sh MODEL_DIR PREPARED_DIR OUT_DIR
#
# MODEL_DIR and PREPARED_DIR are the hash-pinned KAN-19 model and IoT-23 slice that
# lab/run_g8_iot23_docker.sh also takes; both stay outside Git. The Compose stack must
# be up, migrated and provisioned (docs/REPRODUCE.md §5). Works from Linux or from
# Git Bash on Windows with Docker Desktop's Linux engine.
#
# Scenarios, each with its own run id, host process and consumer session:
#   normal     the G8 run, published as it happens
#   duplicate  normal, then one acknowledged envelope published again byte for byte
#   outage     broker stopped before the G8 run; the host spools, the broker returns,
#              a new host process drains the spool
#
# The G8 lab container never sees the network: it reaches the host only through the
# socket in a shared volume. platform/g10_report.py judges the result; this script
# only records it.
set -Eeuo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
MODEL_DIR=${1:?usage: bash platform/run_g10.sh MODEL_DIR PREPARED_DIR OUT_DIR}
PREPARED_DIR=${2:?usage: bash platform/run_g10.sh MODEL_DIR PREPARED_DIR OUT_DIR}
OUT=${3:?usage: bash platform/run_g10.sh MODEL_DIR PREPARED_DIR OUT_DIR}
SCENARIOS=${G10_SCENARIOS:-normal duplicate outage}
PY=${PYTHON:-python3}
export MSYS_NO_PATHCONV=1

native() {  # a path Docker on this host understands
    if command -v cygpath >/dev/null; then cygpath -m "$1"; else realpath -- "$1"; fi
}
sha() { sha256sum "$1" | cut -d ' ' -f 1; }

[[ $(sha "$MODEL_DIR/model.joblib") == d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b ]]
[[ $(sha "$MODEL_DIR/model.meta.json") == 917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad ]]
[[ $(sha "$PREPARED_DIR/prepared.pcap") == fc4aa4b9bbdc89a7845fa0fb8b0fd19ce13f71c82a25346e390ad7863ac917ee ]]
[[ $(sha "$PREPARED_DIR/provenance.json") == f3336d1ade84a869db71c37573d5bc6b30898388e8a763997d530de2f8fbde12 ]]

COMPOSE=(docker compose -f "$(native "$ROOT/platform/compose.yaml")")
REPO=$(native "$ROOT")
SECRETS=$(native "$ROOT/platform/.secrets")
MODEL=$(native "$MODEL_DIR")
PREPARED=$(native "$PREPARED_DIR")
mkdir -p "$OUT"
OUT=$(cd -- "$OUT" && pwd)

docker build -q -t omniguard-g8:local -f "$REPO/lab/Dockerfile.g8" "$REPO" >/dev/null
docker build -q -t omniguard-g10-host:local -f "$REPO/lab/Dockerfile.kan43" "$REPO" >/dev/null
git -C "$REPO" rev-parse HEAD > "$OUT/commit"
git -C "$REPO" status --porcelain > "$OUT/worktree-status"

host() {  # host [docker-run options...] -- MODE ARGS...
    local opts=()
    while [[ $1 != -- ]]; do opts+=("$1"); shift; done
    shift
    docker run "${opts[@]}" --network omniguard_telemetry \
        --mount "type=volume,src=$VOLUME,dst=/g10" \
        --mount "type=bind,src=$REPO,dst=/repo,readonly" \
        --mount "type=bind,src=$SECRETS,dst=/secrets,readonly" \
        -e PYTHONPATH=/repo -w /repo omniguard-g10-host:local \
        python platform/g10_host.py "$@" --password-file /secrets/mqtt_password \
        --run-id "$RUN_ID" --socket /g10/uds/gateway.sock
}

broker_up() {
    "${COMPOSE[@]}" start mosquitto >/dev/null
    "${COMPOSE[@]}" up -d --wait --wait-timeout 120 mosquitto >/dev/null
}

scenario() {
    local name=$1 expected=$2
    RUN_ID="g10-$name-$(date -u +%Y%m%dT%H%M%SZ)"
    VOLUME="og-$RUN_ID"
    local dir="$OUT/$name"
    mkdir -p "$dir"
    echo "$RUN_ID" > "$dir/run_id"
    docker volume create "$VOLUME" >/dev/null

    # The consumer's persistent session exists before anything is published, so an
    # outage queues on the broker instead of being lost to a missing subscription.
    PYTHONPATH="$REPO" PYTHONIOENCODING=utf-8 "$PY" -u "$REPO/platform/consume.py" \
        --password-file "$SECRETS/mqtt_password" \
        --client-id "consumer-$RUN_ID" --messages "$expected" --timeout 300 \
        > "$dir/consumer.log" 2>&1 &
    local consumer=$!
    until grep -q 'ledger restored' "$dir/consumer.log"; do
        kill -0 "$consumer"
        sleep 1
    done
    sleep 2

    local serve
    serve=$(host -d -- serve --out /g10/host-serve.json)
    until docker exec "$serve" test -f /g10/host.ready; do
        docker inspect -f '{{.State.Running}}' "$serve" | grep -q true
        sleep 0.5
    done

    [[ $name != outage ]] || "${COMPOSE[@]}" stop mosquitto >/dev/null

    local g8
    g8=$(docker create --network none --cap-add NET_ADMIN --cap-add SYS_ADMIN --cap-add NET_RAW \
        --security-opt apparmor=unconfined --security-opt systempaths=unconfined \
        --mount "type=bind,src=$MODEL,dst=/opt/g8-model,readonly" \
        --mount "type=bind,src=$PREPARED,dst=/opt/g8-input,readonly" \
        --mount "type=volume,src=$VOLUME,dst=/run/g10-uds" \
        --env G10_EVENT_SOCKET=/run/g10-uds/uds/gateway.sock \
        omniguard-g8:local bash lab/container_g8_iot23_probe.sh)
    local g8_exit=0
    docker start -a "$g8" > "$dir/g8-run.log" 2>&1 || g8_exit=$?
    mkdir -p "$dir/g8"
    docker cp "$g8:/tmp/g8-iot23-evidence/." "$(native "$dir")/g8/" >/dev/null
    docker rm -f "$g8" >/dev/null
    echo "$g8_exit" > "$dir/g8-exit"

    docker exec "$serve" touch /g10/host.stop
    docker wait "$serve" > "$dir/host-serve-exit"
    docker logs "$serve" > "$dir/host-serve.log" 2>&1
    docker rm "$serve" >/dev/null

    if [[ $name == outage ]]; then
        broker_up
        host --rm -- drain --out /g10/host-drain.json > "$dir/host-drain.log" 2>&1
    fi
    if [[ $name == duplicate ]]; then
        host --rm -- republish --out /g10/republish.json > "$dir/republish.log" 2>&1
    fi

    local consumer_exit=0
    wait "$consumer" || consumer_exit=$?
    echo "$consumer_exit" > "$dir/consumer-exit"

    docker run --rm --mount "type=volume,src=$VOLUME,dst=/g10" \
        --mount "type=bind,src=$(native "$dir"),dst=/out" omniguard-g10-host:local \
        sh -c 'cp /g10/*.json /g10/*.jsonl /out/ 2>/dev/null; ls /g10/spool > /out/spool-left.txt'
    docker volume rm "$VOLUME" >/dev/null

    "${COMPOSE[@]}" exec -T postgres psql -U omniguard -d omniguard -At -c \
        "SELECT row_to_json(r) FROM (SELECT event_id, run_id, producer_id, boot_id, sequence,
         device_id, previous_state, new_state, reason, event_timestamp, expires_at, ingested_at
         FROM events WHERE run_id = '$RUN_ID' ORDER BY sequence) r;" > "$dir/db-events.jsonl"

    # The dashboard's own datasource, through Grafana's query API: the row a viewer
    # would see, read with the read-only role Grafana is provisioned with.
    local query
    query=$(printf '{"queries":[{"refId":"A","datasource":{"uid":"omniguard-postgres"},"format":"table","rawSql":"SELECT event_id, sequence, new_state FROM events WHERE run_id = '"'"'%s'"'"' ORDER BY sequence"}],"from":"now-7d","to":"now"}' "$RUN_ID")
    curl -sS -u "admin:$(tr -d '\r\n' < "$ROOT/platform/.secrets/grafana_password")" \
        -H 'Content-Type: application/json' -d "$query" \
        http://127.0.0.1:3000/api/ds/query > "$dir/grafana.json"
}

for name in $SCENARIOS; do
    case $name in
        normal) scenario normal 2 ;;
        duplicate) scenario duplicate 3 ;;
        outage) scenario outage 2 ;;
        *) echo "unknown scenario $name" >&2; exit 2 ;;
    esac
done
broker_up
PYTHONPATH="$REPO" PYTHONIOENCODING=utf-8 "$PY" "$REPO/platform/g10_report.py" "$(native "$OUT")"
