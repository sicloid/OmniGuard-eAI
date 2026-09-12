"""Exercise the running Compose skeleton; this is not the G10 event-chain gate."""

import base64
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]


def run(*args):
    return subprocess.run(
        [*COMPOSE, *args], text=True, capture_output=True, check=True, timeout=30
    ).stdout.strip()


def mqtt(command, *args):
    # Read the password inside the container; it never enters host argv or logs.
    return [
        *COMPOSE,
        "exec",
        "-T",
        "mosquitto",
        "sh",
        "-ec",
        'exec "$@" -h 127.0.0.1 -u omniguard -P "$(cat /run/secrets/mqtt_password)"',
        "sh",
        command,
        *args,
    ]


def main():
    if not __debug__:
        raise SystemExit("Smoke requires assertions; run Python without -O/PYTHONOPTIMIZE.")
    states = [json.loads(line) for line in run("ps", "--format", "json").splitlines()]
    assert len(states) == 3 and all(s["Health"] == "healthy" for s in states), states
    assert (
        run(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "omniguard",
            "-d",
            "omniguard",
            "-Atc",
            "SELECT 1",
        )
        == "1"
    )
    topic = f"omniguard/smoke/{uuid.uuid4()}"
    payload = f"probe-{uuid.uuid4()}"
    subscriber = subprocess.Popen(
        mqtt("mosquitto_sub", "-t", topic, "-q", "1", "-C", "1", "-W", "10"),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Repeat bounded non-retained publishes: startup cannot race a single publish.
        for _ in range(20):
            subprocess.run(
                mqtt("mosquitto_pub", "-t", topic, "-q", "1", "-m", payload),
                capture_output=True,
                check=True,
                timeout=5,
            )
            if subscriber.poll() is not None:
                break
            time.sleep(0.1)
        received, error = subscriber.communicate(timeout=12)
        assert subscriber.returncode == 0 and received.strip() == payload, error
    finally:
        if subscriber.poll() is None:
            subscriber.kill()
            subscriber.communicate()
    anonymous = subprocess.run(
        [
            *COMPOSE,
            "exec",
            "-T",
            "mosquitto",
            "mosquitto_pub",
            "-h",
            "127.0.0.1",
            "-V",
            "mqttv5",
            "-t",
            topic,
            "-q",
            "1",
            "-m",
            "must-be-rejected",
        ],
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert anonymous.returncode != 0 and "authoriz" in anonymous.stderr.lower()
    denied = subprocess.run(
        mqtt("mosquitto_pub", "-V", "mqttv5", "-t", "outside/smoke", "-q", "1", "-m", payload),
        text=True,
        capture_output=True,
        timeout=5,
    )
    # Mosquitto 2.0 reports a denied MQTT v5 PUBACK as a warning with exit code 0.
    assert "Publish 1 failed: Not authorized" in denied.stderr, denied.stderr
    address = run("port", "grafana", "3000")
    assert address.startswith("127.0.0.1:"), address
    with urllib.request.urlopen(f"http://{address}/api/health", timeout=5) as response:
        assert json.load(response)["database"] == "ok"
    password = (ROOT / ".secrets/grafana_password").read_text().strip()
    auth = base64.b64encode(f"admin:{password}".encode()).decode()
    request = urllib.request.Request(
        f"http://{address}/api/user", headers={"Authorization": f"Basic {auth}"}
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert json.load(response)["login"] == "admin"
    print("PASS: three healthy services; PostgreSQL SELECT 1; MQTT QoS1 pub/sub;")
    print("anonymous/unauthorized-topic rejection; Grafana HTTP health and admin login.")


if __name__ == "__main__":
    main()
