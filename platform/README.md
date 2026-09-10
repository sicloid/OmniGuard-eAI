# R3 — Gabriel

First task: pinned Mosquitto, PostgreSQL and Grafana Docker Compose services with
local smoke tests and documented credentials supplied outside Git.
Minimum tables: devices, detection_events, state_events, experiment_runs,
resource_metrics. Provision Grafana against PostgreSQL; avoid a custom SaaS UI.
This directory is configuration only; never add `__init__.py` because it would
shadow Python's standard-library `platform` module.
