"""KAN-50 host side: the real gateway's StateEvents from the Unix socket to the broker.

Runs on Linux (CPython on Windows has no AF_UNIX), in a container on the Compose
telemetry network, with the socket in a volume the G8 lab container also mounts. It is
the shipped path and nothing else — `UnixSocketAdapter` → `TelemetryHandoff` →
`TelemetryPublisher` → `PahoTransport` — with a spool directory that outlives the
process, so a broker outage can be recovered by a later `--drain` run.

Every publish attempt is written to `publishes.jsonl` with the event_id, sequence,
topic and outcome, so the report can join what the host sent to what the gateway
decided and what the database committed. Nothing here decides whether the run passed.

Run it as a script with the repository on PYTHONPATH (`platform` is also a
standard-library module name); `platform/run_g10.sh` does all of this:

    python platform/g10_host.py serve --password-file ... --run-id g10-... --out ...
    python platform/g10_host.py drain --password-file ... --run-id g10-... --out ...
    python platform/g10_host.py republish --password-file ... --run-id g10-... --out ...
"""

import argparse
import json
import signal
import threading
import time
from dataclasses import asdict
from pathlib import Path

import paho.mqtt.client as mqtt

from telemetry.envelope import unwrap
from telemetry.handoff import TelemetryHandoff
from telemetry.identity import ProducerIdentity
from telemetry.mqtt import PahoTransport
from telemetry.publisher import Acknowledgement, TelemetryPublisher, TransportError
from telemetry.spool import BoundedSpool
from telemetry.uds import UnixSocketAdapter

SPOOL_BYTES = 1 << 20
SPOOL_AGE_SECONDS = 3600


class RecordingTransport:
    """Pass each publish through unchanged and append what happened to a JSONL log."""

    def __init__(self, transport, log: Path, phase: str):
        self._transport = transport
        self._log = log
        self._phase = phase

    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool):
        envelope = unwrap(json.loads(payload))
        record = {
            "phase": self._phase,
            "event_id": envelope.payload["event_id"],
            "run_id": envelope.payload["run_id"],
            "boot_id": envelope.producer.boot_id,
            "sequence": envelope.sequence,
            "topic": topic,
            "body": payload.decode("utf-8"),
            "at_unix": time.time(),
        }
        try:
            acknowledgement = self._transport.publish(topic, payload, qos=qos, retain=retain)
        except TransportError as error:
            record["outcome"] = f"transport_error: {error}"
            self._write(record)
            raise
        record["outcome"] = str(acknowledgement)
        self._write(record)
        return acknowledgement

    def _write(self, record: dict) -> None:
        with self._log.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, sort_keys=True) + "\n")


def _client(host: str, port: int, password: str) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.username_pw_set("omniguard", password)
    connected = threading.Event()
    client.on_connect = lambda c, u, f, reason, p: None if reason.is_failure else connected.set()
    client.connect_async(host, port, keepalive=30)
    client.loop_start()
    connected.wait(10)  # a broker that is down now is a scenario, not a failure
    return client


def _spool(args) -> BoundedSpool:
    return BoundedSpool(args.spool, max_bytes=SPOOL_BYTES, max_age_seconds=SPOOL_AGE_SECONDS)


def _spool_state(spool: BoundedSpool) -> dict:
    counters = spool.counters()
    return {
        "pending": [entry.sequence for entry in spool.pending()],
        "counters": {k: v for k, v in asdict(counters).items() if k != "scopes"},
        "loss_scopes": [asdict(scope) for scope in counters.scopes],
    }


def serve(args) -> dict:
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = _client(args.host, args.port, password)
    spool = _spool(args)
    producer = ProducerIdentity.start(args.producer_id, time.time())
    transport = RecordingTransport(PahoTransport(client), args.publishes, "serve")
    publisher = TelemetryPublisher(transport, spool, producer, run_id=args.run_id)
    handoff = TelemetryHandoff(publisher, capacity=256)
    handoff.start()
    adapter = UnixSocketAdapter(args.socket, handoff, clock=time.time, timeout=0.5)
    adapter.bind()
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    serving = threading.Thread(target=adapter.serve_forever, daemon=True)
    serving.start()
    args.ready.write_text(producer.boot_id + "\n", encoding="utf-8")
    while not stopping.is_set() and not args.stop.exists():
        time.sleep(0.1)
    adapter.stop()
    serving.join(timeout=5)
    adapter.close()
    handoff_stopped = handoff.stop(timeout=30)
    client.disconnect()
    client.loop_stop()
    return {
        "mode": "serve",
        "run_id": args.run_id,
        "producer": asdict(producer),
        "adapter": {
            k: str(v) if k == "peer_verification" else v
            for k, v in asdict(adapter.counters).items()
        },
        "handoff": asdict(handoff.counters) | {"stopped_cleanly": handoff_stopped},
        "publisher": asdict(publisher.counters),
        "spool": _spool_state(spool),
    }


def drain(args) -> dict:
    password = args.password_file.read_text(encoding="utf-8").strip()
    client = _client(args.host, args.port, password)
    spool = _spool(args)
    before = _spool_state(spool)
    producer = ProducerIdentity.start(args.producer_id, time.time())
    transport = RecordingTransport(PahoTransport(client), args.publishes, "drain")
    publisher = TelemetryPublisher(transport, spool, producer, run_id=args.run_id)
    outcomes = publisher.drain(now=time.time())
    client.disconnect()
    client.loop_stop()
    return {
        "mode": "drain",
        "run_id": args.run_id,
        "before": before,
        "outcomes": [
            {"event_id": o.event_id, "broker_ack": o.broker_ack, "reason": o.reason}
            for o in outcomes
        ],
        "publisher": asdict(publisher.counters),
        "after": _spool_state(spool),
    }


def republish(args) -> dict:
    """Send one already-acknowledged envelope again, byte for byte (QoS 1 duplicate)."""
    password = args.password_file.read_text(encoding="utf-8").strip()
    records = [json.loads(line) for line in args.publishes.read_text(encoding="utf-8").splitlines()]
    acked = [r for r in records if r["outcome"] == str(Acknowledgement.ACKED)]
    chosen = acked[0]
    client = _client(args.host, args.port, password)
    acknowledgement = PahoTransport(client).publish(
        chosen["topic"], chosen["body"].encode("utf-8"), qos=1, retain=False
    )
    client.disconnect()
    client.loop_stop()
    return {
        "mode": "republish",
        "event_id": chosen["event_id"],
        "sequence": chosen["sequence"],
        "outcome": str(acknowledgement),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("serve", "drain", "republish"))
    parser.add_argument("--host", default="mosquitto")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--producer-id", default="g10-host")
    parser.add_argument("--socket", type=Path, default=Path("/run/g10-uds/gateway.sock"))
    parser.add_argument("--spool", type=Path, default=Path("/g10/spool"))
    parser.add_argument("--publishes", type=Path, default=Path("/g10/publishes.jsonl"))
    parser.add_argument("--ready", type=Path, default=Path("/g10/host.ready"))
    parser.add_argument("--stop", type=Path, default=Path("/g10/host.stop"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = {"serve": serve, "drain": drain, "republish": republish}[args.mode](args)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
