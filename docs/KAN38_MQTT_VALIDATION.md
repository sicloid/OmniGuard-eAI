# KAN-38 MQTT verification — 2026-09-12

Paho MQTT 2.1.0 is hash-pinned in both core and ML locks; the ML lock includes
the shared core input and is what CI installs. No previously pinned version changed.
Hash-verified installation and pip check passed on Linux/Python 3.14.7.

The worker-side adapter uses the specific MQTTMessageInfo object's completion,
not a successful local enqueue, as its PUBACK evidence. Reference: [Paho client
documentation](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).
Only MQTT 3.1.1/QoS1/non-retained messages are supported by this adapter.

Run against the project's existing loopback Mosquitto:

```sh
python -m lab.telemetry_probe --password-file /path/to/platform/.secrets/mqtt_password
```

The probe reads the credential without printing it, uses a unique device/topic,
bounded client queues, an independent subscriber and an ephemeral spool directory.
It does not stop the shared broker or change any Compose service.

Measured result:

```json
{
  "broker_puback": true,
  "subscriber_delivery": true,
  "disconnect_spooled": true,
  "retry_bytes_and_id_unchanged": true,
  "spool_empty_after_puback": true,
  "g10_passed": false
}
```

The branch suite ran 207 tests successfully with two platform-absence tests skipped
on Linux. Real Linux UDS permissions and peer-credential tests executed, not skipped.
Five new tests distinguish per-message completion, enqueue/error paths and invalid
publish parameters, and verify recovery on a surviving worker after counter-write
or scope-registration failure. Ruff lint/format and pip check passed.

Broker receipt and subscriber receipt are distinct from database durability. There
is no DB commit, production deployment or G10 completeness claim here. ADR-0003
remains PROPOSED pending remaining team review; merging implementation does not
silently promote it to an approved production wire contract.
