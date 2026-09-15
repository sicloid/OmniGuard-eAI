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

## Schema migrations — KAN-39

```sh
python3 platform/migrate.py
```

Numbered files in `platform/migrations/NNN_name.sql` are applied once each, in
version order, against the running Compose database. `schema_migrations` records
the version, name and SHA-256 of the file bytes. Each file is sent as a single
transaction that takes `pg_advisory_xact_lock` first, so a second runner started
at the same time blocks and then finds the version already recorded; its own
transaction rolls back and it applies nothing. A migration that fails anywhere is
rolled back whole and is never recorded, so the next start retries it.

The runner refuses to start, rather than guessing, when the recorded history and
the files disagree: an applied file whose checksum changed, an applied version no
longer on disk, or a new file numbered below applied history. Files must not
contain their own `BEGIN`/`COMMIT` or `CONCURRENTLY`, because the runner owns the
transaction; PL/pgSQL blocks are allowed and their `BEGIN` is not transaction
control. Applied migrations are immutable — correct a mistake with a new file.

`001_initial_schema.sql` creates the `events` table for the approved 0.1.0
`TelemetryPayload` and its nested `StateEvent`: `event_id` as primary key so
redelivery is an `ON CONFLICT DO NOTHING`, `run_id` because it is a 0.1.0 field,
the five `StateEvent` fields, and CHECK constraints mirroring
`StateEvent.__post_init__`. `StateEvent.timestamp` is stored as `event_timestamp`
because `timestamp` is a SQL type name; the mapping is listed in the file. The
wire value is kept as sent, with a generated `event_time timestamptz` for
time-range queries and a separate `ingested_at` so event time and arrival time
cannot be confused — G10 latency is the difference between them.

Per the Lead decision recorded on KAN-39 on 14 September 2026, this migration
carries no boots table, no `boot_id` and no producer/boot ordering columns. Those
are KAN-40's additive `002`. ADR-0003 remains PROPOSED and is not treated as
accepted by this file.

Two non-owner roles are created: `omniguard_consumer` (SELECT, INSERT on `events`
only — telemetry history is append-only, and a consumer that could rewrite it
could not be used as evidence) and `omniguard_readonly` (SELECT, for KAN-41's
Grafana datasource). Neither is given a password here, so neither can
authenticate until one is provisioned outside version control; that provisioning
is not part of KAN-39. Note that the `postgres` image trusts local socket
connections, so this separates authority over the schema, not access from inside
the container.

`tests/test_platform_migrations.py` covers the runner's decision logic against an
injected executor: ordering, drift refusal, rollback, retry and the concurrent
race. It executes no SQL and is **not** evidence that `001` applies. That comes
only from running the command above against the real database.

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

KAN-40–41: the MQTT consumer, its additive `002` boot migration, and a
provisioned PostgreSQL datasource/dashboard. Grafana currently uses its default
metadata database; HTTP health does not prove telemetry queries. Role passwords
are not yet provisioned, so nothing runs as `omniguard_consumer` or
`omniguard_readonly` today. Further tables (devices, detection_events,
experiment_runs, resource_metrics) follow their own cards and ADR decisions.
G5/G8/G10 are pending; a created table is not a delivered event.

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
