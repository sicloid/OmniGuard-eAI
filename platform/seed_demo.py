"""Publish fabricated StateEvents so the KAN-41 dashboard has something to draw.

These events are **invented**. They are a fixture for the dashboard, not a measurement,
and nothing here is evidence about detection, enforcement or timing. The card asks for
a dashboard demonstrated on fake data; this is that fake data, and it is labelled as
such in every row it writes: every event carries `reason = 'seed_demo'` and a `run_id`
beginning `seed-demo-`, so a real run is never confused with one of these.

Rows are not inserted into PostgreSQL directly. The events go out through the real
`TelemetryPublisher` — real canonical encoding, real ADR-0003 envelope, real topic,
real QoS 1 — and reach the database only if `platform/consume.py` accepts them. A
seeder that wrote rows itself could produce a dashboard that looks right while the
pipeline under it is broken, which is the one thing this dashboard must not do.

Run the consumer alongside it:

    python3 platform/consume.py --password-file platform/.secrets/mqtt_password \\
        --messages 48 --timeout 60
    python3 platform/seed_demo.py
"""

import argparse
import random
import sys
import tempfile
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

from core.schema import DeviceState, StateEvent
from telemetry.identity import ProducerIdentity
from telemetry.publisher import QOS, Acknowledgement, TelemetryPublisher, topic_for
from telemetry.spool import BoundedSpool

ROOT = Path(__file__).resolve().parent

DEVICES = ("lab-camera-01", "lab-camera-02", "lab-sensor-07", "lab-printer-03")
REASON = "seed_demo"

# A plausible walk through the state machine rather than random jumps: the dashboard
# should show transitions that a real policy could have produced.
WALK = {
    DeviceState.NORMAL: (DeviceState.SUSPICIOUS,),
    DeviceState.SUSPICIOUS: (DeviceState.QUARANTINED, DeviceState.NORMAL),
    DeviceState.QUARANTINED: (DeviceState.NORMAL,),
}


class MqttTransport:
    """Adapts paho to the publisher's Transport protocol."""

    def __init__(self, client: mqtt.Client):
        self._client = client

    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> Acknowledgement:
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        info.wait_for_publish(timeout=10)
        if not info.is_published():
            raise TimeoutError(f"broker did not acknowledge {topic}")
        # The broker replied with a PUBACK for this specific message, which is what
        # ACKED is allowed to mean. Anything weaker would have to say QUEUED.
        return Acknowledgement.ACKED


def events(count: int, span_seconds: float, now: float, seed: int):
    """Build `count` transitions spread backwards over `span_seconds`."""
    random = _rng(seed)
    state = dict.fromkeys(DEVICES, DeviceState.NORMAL)
    step = span_seconds / max(count, 1)
    for index in range(count):
        device = DEVICES[index % len(DEVICES)]
        previous = state[device]
        new = random.choice(WALK[previous])
        state[device] = new
        timestamp = now - span_seconds + step * index
        # Only a quarantine has a lease; NORMAL and SUSPICIOUS do not expire.
        expires_at = timestamp + 120.0 if new is DeviceState.QUARANTINED else None
        yield StateEvent(device, previous, new, REASON, timestamp, expires_at)


def _rng(seed: int) -> random.Random:
    return random.Random(seed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username", default="omniguard")
    parser.add_argument("--password-file", type=Path, default=ROOT / ".secrets" / "mqtt_password")
    parser.add_argument("--count", type=int, default=48)
    parser.add_argument(
        "--span-hours",
        type=float,
        default=5.0,
        help="spread the events backwards over this many hours so the default "
        "dashboard window is not empty",
    )
    parser.add_argument("--seed", type=int, default=41)
    arguments = parser.parse_args()

    if arguments.count < 1:
        print("FAIL: --count must be at least 1", file=sys.stderr)
        return 1

    now = time.time()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.username_pw_set(
        arguments.username, arguments.password_file.read_text(encoding="utf-8").strip()
    )
    client.connect(arguments.host, arguments.port, keepalive=30)
    client.loop_start()

    published = 0
    # The spool is throwaway. A one-shot seeder has nothing to resume, and fabricated
    # events left on disk would be drained into a later real run.
    with tempfile.TemporaryDirectory(prefix="omniguard-seed-") as spool_directory:
        publisher = TelemetryPublisher(
            MqttTransport(client),
            BoundedSpool(Path(spool_directory), max_bytes=1 << 20, max_age_seconds=300.0),
            # A fresh boot identity per invocation, so repeated seeding does not reuse
            # a sequence range and get recorded as a replay of the same boot.
            ProducerIdentity.start(f"seed-demo-{uuid.uuid4().hex[:8]}", now),
            run_id=f"seed-demo-{uuid.uuid4().hex[:8]}",
        )
        try:
            for event in events(
                arguments.count, arguments.span_hours * 3600.0, now, arguments.seed
            ):
                outcome = publisher.publish(event, now=time.time())
                if outcome.broker_ack:
                    published += 1
                else:
                    # Spooled or dropped both mean the broker did not confirm it, so
                    # the dashboard will not show it. Say which, and keep going.
                    state = "spooled" if outcome.spooled else "dropped"
                    print(
                        f"not delivered ({state}): {outcome.event_id} {outcome.reason or ''}",
                        file=sys.stderr,
                    )
        finally:
            client.loop_stop()
            client.disconnect()

    print(f"published {published}/{arguments.count} fabricated events to {topic_for(DEVICES[0])}")
    print(f"topic QoS {QOS}; every row is marked reason='{REASON}'.")
    print("These are invented events. They are not evidence of anything.")
    return 0 if published == arguments.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
