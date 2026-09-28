"""Compare the same pinned detector locally and through the optional HTTP path."""

import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
import urllib.request
from pathlib import Path

from data.samplepack.build import read_windows
from gateway.real_detector import load_pinned_rf_detector


def percentile(values: list[int], fraction: float) -> int:
    if not values:
        raise ValueError("at least one latency is required")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def payload(vector) -> dict:
    return {
        "device_id": vector.device_id,
        "window_start": vector.window_start,
        "window_end": vector.window_end,
        "feature_schema_version": vector.feature_schema_version,
        "feature_order": list(vector.feature_order),
        "values": list(vector.values),
    }


def expected(result) -> dict:
    return {
        "device_id": result.device_id,
        "window_ts": result.window_ts,
        "model_id": result.model_id,
        "model_version": result.model_version,
        "score": result.score,
        "classification": result.classification.value,
        "threshold": result.threshold,
    }


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def run(args) -> dict:
    detector = load_pinned_rf_detector(
        args.model_dir,
        expected_model_sha256=args.model_sha256,
        expected_metadata_sha256=args.metadata_sha256,
    )
    windows = read_windows(args.pack)
    if not windows:
        raise ValueError("pack contains no labelled windows")
    local_ns, remote_ns, errors = [], [], []
    for index in range(args.requests):
        vector = windows[index % len(windows)].vector
        started = time.perf_counter_ns()
        local = detector.predict(vector)
        local_ns.append(time.perf_counter_ns() - started)
        body = json.dumps(payload(vector)).encode()
        request = urllib.request.Request(
            args.url,
            body,
            {"Content-Type": "application/json"},
            method="POST",
        )
        started = time.perf_counter_ns()
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                remote = json.load(response)
            remote_ns.append(time.perf_counter_ns() - started)
            if remote != expected(local):
                errors.append({"index": index, "reason": "local/remote result mismatch"})
        except Exception as exc:
            errors.append({"index": index, "reason": f"{type(exc).__name__}: {exc}"})
    report = {
        "schema": "omniguard.remote-comparison/1",
        "mode": "comparison-only; local inference remains production default",
        "requests": args.requests,
        "errors": errors,
        "model_sha256": args.model_sha256,
        "metadata_sha256": args.metadata_sha256,
        "pack_sha256": hashlib.sha256(args.pack.read_bytes()).hexdigest(),
        "environment": {
            "client_host": platform.node(),
            "server_host": args.server_host,
            "client_server_cpu_scope": args.client_server_cpu_scope,
            "url": args.url,
            "python": platform.python_version(),
            "fastapi": _package_version("fastapi"),
            "uvicorn": _package_version("uvicorn"),
        },
        "local_latency_ns": {
            "p50": percentile(local_ns, 0.50),
            "p95": percentile(local_ns, 0.95),
        },
        "remote_latency_ns": {
            "p50": percentile(remote_ns, 0.50) if remote_ns else None,
            "p95": percentile(remote_ns, 0.95) if remote_ns else None,
        },
    }
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.out.with_suffix(args.out.suffix + ".sha256").write_text(f"{digest}  {args.out.name}\n")
    if errors:
        raise RuntimeError(f"{len(errors)} remote comparison requests failed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--metadata-sha256", required=True)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--url", default="http://127.0.0.1:8047/v1/predict")
    parser.add_argument("--server-host", required=True)
    parser.add_argument("--client-server-cpu-scope", required=True)
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.requests <= 0:
        parser.error("--requests must be positive")
    report = run(args)
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
