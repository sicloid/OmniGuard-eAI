# R3 — self-hosted platform

Owner: Gabriel (@Gabi8347). KAN-36/KAN-37: Mosquitto 2.0.22, PostgreSQL 17.6
and Grafana 12.1.1, pinned by multi-architecture image digest. These are tested
versions, not a claim to be the newest releases. Never add `__init__.py` here.

## Start and verify

Requires Python 3, a running Linux Docker engine and Compose v2 or newer.
Run from the repository root:

```sh
python3 platform/init_secrets.py
docker compose -f platform/compose.yaml up -d --wait --wait-timeout 180
python3 platform/smoke.py
docker compose -f platform/compose.yaml ps
```

The initializer creates random credentials in ignored `platform/.secrets/`
(directory mode 0700). Files are readable to container users through individual
read-only secret mounts. Existing credentials are preserved. Credentials do not
belong in Git, host shell arguments or Compose environment. Run on Linux;
native Windows file permissions are not validated.

- Grafana: http://127.0.0.1:3000, user `admin`, password in
  `platform/.secrets/grafana_password`.
- MQTT: `127.0.0.1:1883`, user `omniguard`, password in
  `platform/.secrets/mqtt_password`. Anonymous clients are rejected; this development
  identity can read/write only `omniguard/#`. Smoke uses a random non-retained topic
  with QoS 1. This is not the final telemetry event/topic/deduplication contract.
- PostgreSQL: no published host port. Internal service name `postgres:5432`,
  database/user `omniguard`, password in `platform/.secrets/postgres_password`.

`MQTT_PORT` and `GRAFANA_PORT` environment variables override loopback ports.
The private `telemetry` network is internal. MQTT/Grafana also join `local_access`
so Docker can publish loopback ports. The packet lab never joins these networks.
HTTP/MQTT here are local development endpoints; remote access/TLS remain separate work.

Smoke verifies three healthchecks, PostgreSQL SELECT 1, real MQTT QoS 1 pub/sub,
anonymous denial, outside-topic denial, Grafana HTTP health and login. Mosquitto
2.0 may return exit code 0 for an MQTT v5 denied publish; the test checks the
explicit negative PUBACK warning. CI runs this unprivileged service smoke;
privileged namespace tests remain dedicated-host-only.

## Stop and resume

```sh
docker compose -f platform/compose.yaml down
docker compose -f platform/compose.yaml up -d --wait
python3 platform/smoke.py
```

Named volumes preserve state. Do not remove volumes or regenerate credentials to
restart: PostgreSQL/Grafana initialize passwords only on first boot. Rotation
needs coordinated service-side changes.

## Remaining R3 work

KAN-38–41: StateEvent adapter, application migrations, consumer and provisioned
PostgreSQL datasource/dashboard. Grafana currently uses its default metadata
database; HTTP health does not prove telemetry queries. Future tables: devices,
detection_events, state_events, experiment_runs, resource_metrics. G10 is pending.

References: [Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/),
[healthchecks](https://docs.docker.com/reference/compose-file/services/),
[Mosquitto authentication](https://mosquitto.org/documentation/authentication-methods/).

## PR #2 review follow-up

Run smoke without `-O` or `PYTHONOPTIMIZE`; optimized Python is rejected before
Docker access because this probe uses assertions. The negative PUBACK check
depends on the pinned Mosquitto client warning text; revalidate it on image upgrades.
Compose JSON-array versus JSONL portability remains Gabriel’s Windows follow-up.

Secret files use mode 0444 within a 0700 directory so container service UIDs can
read bind-mounted secrets in this local development setup. This is not a production
secret distribution design. MQTT passwords avoid host argv and logs, but the client
inside the container receives `-P` in its process arguments; privileged container
inspection can expose it. Restrict local Docker access accordingly.
