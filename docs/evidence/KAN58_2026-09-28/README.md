# KAN-58 demo rehearsal evidence — 28 September 2026

`demo.log` is the combined stdout/stderr from `./demo.sh` at source commit
`88c8bcc01582f9ffaa569a15e97edc79e6121d2c`. The command exited zero on the
Linux/Docker development host. Its SHA-256 is
`5239ecb04d71149e7aa5faf6d1cc0cf3571803f71be403b9b0eb2e7d19c53e58`.

The run verifies platform health and access controls, migrations and roles,
MQTT QoS 1 delivery, the isolated synthetic detector-to-nftables wiring path,
independent TCP/UDP stop and restore, owned-namespace cleanup, and the sealed
G10 evidence fallback. The lab report records zero kernel drops.

The run explicitly records `synthetic_only_not_g8=true`. It is demo-wiring and
cleanup evidence, not a model-accuracy result and not a replacement for the
separate real-model G8 evidence under `KAN69_2026-09-28`.
