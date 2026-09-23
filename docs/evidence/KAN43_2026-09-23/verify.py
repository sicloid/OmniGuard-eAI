"""Recompute the KAN-43 figures from the committed raw files; nothing is taken on trust.

Run from the repository root:

    python docs/evidence/KAN43_2026-09-23/verify.py

For each run it checks the SHA-256 index, reads the frozen manifest, compares the
sealed code hashes with this checkout, re-derives every per-event and per-second
figure, reconciles each boundary against the next, and joins the consumer's committed
rows to the publisher's count. It prints one JSON report and exits nonzero if any
check fails.
"""

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNS = ("run1-listen1", "run2-listen64")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_index() -> list[str]:
    failures = []
    for line in (HERE / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split(maxsplit=1)
        if sha256(HERE / name) != digest:
            failures.append(f"hash mismatch: {name}")
    return failures


def verify_run(name: str) -> dict:
    directory = HERE / name
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (directory / "db-events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    m = manifest["measurements"]
    events, ledger, wire, recon = m["events"], m["ledger"], m["wire"], m["reconciliation"]
    acked = ledger["events"]["broker_acknowledged"]
    window = manifest["closed_at_unix"] - manifest["started_at_unix"]

    checks = {
        "manifest_format_is_2": manifest["manifest_format"] == "omniguard-experiment-manifest/2",
        "status_completed": manifest["status"] == "completed",
        "every_boundary_observed": ledger["not_observed"] == [],
        "publish_to_broker_matches_derived": recon["publish_to_broker_residue"] == 0,
        "pubacks_match_acknowledged": recon["publish_from_broker_residue"] == 0,
        "close_phase_is_one_disconnect": recon["close_to_broker_counted"] == 2,
        "peer_verified": events["adapter"]["peer_verification"] == "VERIFIED",
        "adapter_frames_equal_bridge_deliveries": events["adapter"]["frames"]
        == events["bridge"]["delivered"],
        "uds_loss_is_counted_not_silent": events["bridge"]["delivered"]
        + events["bridge"]["failures"]
        == events["produced_by_policy"],
        "handoff_processed_everything_accepted": events["handoff"]["processed"]
        == events["adapter"]["accepted"],
        "publisher_acked_everything_processed": events["publisher"]["published"]
        == events["handoff"]["processed"]
        == acked,
        "no_spool_or_drop": events["publisher"]["spooled"] == 0
        and events["spool"]["dropped_events"] == 0,
        "db_rows_equal_acknowledged": len(rows) == acked,
        "db_event_ids_unique": len({row["event_id"] for row in rows}) == len(rows),
        "db_sequences_contiguous": [row["sequence"] for row in rows]
        == list(range(1, len(rows) + 1)),
        "db_rows_belong_to_this_run": all(row["run_id"] == manifest["run_id"] for row in rows),
    }
    code = {
        path: sha256(ROOT / path) == digest
        for path, digest in manifest["config"]["code_sha256"].items()
    }
    per_event = {
        boundary: volume["bytes_total"] / acked for boundary, volume in ledger["boundaries"].items()
    }
    per_event["wire_to_broker_publish_phase"] = wire["to_broker"]["segments"]["publish"] / acked
    per_event["wire_from_broker_publish_phase"] = wire["from_broker"]["segments"]["publish"] / acked
    per_second = {
        boundary: volume["bytes_total"] / window
        for boundary, volume in ledger["boundaries"].items()
    }
    per_second["wire_both_directions_all_phases"] = (
        wire["to_broker"]["total"] + wire["from_broker"]["total"]
    ) / window
    return {
        "run_id": manifest["run_id"],
        "checks": checks,
        "code_matches_this_checkout": code,
        "events": {
            "produced_by_policy": events["produced_by_policy"],
            "delivered_over_uds": events["bridge"]["delivered"],
            "lost_at_uds_counted_by_bridge": events["bridge"]["failures"],
            "broker_acknowledged": acked,
            "committed_rows": len(rows),
            "end_to_end_completeness": len(rows) / events["produced_by_policy"],
        },
        "manifest_window_seconds": window,
        "bytes_per_acknowledged_event": {k: round(v, 2) for k, v in per_event.items()},
        "bytes_per_second_over_manifest_window": {k: round(v, 1) for k, v in per_second.items()},
        "handshake": {
            "connect_to_broker": wire["to_broker"]["segments"]["connect"],
            "connack_from_broker": wire["from_broker"]["segments"]["connect"],
        },
        "uds_residue_bytes": recon["uds_residue"],
    }


def main() -> int:
    failures = check_index()
    report = {"index": "ok" if not failures else failures, "runs": {}}
    for name in RUNS:
        run = verify_run(name)
        report["runs"][name] = run
        failures += [f"{name}: {check}" for check, ok in run["checks"].items() if not ok]
    # The fix between the runs is the point: run 1 used listen(1), run 2 the current code.
    run2_code = report["runs"]["run2-listen64"]["code_matches_this_checkout"]
    failures += [f"run2-listen64: {path} differs" for path, ok in run2_code.items() if not ok]
    report["failures"] = failures
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
