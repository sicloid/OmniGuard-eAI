# OmniGuard eAI — Repository Blueprint v2

Recommended monorepo:

```text
omniguard/
├── README.md
├── AI_SYSTEM_PROMPT.md
├── SCHEMA.md
├── CODEOWNERS
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── core/
│   ├── schema.py
│   ├── packets.py
│   └── features.py
│
├── sources/
│   ├── from_pcap.py
│   └── from_live.py
│
├── model/
│   ├── train.py
│   ├── evaluate.py
│   ├── splits.py
│   ├── ablation.py
│   └── artifacts/
│
├── gateway/
│   ├── engine.py
│   ├── windowing.py
│   ├── detector.py
│   ├── state_machine.py
│   └── enforce.py
│
├── telemetry/
│   ├── uds_adapter.py
│   ├── mqtt_publisher.py
│   └── consumer.py
│
├── platform/
│   ├── docker-compose.yml
│   ├── mosquitto/
│   ├── postgres/
│   └── grafana/
│
├── measure/
│   ├── harness.py
│   ├── resources.py
│   ├── leakage.py
│   └── plots.py
│
├── lab/
│   ├── setup_netns.sh
│   ├── teardown_netns.sh
│   ├── replay.py
│   └── sink.py
│
├── stubs/
│   ├── fake_features.py
│   ├── fake_detector.py
│   └── fake_telemetry.py
│
├── scripts/
│   ├── build_sample_pack.py
│   └── run_pi_validation.sh
│
├── data/
│   └── samplepack/
│
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
│
└── docs/
    ├── adr/
    ├── architecture/
    ├── methodology/
    └── demo/
```

## Ownership

### R1
- core/features.py
- model/*
- data/samplepack pipeline

### R2
- sources/*
- gateway/*
- lab/*

### R3
- telemetry/*
- platform/*
- measure/*

### Team Lead
- SCHEMA.md
- docs/adr/*
- CODEOWNERS coordination
- release/integration process

## Branch examples

```text
feat/KAN-12-feature-extractor
feat/KAN-18-netns-topology
feat/KAN-24-mqtt-telemetry
feat/KAN-28-postgres-consumer
feat/KAN-31-grafana-dashboard
exp/KAN-40-feature-ablation
fix/KAN-45-conntrack-quarantine
```

## Secrets

`.env.example` documents:
- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- MQTT_HOST
- MQTT_PORT
- MQTT_USER
- MQTT_PASSWORD

Real values ignored by Git.

## CI

Unprivileged CI:
- install
- lint
- unit tests
- schema tests
- model-meta compatibility
- platform config validation where possible

Privileged netns/nftables tests run on dedicated local/Pi integration host, not generic shared CI runner.
