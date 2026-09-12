import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import paho.mqtt.client as mqtt

from telemetry.mqtt import PahoTransport
from telemetry.publisher import Acknowledgement, TransportError
from telemetry.spool import BoundedSpool, SpoolScope


class MqttTests(unittest.TestCase):
    def test_spool_worker_recovers_without_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = BoundedSpool(Path(directory), max_bytes=100, max_age_seconds=1)
            scope = SpoolScope("producer", "boot", 0)
            spool.append(1, b"lost", now=0, scope=scope)
            with patch.object(spool, "_save_counters", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    spool.enforce(now=2)
            spool.append(2, b"new", now=3, scope=scope)
            reopened = BoundedSpool(Path(directory), max_bytes=100, max_age_seconds=1)
            self.assertEqual(reopened.counters().dropped_events, 1)
            self.assertEqual([entry.sequence for entry in reopened.pending()], [2])

    def test_failed_scope_write_is_retried_before_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            spool = BoundedSpool(Path(directory), max_bytes=100, max_age_seconds=1)
            scope = SpoolScope("producer", "boot", 0)
            with patch.object(spool, "_write_atomic", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    spool.append(1, b"x", now=0, scope=scope)
            spool.append(2, b"y", now=0, scope=scope)
            reopened = BoundedSpool(Path(directory), max_bytes=100, max_age_seconds=1)
            self.assertEqual(reopened.scopes()[scope.token], scope)

    def test_only_message_completion_is_acked(self):
        client = Mock(protocol=mqtt.MQTTv311)
        info = client.publish.return_value
        info.rc = mqtt.MQTT_ERR_SUCCESS
        transport = PahoTransport(client, ack_timeout=0.2)
        for completed, expected in ((False, Acknowledgement.QUEUED), (True, Acknowledgement.ACKED)):
            info.is_published.return_value = completed
            self.assertEqual(transport.publish("test", b"x", qos=1, retain=False), expected)
        info.wait_for_publish.assert_called_with(timeout=0.2)

    def test_enqueue_and_wait_errors_remain_transport_failures(self):
        client = Mock(protocol=mqtt.MQTTv311)
        transport = PahoTransport(client)
        client.publish.return_value.rc = mqtt.MQTT_ERR_NO_CONN
        with self.assertRaises(TransportError):
            transport.publish("test", b"x", qos=1, retain=False)
        client.publish.return_value.rc = mqtt.MQTT_ERR_SUCCESS
        client.publish.return_value.wait_for_publish.side_effect = RuntimeError("disconnected")
        with self.assertRaises(TransportError):
            transport.publish("test", b"x", qos=1, retain=False)

    def test_reject_unbounded_or_non_qos1_requests(self):
        client = Mock(protocol=mqtt.MQTTv311)
        transport = PahoTransport(client)
        for body, qos, retain in ((b"x", 0, False), (b"x", 1, True), (b"x" * 65537, 1, False)):
            with self.assertRaises(TransportError):
                transport.publish("test", body, qos=qos, retain=retain)
        client.publish.assert_not_called()
