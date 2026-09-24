"""KAN-50 / G10 report: join every record of a `run_g10.sh` output and judge it.

For each scenario directory it reads what the gateway decided and what the kernel did
(`g8/core.jsonl`), what the host received and published (`host-serve.json`,
`host-drain.json`, `publishes.jsonl`), what the consumer committed (`consumer.log`,
`db-events.jsonl`) and what Grafana's datasource returned (`grafana.json`). It then:

- pairs every StateEvent with its kernel receipt (decision ↔ application);
- follows each one to exactly one committed row with identical fields, and that row
  to the Grafana result (decision ↔ telemetry ↔ dashboard);
- counts it at every boundary so a loss is located, not just detected;
- checks the scenario's own claim: a byte-identical duplicate stored nothing new, an
  outage spooled every event and the drain recovered every one under the same id.

Pairing is by order and by field equality: the schema has no shared durable
decision/application key, and the report says so rather than inventing one.

    python platform/g10_report.py OUT_DIR

Writes `OUT_DIR/g10-report.json` and exits nonzero if any check fails.
"""

import json
import sys
from pathlib import Path

FIELDS = (
    ("device_id", "device_id"),
    ("previous_state", "previous_state"),
    ("new_state", "new_state"),
    ("reason", "reason"),
    ("timestamp", "event_timestamp"),
    ("expires_at", "expires_at"),
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _lines(path: Path) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _consumer_counters(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    start = text.find("{")
    return json.loads(text[start : text.index("}", start) + 1]) if start >= 0 else None


def _grafana_event_ids(document) -> list:
    try:
        frame = document["results"]["A"]["frames"][0]
        names = [field["name"] for field in frame["schema"]["fields"]]
        return frame["data"]["values"][names.index("event_id")]
    except KeyError, IndexError, TypeError, ValueError:
        return []


def scenario(directory: Path) -> dict:
    name = directory.name
    run_id = (directory / "run_id").read_text(encoding="utf-8").strip()
    core = _lines(directory / "g8" / "core.jsonl")
    events = [r for r in core if r["kind"] == "state_event"]
    receipts = [r for r in core if r["kind"] == "kernel_receipt"]
    handoffs = [r for r in core if r["kind"] == "event_handoff"]
    bridge = next((r for r in core if r["kind"] == "event_bridge_summary"), {})
    validation = _json(directory / "g8" / "validation.json") or {}
    serve = _json(directory / "host-serve.json") or {}
    drain = _json(directory / "host-drain.json")
    republished = _json(directory / "republish.json")
    publishes = _lines(directory / "publishes.jsonl")
    rows = _lines(directory / "db-events.jsonl")
    consumer = _consumer_counters(directory / "consumer.log") or {}
    grafana = _grafana_event_ids(_json(directory / "grafana.json"))
    produced = len(events)
    acked = [p for p in publishes if p["outcome"] == "ACKED"]
    acked_ids = [p["event_id"] for p in acked]

    checks = {
        "g8_lab_exited_cleanly": (directory / "g8-exit").read_text().strip() == "0",
        "g8_produced_events": produced > 0,
        "every_decision_has_a_kernel_receipt": len(receipts) == produced,
        "gateway_bridge_accepted_every_event": [h["outcome"] for h in handoffs]
        == ["ACCEPTED"] * produced,
        "gateway_bridge_delivered_every_event": bridge.get("delivered") == produced
        and bridge.get("failures") == 0,
        "host_peer_verified": serve.get("adapter", {}).get("peer_verification") == "VERIFIED",
        "host_accepted_every_frame": serve.get("adapter", {}).get("accepted") == produced,
        "handoff_processed_every_event": serve.get("handoff", {}).get("processed") == produced
        and serve.get("handoff", {}).get("overflowed") == 0,
        "every_event_acknowledged_once": sorted(p["sequence"] for p in acked)
        == list(range(1, produced + 1))
        and len(set(acked_ids)) == produced,
        "db_rows_equal_produced": len(rows) == produced,
        "db_rows_are_the_acknowledged_ids": sorted(r["event_id"] for r in rows)
        == sorted(acked_ids),
        "db_rows_belong_to_this_run": all(r["run_id"] == run_id for r in rows),
        "consumer_clean": consumer.get("database_failures") == 0
        and consumer.get("left_unacknowledged") == 0
        and consumer.get("rejected") == 0,
        "grafana_returns_the_committed_rows": grafana == [r["event_id"] for r in rows],
        "g8_sinks_blocked_during_quarantine": all(
            sink.get("blocked") == 0 for sink in validation.get("sinks", {}).values()
        )
        and bool(validation.get("sinks")),
        "g8_kernel_drops_zero": validation.get("kernel_drops") == 0,
    }

    correlation = []
    for index, (event, receipt) in enumerate(zip(events, receipts, strict=False)):
        row = rows[index] if index < len(rows) else None
        fields_match = row is not None and all(event[a] == row[b] for a, b in FIELDS)
        applied = receipt["action"] == "APPLIED" and receipt["readback_active"] is True
        released = (
            receipt["action"] in ("RELEASED", "ALREADY_RELEASED")
            and receipt["readback_active"] is False
        )
        coherent = applied if event["new_state"] == "QUARANTINED" else released
        checks[f"event_{index + 1}_row_fields_match"] = fields_match
        checks[f"event_{index + 1}_kernel_matches_decision"] = coherent
        correlation.append(
            {
                "sequence": row["sequence"] if row else None,
                "event_id": row["event_id"] if row else None,
                "transition": f"{event['previous_state']}→{event['new_state']}",
                "reason": event["reason"],
                "kernel_action": receipt["action"],
                "kernel_readback_active": receipt["readback_active"],
                "decision_to_receipt_ms": (receipt["mono_ns"] - event["mono_ns"]) / 1e6,
                "ingest_minus_event_wall_seconds": (
                    _wall_gap(row) if row and row.get("ingested_at") else None
                ),
            }
        )

    served = serve.get("publisher", {})
    if name == "outage":
        checks["outage_spooled_every_event"] = (
            served.get("spooled") == produced and served.get("published") == 0
        )
        checks["drain_recovered_every_event"] = (
            drain is not None
            and len(drain["before"]["pending"]) == produced
            and drain["after"]["pending"] == []
            and drain["publisher"]["drained"] == produced
            and all(o["broker_ack"] for o in drain["outcomes"])
        )
        checks["spool_lost_nothing"] = drain is not None and (
            drain["after"]["counters"]["dropped_events"] == 0
        )
    else:
        checks["published_without_spooling"] = (
            served.get("published") == produced and served.get("spooled") == 0
        )
    if name == "duplicate":
        checks["duplicate_was_acknowledged_by_broker"] = (
            republished is not None and republished["outcome"] == "ACKED"
        )
        checks["duplicate_stored_nothing_new"] = (
            consumer.get("redelivered") == 1 and consumer.get("stored") == produced
        )
    else:
        checks["consumer_stored_every_event"] = consumer.get("stored") == produced

    return {
        "run_id": run_id,
        "passed": all(checks.values()),
        "checks": checks,
        "completeness": {
            "decided_by_gateway": produced,
            "accepted_by_gateway_bridge": bridge.get("accepted"),
            "delivered_over_uds": bridge.get("delivered"),
            "accepted_by_host_adapter": serve.get("adapter", {}).get("accepted"),
            "processed_by_handoff": serve.get("handoff", {}).get("processed"),
            "spooled_during_outage": served.get("spooled"),
            "broker_acknowledged": len(set(acked_ids)),
            "committed_rows": len(rows),
            "grafana_rows": len(grafana),
            "consumer": consumer,
            "lost": produced - len(rows),
        },
        "correlation": correlation,
        "correlation_basis": (
            "order and field equality within one run; there is no shared durable "
            "decision/application key in the 0.1.0 schema"
        ),
    }


def _wall_gap(row: dict) -> float | None:
    """Consumer commit minus producer timestamp: two unaligned wall clocks, not latency."""
    from datetime import datetime

    try:
        ingested = datetime.fromisoformat(row["ingested_at"]).timestamp()
    except TypeError, ValueError:
        return None
    return round(ingested - row["event_timestamp"], 3)


def main() -> int:
    out = Path(sys.argv[1])
    scenarios = sorted(p for p in out.iterdir() if (p / "run_id").exists())
    report = {
        "commit": (out / "commit").read_text().strip() if (out / "commit").exists() else None,
        "worktree_dirty": bool((out / "worktree-status").read_text().strip())
        if (out / "worktree-status").exists()
        else None,
        "scenarios": {p.name: scenario(p) for p in scenarios},
    }
    report["passed"] = bool(scenarios) and all(s["passed"] for s in report["scenarios"].values())
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    (out / "g10-report.json").write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
