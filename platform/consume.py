"""Run the telemetry consumer against the Compose broker and database.

Wiring only. What to store and what a failure means lives in `telemetry/consumer.py`,
which is testable without Docker; this file supplies the two things that cannot be
faked — a real broker subscription and a real psql transaction — and is proved by
running it, not by unit tests.

Acknowledgement is manual and deliberate. Paho acknowledges a QoS 1 message as soon as
the callback returns unless `manual_ack` is set, which would mean the broker dropped
its copy before the row was committed: a database outage would become silent telemetry
loss, the exact failure ADR-0002 forbids. Here the PUBACK is sent only after the
transaction commits, so an unstored message stays with the broker and is redelivered.
Redelivery is safe because `event_id` makes the insert idempotent.

The session is persistent — a fixed client id and `clean_session=False` — because
withholding a PUBACK only preserves the message if the broker keeps the session. With a
clean session the broker discards the queue the moment this process disconnects, and
"the broker is holding it" would be a claim about something that had already been
thrown away. Two consumers must therefore not share a client id.
"""

import argparse
import json
import subprocess
import sys
import threading
from pathlib import Path

import paho.mqtt.client as mqtt

from telemetry.consumer import DatabaseError, TelemetryConsumer
from telemetry.publisher import QOS, TOPIC_PREFIX

ROOT = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
SUBSCRIPTION = f"{TOPIC_PREFIX}/+"


class ComposePsql:
    """Runs one script as one psql invocation inside the Compose `postgres` service.

    Follows `platform/migrate.py`: the credential is read inside the container and
    never enters host argv. `ON_ERROR_STOP` plus the script's own BEGIN/COMMIT means a
    statement that fails takes the whole transaction with it.
    """

    def __init__(self, user: str = "omniguard", database: str = "omniguard", timeout: int = 30):
        self.user, self.database, self.timeout = user, database, timeout

    def apply(self, sql: str) -> tuple[tuple[str, ...], ...]:
        try:
            result = subprocess.run(
                [
                    *COMPOSE,
                    "exec",
                    "-T",
                    "postgres",
                    "psql",
                    "-U",
                    self.user,
                    "-d",
                    self.database,
                    "-v",
                    "ON_ERROR_STOP=1",
                    # -q suppresses command tags. Without it psql writes BEGIN, INSERT
                    # 0 1 and COMMIT to stdout, the caller reads them as returned rows,
                    # and every insert looks like it stored something — a redelivery
                    # would be counted as a new event while the database correctly
                    # deduplicated it. Measured on PostgreSQL 17.6 before this flag.
                    "-q",
                    "-A",
                    "-t",
                    "-F",
                    "\t",
                    "-f",
                    "-",
                ],
                input=sql,
                text=True,
                # The database is UTF-8 and an event's `reason` is free text, so a
                # Turkish character in one would otherwise be encoded with the host
                # locale and rejected. See the same note in platform/migrate.py.
                encoding="utf-8",
                capture_output=True,
                timeout=self.timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            # Unreachable database, not a rejected statement: the message must not be
            # acknowledged, so this is raised rather than reported as a refusal.
            raise DatabaseError(f"psql could not be run: {error}") from error
        if result.returncode != 0:
            raise DatabaseError((result.stderr or result.stdout).strip())
        return tuple(tuple(line.split("\t")) for line in result.stdout.splitlines() if line.strip())


def on_message(consumer: TelemetryConsumer, client: mqtt.Client, message) -> None:
    try:
        document = json.loads(message.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        # Not a document at all. Acknowledged for the same reason the consumer
        # acknowledges a malformed envelope: redelivering it forever is a loop.
        consumer.counters.rejected += 1
        client.ack(message.mid, message.qos)
        print(f"rejected  {message.topic}: {error}", flush=True)
        return

    result = consumer.ingest(document)
    if result.acknowledge:
        client.ack(message.mid, message.qos)
    if result.rejected:
        print(f"rejected  {message.topic}: {result.rejected}", flush=True)
    elif result.failure:
        print(f"UNACKED   {message.topic}: {result.failure}", flush=True)
    else:
        state = "stored" if result.stored else "redelivered"
        print(f"{state:<9} {message.topic} boot={result.boot}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--username", default="omniguard")
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument(
        "--messages",
        type=int,
        default=0,
        help="stop after this many acknowledged messages; 0 runs until interrupted",
    )
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--client-id",
        default="omniguard-consumer",
        help="persistent session id; two consumers must not share one",
    )
    arguments = parser.parse_args()

    database = ComposePsql()
    try:
        consumer = TelemetryConsumer.restored(database)
        recorded = database.apply(
            "SELECT count(*), count(*) FILTER (WHERE verdict = 'UNORDERED') FROM boots;"
        )
    except DatabaseError as error:
        print(f"FAIL: cannot read the boot ledger: {error}", file=sys.stderr)
        return 1
    total, unordered_boots = recorded[0] if recorded else ("0", "0")
    print(f"ledger restored from the database: {total} boots, {unordered_boots} unordered")

    done = threading.Event()
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=arguments.client_id,
        clean_session=False,
        protocol=mqtt.MQTTv311,
        manual_ack=True,
    )
    client.username_pw_set(arguments.username, arguments.password_file.read_text().strip())

    def handle(client_, _userdata, message):
        on_message(consumer, client_, message)
        handled = consumer.counters.stored + consumer.counters.redelivered
        if arguments.messages and handled >= arguments.messages:
            done.set()

    client.on_message = handle
    client.on_connect = lambda c, *_: c.subscribe(SUBSCRIPTION, qos=QOS)

    client.connect(arguments.host, arguments.port, keepalive=30)
    client.loop_start()
    try:
        done.wait(timeout=arguments.timeout if arguments.messages else None)
    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()

    print(json.dumps(consumer.counters.as_dict(), indent=2, sort_keys=True))
    try:
        unordered = list(consumer.unordered_runs())
        print(f"runs excluded from ordering-dependent measurement: {unordered or 'none'}")
    except DatabaseError as error:
        # The database is the reason we are shutting down, so this is the expected
        # case rather than a surprise. It must not print an empty list: "none
        # excluded" and "could not ask" are different facts, and the first one is the
        # dangerous thing to say when an ordering-dependent measurement reads it.
        print(f"runs excluded from ordering-dependent measurement: NOT READ ({error})")
    # Nothing acknowledged without a commit; a nonzero count here is a backlog the
    # broker still holds, not loss.
    return 1 if consumer.counters.left_unacknowledged else 0


if __name__ == "__main__":
    raise SystemExit(main())
