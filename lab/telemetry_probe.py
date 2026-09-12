"""Real loopback Mosquitto delivery and restart retry; not a DB/G10 proof."""

import argparse
import json
import queue
import tempfile
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

from core.schema import DeviceState, StateEvent
from telemetry.identity import ProducerIdentity
from telemetry.mqtt import PahoTransport
from telemetry.publisher import TelemetryPublisher, topic_for
from telemetry.spool import BoundedSpool


def run(password_file: Path, port: int) -> dict:
    password = password_file.read_text().strip()
    clients = []
    received = queue.Queue(maxsize=4)
    subscribed = threading.Event()
    device = "probe-" + uuid.uuid4().hex
    topic = topic_for(device)

    def connect(subscriber=False):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        clients.append(client)
        client.username_pw_set("omniguard", password)
        client.connect_timeout = 5
        client.max_queued_messages_set(8)
        client.max_inflight_messages_set(4)
        connected = threading.Event()

        def on_connect(c, userdata, flags, reason_code, properties):
            if not reason_code.is_failure:
                if subscriber:
                    c.subscribe(topic, qos=1)
                connected.set()

        client.on_connect = on_connect
        client.on_subscribe = lambda *args: subscribed.set()
        client.on_message = lambda c, u, message: received.put_nowait(message.payload)
        client.connect("127.0.0.1", port, keepalive=20)
        client.loop_start()
        if not connected.wait(5):
            raise RuntimeError("broker connection was not acknowledged")
        return client

    try:
        connect(subscriber=True)
        if not subscribed.wait(5):
            raise RuntimeError("subscription was not acknowledged")
        sender = connect()
        with tempfile.TemporaryDirectory(prefix="omniguard-mqtt-") as directory:
            spool = BoundedSpool(Path(directory), max_bytes=65536, max_age_seconds=60)
            producer = ProducerIdentity.start("linux-probe", time.time())
            publisher = TelemetryPublisher(PahoTransport(sender), spool, producer, run_id=device)
            event = StateEvent(
                device,
                DeviceState.NORMAL,
                DeviceState.SUSPICIOUS,
                "controlled delivery probe",
                time.time(),
                None,
            )
            first = publisher.publish(event, now=time.time())
            body = received.get(timeout=5)
            if not first.broker_ack or first.event_id.encode() not in body:
                raise RuntimeError("PUBACK/subscriber delivery mismatch")

            sender.disconnect()
            sender.loop_stop()
            failed = publisher.publish(event, now=time.time())
            if failed.broker_ack or not failed.spooled:
                raise RuntimeError("disconnected publish was not retained in spool")
            stored = spool.read(spool.pending()[0])
            restarted = TelemetryPublisher(
                PahoTransport(connect()),
                spool,
                ProducerIdentity.start("linux-probe", time.time()),
                run_id=device,
            )
            outcomes = restarted.drain(now=time.time())
            retried = received.get(timeout=5)
            if (
                len(outcomes) != 1
                or not outcomes[0].broker_ack
                or outcomes[0].event_id != failed.event_id
                or retried != stored
                or spool.pending()
            ):
                raise RuntimeError("restart retry lost identity, bytes or delivery")
            return {
                "broker_puback": True,
                "subscriber_delivery": True,
                "disconnect_spooled": True,
                "retry_bytes_and_id_unchanged": True,
                "spool_empty_after_puback": True,
                "g10_passed": False,
            }
    finally:
        for client in clients:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--port", type=int, default=1883)
    args = parser.parse_args()
    print(json.dumps(run(args.password_file, args.port), indent=2))
