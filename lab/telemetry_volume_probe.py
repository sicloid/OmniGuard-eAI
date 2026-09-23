"""KAN-43 instrument check: publish real events and count what they cost.

This is **not** the card's measurement run. It exercises the instruments against a
real broker so the figures they produce can be compared before a sealed run is made:
the application bytes the host offered, the derived PUBLISH size, and the bytes the
connection actually carried. A sealed run additionally needs a frozen
`ExperimentManifest`, which requires the `/2` contract.

The publisher connects through `lab/mqtt_wire_counter.py`; the subscriber connects to
the broker directly, so its traffic never lands in the publisher's counts. The connect
phase and the publish phase are marked separately, because a handshake is paid once
and a PUBLISH is paid per event.

    python -m lab.telemetry_volume_probe --password-file platform/.secrets/mqtt_password \\
        --port 1883 --events 20 --out ~/omniguard-data/runs/kan43/probe.json
"""

import argparse
import json
import queue
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

from core.schema import DeviceState, StateEvent
from lab.mqtt_wire_counter import MqttWireCounter
from telemetry.accounting import CountingAdapter, CountingTransport, VolumeLedger
from telemetry.canonical import canonical_bytes
from telemetry.framing import encode_frame
from telemetry.handoff import TelemetryHandoff
from telemetry.identity import ProducerIdentity
from telemetry.mqtt import PahoTransport
from telemetry.publisher import TelemetryPublisher, topic_for
from telemetry.spool import BoundedSpool


def _client(host: str, port: int, password: str, *, topic: str | None = None) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.username_pw_set("omniguard", password)
    client.connect_timeout = 5
    connected = threading.Event()

    def on_connect(c, userdata, flags, reason_code, properties):
        if not reason_code.is_failure:
            if topic is not None:
                c.subscribe(topic, qos=1)
            connected.set()

    client.on_connect = on_connect
    client.connect(host, port, keepalive=20)
    client.loop_start()
    if not connected.wait(5):
        raise RuntimeError("broker connection was not acknowledged")
    return client


def _write_frames(path: Path, device: str, events: int) -> int:
    """Play the gateway's part: connect to the socket and write framed StateEvents.

    Returns the bytes handed to the socket, which is the producer side of the same
    figure the adapter counts on the reading side. The two are compared in the report
    rather than one being assumed from the other.
    """
    written = 0
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(path))
        for index in range(events):
            body = canonical_bytes(
                {
                    "device_id": device,
                    "previous_state": "NORMAL",
                    "new_state": "SUSPICIOUS",
                    "reason": f"volume probe {index}",
                    "timestamp": time.time(),
                    "expires_at": None,
                }
            )
            frame = encode_frame(body)
            client.sendall(frame)
            written += len(frame)
    return written


def run_uds(sink, device: str, events: int, ledger: VolumeLedger) -> dict:
    """Serve one real Unix socket connection and count every frame that crosses it.

    Linux only: this is the boundary CPython cannot open on Windows, so the figure
    for it comes from a container rather than from a Windows estimate.
    """
    with tempfile.TemporaryDirectory(prefix="omniguard-uds-") as directory:
        path = Path(directory) / "gateway.sock"
        adapter = CountingAdapter(path, sink, clock=time.time, ledger=ledger)
        adapter.bind()
        served = threading.Thread(target=adapter.accept_once, daemon=True)
        served.start()
        written = _write_frames(path, device, events)
        served.join(timeout=10)
        adapter.close()
        return {
            "frames_written_by_the_producer": events,
            "bytes_written_by_the_producer": written,
            "adapter_counters": {
                "frames": adapter.counters.frames,
                "accepted": adapter.counters.accepted,
                "refused_by_sink": adapter.counters.refused_by_sink,
                "invalid_events": adapter.counters.invalid_events,
                "undecodable_bodies": adapter.counters.undecodable_bodies,
            },
            "peer_verification": str(adapter.counters.peer_verification),
        }


def run(
    password_file: Path,
    port: int,
    events: int,
    *,
    host: str = "127.0.0.1",
    through_uds: bool = False,
) -> dict:
    password = password_file.read_text(encoding="utf-8").strip()
    device = "volume-" + uuid.uuid4().hex
    topic = topic_for(device)
    received: queue.Queue = queue.Queue()
    uds_report: dict | None = None

    counter = MqttWireCounter(("0.0.0.0", 0), (host, port))
    counter.start()
    subscriber = _client(host, port, password, topic=topic)
    subscriber.on_message = lambda c, u, message: received.put_nowait(message.payload)
    time.sleep(0.5)  # let the subscription settle before anything is published

    counter.mark("connect")
    sender = _client("127.0.0.1", counter.port, password)
    ledger = VolumeLedger(device)
    try:
        with tempfile.TemporaryDirectory(prefix="omniguard-volume-") as directory:
            spool = BoundedSpool(Path(directory), max_bytes=1 << 20, max_age_seconds=300)
            producer = ProducerIdentity.start("volume-probe", time.time())
            publisher = TelemetryPublisher(
                CountingTransport(PahoTransport(sender), ledger), spool, producer, run_id=device
            )
            counter.mark("publish")
            started = time.time()
            acknowledged = 0
            if through_uds:
                # The whole chain: the gateway writes frames, the adapter reads them,
                # the bounded handoff carries them to the worker, the worker publishes.
                handoff = TelemetryHandoff(publisher, capacity=max(events, 16))
                handoff.start()
                uds_report = run_uds(handoff, device, events, ledger)
                # stop() drains what is queued before ending the worker, so the
                # counters below describe finished work rather than work in flight.
                uds_report["worker_stopped_cleanly"] = handoff.stop(timeout=10)
                uds_report["handoff_counters"] = vars(handoff.counters).copy()
                acknowledged = publisher.counters.published
            else:
                for index in range(events):
                    event = StateEvent(
                        device,
                        DeviceState.NORMAL,
                        DeviceState.SUSPICIOUS,
                        f"volume probe {index}",
                        time.time(),
                        None,
                    )
                    outcome = publisher.publish(event, now=time.time())
                    acknowledged += bool(outcome.broker_ack)
            elapsed = time.time() - started
            delivered = 0
            deadline = time.time() + 5
            while delivered < acknowledged and time.time() < deadline:
                try:
                    received.get(timeout=0.5)
                    delivered += 1
                except queue.Empty:
                    break
    finally:
        for client in (sender, subscriber):
            client.disconnect()
            client.loop_stop()
        time.sleep(0.3)  # let the FIN exchange reach the counter before it stops
        counter.stop()

    wire = counter.report()
    publish_bytes = wire["to_broker"]["segments"].get("publish", 0)
    return {
        "probe": "KAN-43 instrument check, not a sealed measurement run",
        "device": device,
        "events_published": events,
        "events_acknowledged": acknowledged,
        "events_delivered_to_subscriber": delivered,
        "publish_seconds": round(elapsed, 4),
        "ledger": ledger.summary(),
        "uds": uds_report,
        "wire": wire,
        "per_acknowledged_event": {
            "wire_bytes_to_broker": publish_bytes / acknowledged if acknowledged else None,
            "application_bytes": (
                ledger.boundaries["mqtt_application"].bytes_total / acknowledged
                if acknowledged and "mqtt_application" in ledger.boundaries
                else None
            ),
        },
        "limits": [
            "no frozen manifest: this is not the card's measurement run",
            "TCP payload bytes only; no IP/TCP headers or retransmissions",
            "one loopback broker on one host, not a deployment estimate",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--events", type=int, default=20)
    parser.add_argument(
        "--uds",
        action="store_true",
        help="drive the chain through a real Unix socket (Linux only)",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run(args.password_file, args.port, args.events, host=args.host, through_uds=args.uds)
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
