#!/usr/bin/env bash
# OmniGuard final demonstration entry point.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
MODE=${1:-all}

platform_demo() {
    cd "$ROOT"
    python3 platform/init_secrets.py
    docker compose -f platform/compose.yaml up -d --wait --wait-timeout 180
    python3 platform/migrate.py
    python3 platform/provision_roles.py
    python3 platform/smoke.py
    echo "Grafana: http://127.0.0.1:3000/d/omniguard-state"
}

core_demo() {
    cd "$ROOT"
    bash lab/run_g8_synthetic_docker.sh
}

evidence_demo() {
    cd "$ROOT"
    python3 docs/evidence/KAN43_2026-09-23/verify.py >/dev/null
    python3 platform/g10_report.py docs/evidence/G10_2026-09-24 >/dev/null
    (cd docs/evidence/G10_2026-09-24 && sha256sum -c SHA256SUMS >/dev/null)
    (cd docs/evidence/KAN45_2026-09-28_runtime && \
        sha256sum -c SHA256SUMS >/dev/null)
    sha256sum -c docs/evidence/KAN66_PI_2026-09-28/SHA256SUMS >/dev/null
    python3 -m measure.result_freeze verify \
        --root . docs/evidence/G13_2026-09-28-final/result-freeze.json >/dev/null
    (cd docs/evidence/G13_2026-09-28-final && \
        sha256sum -c result-freeze.json.sha256 >/dev/null)
    echo "PASS: sealed G10, compute-budget, Pi and final G13 evidence verified"
}

real_demo() {
    local model=${2:?usage: ./demo.sh real MODEL_DIR PREPARED_DIR}
    local prepared=${3:?usage: ./demo.sh real MODEL_DIR PREPARED_DIR}
    cd "$ROOT"
    bash lab/run_g8_iot23_docker.sh "$model" "$prepared"
}

case "$MODE" in
    all)
        platform_demo
        core_demo
        evidence_demo
        ;;
    platform) platform_demo ;;
    core) core_demo ;;
    evidence) evidence_demo ;;
    real) real_demo "$@" ;;
    *)
        echo "usage: ./demo.sh [all|platform|core|evidence|real MODEL_DIR PREPARED_DIR]" >&2
        exit 2
        ;;
esac
