"""KAN-43 sealed measurement run: telemetry bytes at every boundary of the real chain.

Unlike `lab/telemetry_volume_probe.py`, which is an instrument check, this is the
card's run. The `ExperimentManifest` is frozen before the first byte moves; its sealed
configuration names the event schedule, the policy parameters and the SHA-256 of every
file on the measured path, and the figures are written into `measurements` at close.

The chain is the shipped one end to end, with nothing on the gateway side written for
this run:

    DevicePolicy -> GatewayEventBridge -> UnixSocketTransport -> socket
      -> CountingAdapter -> TelemetryHandoff -> TelemetryPublisher
      -> CountingTransport(PahoTransport) -> relay -> Mosquitto

Detections are scripted: byte volume depends on the StateEvents the policy emits, not
on how a model scored the window, so no model is loaded. The policy itself is the real
`gateway.policy.DevicePolicy` with the Lead's frozen N=2 and 300 s lease (ADR-0004 7b),
driven by a seeded, declared clock that ends before the run starts, so every timestamp
is a plausible past instant of the same magnitude a live gateway writes.

Delivery completeness is not claimed here. The consumer runs beside this process
(`platform/consume.py`) and the committed rows for this run id are exported after it;
`docs/evidence/KAN43_*/verify.py` joins the two.

    python -m lab.kan43_sealed_run --host mosquitto --password-file \\
        platform/.secrets/mqtt_password --out /out
"""

import argparse
import hashlib
import math
import random
import tempfile
import threading
import time
import uuid
from pathlib import Path

import paho.mqtt.client as mqtt

from core.schema import Classification, DetectionResult
from gateway.event_bridge import GatewayEventBridge, UnixSocketTransport, state_event_frame
from gateway.policy import DevicePolicy
from lab.mqtt_wire_counter import MqttWireCounter
from measure.manifest import (
    FAILED,
    POLICY_CONFIG_KEY,
    POLICY_CONFIG_VERSION,
    ExperimentManifest,
    ProvenanceFromR2,
)
from telemetry.accounting import (
    MQTT_PUBLISH_PACKET,
    UDS_FRAME,
    CountingAdapter,
    CountingTransport,
    VolumeLedger,
)
from telemetry.handoff import TelemetryHandoff
from telemetry.identity import ProducerIdentity
from telemetry.mqtt import PahoTransport
from telemetry.publisher import TelemetryPublisher
from telemetry.spool import BoundedSpool

# Every file whose bytes decide what is sent or how it is counted. Their hashes are
# sealed in the manifest so a reviewer can tell whether a checkout still runs this code.
MEASURED_PATH = (
    "lab/kan43_sealed_run.py",
    "lab/mqtt_wire_counter.py",
    "telemetry/accounting.py",
    "telemetry/canonical.py",
    "telemetry/envelope.py",
    "telemetry/framing.py",
    "telemetry/handoff.py",
    "telemetry/identity.py",
    "telemetry/mqtt.py",
    "telemetry/publisher.py",
    "telemetry/spool.py",
    "telemetry/uds.py",
    "gateway/event_bridge.py",
    "gateway/policy.py",
    "core/schema.py",
)

# The Lead's frozen choice, ADR-0004 decision 7b (PR #46).
POLICY = {
    "policy_config_version": POLICY_CONFIG_VERSION,
    "n": 2,
    "lease_seconds": 300.0,
    "max_lease": 300.0,
}
MODEL = ("rf-iot23", "0.1.0-seed1-kan19", 0.9798815486832)  # names only; nothing is loaded
DEVICE = "camera"
WINDOW = 5
PUBACK_BYTES = 4  # MQTT 3.1.1: fixed header 2 + packet id 2
DISCONNECT_BYTES = 2


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _machine_context() -> ProvenanceFromR2:
    """The run's own kernel: boot id and boot time, read here rather than supplied.

    `host_id` stays unsupplied: inside a container the hostname names the container,
    not a machine, and publishing it as a host identity would be a different claim.
    """
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    btime = next(
        int(line.split()[1])
        for line in Path("/proc/stat").read_text().splitlines()
        if line.startswith("btime ")
    )
    return ProvenanceFromR2(boot_id=boot_id, boot_started_at=float(btime))


def policy_events(cycles: int, seed: int, *, end: float) -> list:
    """Drive the real policy through `cycles` quarantine episodes and keep what it emits.

    Each cycle is two ANOMALOUS windows (N=2: SUSPICIOUS, then QUARANTINED with a lease)
    followed by the lease running out (NORMAL), then an explicit rearm. The clock is
    synthetic but obeys the policy's own admission rules — aligned windows, results no
    older than MAX_RESULT_AGE — and is shifted so the last event lands before `end`.
    """
    rng = random.Random(seed)
    policy = DevicePolicy(
        DEVICE, n=POLICY["n"], lease_seconds=POLICY["lease_seconds"], max_lease=POLICY["max_lease"]
    )
    model_id, model_version, threshold = MODEL
    span = cycles * (2 * WINDOW + POLICY["lease_seconds"] + 4 * WINDOW)
    start = math.floor((end - span - 60) / WINDOW) * WINDOW
    now = float(start)
    events = []
    for _ in range(cycles):
        # Consecutive windows: a gap would reset the series and N would never be reached.
        window = math.floor(now / WINDOW) * WINDOW + WINDOW
        for index in range(POLICY["n"]):
            window += WINDOW if index else 0
            now = window + WINDOW + rng.uniform(0.0, 2.0)
            result = DetectionResult(
                DEVICE, window, model_id, model_version, 1.0, Classification.ANOMALOUS, threshold
            )
            events += policy.observe(result, now=now, mono=now)
        now += POLICY["lease_seconds"] + rng.uniform(0.0, 2.0)
        events += policy.tick(now=now, mono=now)
        policy.rearm()
    if now >= end:
        raise RuntimeError("the declared schedule would produce future timestamps")
    return events


def _connect(host: str, port: int, password: str, keepalive: int) -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    client.username_pw_set("omniguard", password)
    connected = threading.Event()
    client.on_connect = lambda c, u, f, reason, p: None if reason.is_failure else connected.set()
    client.connect(host, port, keepalive=keepalive)
    client.loop_start()
    if not connected.wait(5):
        raise RuntimeError("broker connection was not acknowledged")
    return client


def _wait(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)
    return True


def measure(manifest: ExperimentManifest, events: list, *, host: str, port: int, password: str):
    run_id = manifest.run_id
    ledger = VolumeLedger(run_id)
    relay = MqttWireCounter(("127.0.0.1", 0), (host, port))
    relay.start()
    relay.mark("connect")
    # CONNACK has reached the client, so CONNECT and CONNACK are both counted and nothing
    # of the publish phase has been sent: the mark below is at a synchronisation point.
    sender = _connect("127.0.0.1", relay.port, password, manifest.config["mqtt"]["keepalive"])
    relay.mark("publish")
    with tempfile.TemporaryDirectory(prefix="kan43-") as directory:
        spool = BoundedSpool(Path(directory) / "spool", max_bytes=1 << 20, max_age_seconds=3600)
        producer = ProducerIdentity.start("kan43-host", time.time())
        publisher = TelemetryPublisher(
            CountingTransport(PahoTransport(sender), ledger), spool, producer, run_id=run_id
        )
        handoff = TelemetryHandoff(publisher, capacity=len(events) + 16)
        handoff.start()
        path = Path(directory) / "gateway.sock"
        adapter = CountingAdapter(path, handoff, clock=time.time, ledger=ledger, timeout=0.5)
        adapter.bind()
        serving = threading.Thread(target=adapter.serve_forever, daemon=True)
        serving.start()

        bridge = GatewayEventBridge(UnixSocketTransport(path), capacity=len(events) + 16)
        bridge.start()
        produced_bytes = 0
        submitted = {"ACCEPTED": 0, "OVERFLOWED": 0, "REFUSED": 0}
        for event in events:
            produced_bytes += len(state_event_frame(event))
            submitted[str(bridge.submit(event))] += 1
        bridge_drained = _wait(
            lambda: bridge.counters.delivered + bridge.counters.failures >= submitted["ACCEPTED"],
            30,
        )
        bridge_stopped = bridge.stop()
        adapter_drained = _wait(lambda: adapter.counters.frames >= bridge.counters.delivered, 10)
        adapter.stop()
        serving.join(timeout=5)
        adapter.close()
        # stop() drains what is queued, and each publish waits for its PUBACK, so once it
        # returns the last PUBACK has reached the client: the second synchronisation point.
        handoff_stopped = handoff.stop(timeout=30)
        relay.mark("close")
        sender.disconnect()
        sender.loop_stop()
        time.sleep(0.3)  # let the FIN reach the relay before it stops counting
        relay.stop()
        spool_counters = spool.counters()
        spool_pending = len(spool.pending())

    wire = relay.report()
    summary = ledger.summary()
    acked = summary["events"]["broker_acknowledged"]

    def segment(direction: str, name: str) -> int:
        return wire[direction]["segments"].get(name, 0)

    expected_publish = summary["boundaries"].get(MQTT_PUBLISH_PACKET, {}).get("bytes_total", 0)
    counted_uds = summary["boundaries"].get(UDS_FRAME, {}).get("bytes_total", 0)
    return {
        "measures": "KAN-43 sealed run: telemetry bytes per boundary, real gateway→broker chain",
        "events": {
            "produced_by_policy": len(events),
            "bridge_submit": submitted,
            "bridge": vars(bridge.counters).copy() | {"stopped_cleanly": bridge_stopped},
            "adapter": {
                name: getattr(adapter.counters, name)
                for name in (
                    "connections",
                    "frames",
                    "accepted",
                    "refused_by_sink",
                    "invalid_events",
                    "undecodable_bodies",
                    "read_timeouts",
                )
            }
            | {"peer_verification": str(adapter.counters.peer_verification)},
            "handoff": vars(handoff.counters).copy() | {"stopped_cleanly": handoff_stopped},
            "publisher": vars(publisher.counters).copy(),
            "spool": {
                name: value for name, value in vars(spool_counters).items() if name != "scopes"
            }
            | {"loss_scopes": len(spool_counters.scopes), "pending_at_close": spool_pending},
            "waits": {"bridge_drained": bridge_drained, "adapter_drained": adapter_drained},
        },
        "ledger": summary,
        "wire": wire,
        # Each line compares a counted figure with the one the protocol predicts for the
        # same bytes. A nonzero residue is reported, never folded into the per-event cost.
        "reconciliation": {
            "uds_bytes_written_by_gateway": produced_bytes,
            "uds_bytes_counted_by_adapter": counted_uds,
            "uds_residue": counted_uds - produced_bytes,
            "publish_to_broker_counted": segment("to_broker", "publish"),
            "publish_to_broker_derived": expected_publish,
            "publish_to_broker_residue": segment("to_broker", "publish") - expected_publish,
            "publish_from_broker_counted": segment("from_broker", "publish"),
            "publish_from_broker_expected_pubacks": PUBACK_BYTES * acked,
            "publish_from_broker_residue": segment("from_broker", "publish") - PUBACK_BYTES * acked,
            "close_to_broker_counted": segment("to_broker", "close"),
            "close_to_broker_expected_disconnect": DISCONNECT_BYTES,
        },
        "per_acknowledged_event": {
            name: (volume["bytes_total"] / acked if acked else None)
            for name, volume in summary["boundaries"].items()
        }
        | {
            "wire_to_broker_publish_phase": segment("to_broker", "publish") / acked
            if acked
            else None,
            "wire_from_broker_publish_phase": segment("from_broker", "publish") / acked
            if acked
            else None,
        },
        "per_second": "computed over the manifest window by verify.py, not here",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="mosquitto")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--password-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--seed", type=int, default=43)
    args = parser.parse_args()

    run_id = "kan43-" + uuid.uuid4().hex
    root = Path(__file__).resolve().parent.parent
    config = {
        "card": "KAN-43",
        "schedule": {
            "cycles": args.cycles,
            "seed": args.seed,
            "per_cycle": "N ANOMALOUS windows, then lease expiry, then rearm",
            "device_id": DEVICE,
        },
        POLICY_CONFIG_KEY: POLICY,
        "mqtt": {
            "broker": f"{args.host}:{args.port}",
            "protocol": "3.1.1",
            "qos": 1,
            "retain": False,
            "keepalive": 60,
        },
        "code_sha256": {name: _sha256(root / name) for name in MEASURED_PATH},
    }
    manifest = ExperimentManifest(
        run_id,
        args.out / run_id,
        config,
        r2=_machine_context(),
        notes=(
            "R1 fields are not supplied because no dataset or model is read: byte volume "
            "depends on the StateEvents the policy emits, and detections are scripted. "
            "R2 boot_id/boot_started_at were read by this run from its own kernel "
            "(Docker Desktop's Linux VM); host_id, t0 and sink evidence do not apply."
        ),
    )
    manifest.freeze()
    password = args.password_file.read_text(encoding="utf-8").strip()
    try:
        events = policy_events(args.cycles, args.seed, end=time.time())
        measurements = measure(manifest, events, host=args.host, port=args.port, password=password)
    except BaseException as error:
        manifest.close(measurements={}, status=FAILED, outcome={"error": repr(error)})
        raise
    manifest.close(measurements=measurements)
    print(manifest.path)


if __name__ == "__main__":
    main()
