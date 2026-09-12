"""Worker-side Paho QoS1 transport; only per-message PUBACK counts as ACKED.

The owner configures authentication, bounded client queues and connection/network
loop lifecycle before handing this adapter to TelemetryPublisher. Never call it
on the enforcement thread. MQTT 3.1.1 is required for this reference adapter.
"""

import paho.mqtt.client as mqtt

from core.schema import number
from telemetry.framing import MAX_FRAME
from telemetry.publisher import Acknowledgement, TransportError


class PahoTransport:
    def __init__(self, client: mqtt.Client, *, ack_timeout: float = 5.0):
        number(ack_timeout, "ack_timeout")
        if ack_timeout <= 0:
            raise ValueError("ack_timeout must be positive")
        if client.protocol != mqtt.MQTTv311:
            raise ValueError("reference transport requires MQTT 3.1.1")
        self.client = client
        self.ack_timeout = ack_timeout

    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> Acknowledgement:
        if qos != 1 or retain or not 0 < len(payload) <= MAX_FRAME:
            raise TransportError("requires QoS1, retain=false and bounded nonempty payload")
        try:
            info = self.client.publish(topic, payload, qos=1, retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise TransportError(f"MQTT enqueue failed: {info.rc}")
            # MQTTMessageInfo binds completion to this particular message's mid.
            info.wait_for_publish(timeout=self.ack_timeout)
            return Acknowledgement.ACKED if info.is_published() else Acknowledgement.QUEUED
        except (OSError, RuntimeError, ValueError) as exc:
            raise TransportError("MQTT publish failed") from exc
