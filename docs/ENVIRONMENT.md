# Environment and dependency lock — KAN-10

11 September 2026. Scope: interpreter pin, hash-verified dependency lock and
recorded platform tool versions. This document states what was executed and what
was only recorded; it does not claim ARM64 runtime validation.

## Interpreter

`.python-version` pins **3.14.7**. CI installs exactly 3.14.7 on both
`ubuntu-latest` and `windows-latest`.

`pyproject.toml` declares `requires-python = ">=3.14.7,<3.15"` rather than a
single exact version. The pin that defines the reference build is
`.python-version` plus the CI matrix; the `pyproject` range is a floor that
rejects older 3.14 patch releases without breaking every developer on the day a
3.14.8 security release appears. A build reproduced for results must record the
interpreter version actually used, not assume the floor.

Previous state: the declaration was `==3.14.*`, which accepted any 3.14 patch
release and therefore did not enforce the documented reference at all. One
developer environment was running 3.14.2 against a 3.14.7 reference.

## Dependency lock

`requirements.lock` lists every resolved package with SHA-256 hashes:

| Package | Version | Role |
|---|---|---|
| `setuptools` | 82.0.1 | build backend, required for the editable install |
| `dpkt` | 1.9.8 | PCAP parsing |
| `ruff` | 0.15.6 | lint and format |

There are no transitive dependencies: all three declare none. The resolved set is
therefore complete, not a partial snapshot.

`dpkt` and `setuptools` are `py3-none-any`, so one hash covers every platform.
`ruff` ships platform wheels; the lock carries three hashes — `win_amd64`,
`manylinux_2_17_x86_64` and `manylinux_2_17_aarch64`. macOS wheels exist upstream
but are not listed, because no team environment uses them and an unlisted
platform is more honest than an unverified one.

## Install

Hash verification requires that resolution produce no unlisted package, so the
project itself is installed separately with `--no-deps`.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
```

Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
```

`--no-build-isolation` is deliberate: build isolation would fetch a build-time
setuptools outside hash verification. The lock installs the pinned setuptools
first, so the build uses a verified copy.

`pip` itself is not listed. It comes from the `ensurepip` bundle inside the
pinned interpreter, so pinning 3.14.7 already determines it (26.2.1 here).

## Regenerating the lock

```sh
.venv/bin/python -m pip download <pkg>==<version> --no-deps --dest wheels
.venv/bin/python -m pip download ruff==<version> --no-deps --only-binary=:all: \
    --platform manylinux_2_17_x86_64 --dest wheels
.venv/bin/python -m pip download ruff==<version> --no-deps --only-binary=:all: \
    --platform manylinux_2_17_aarch64 --dest wheels
.venv/bin/python -m pip hash wheels/*
```

Keep the downloaded wheels out of Git; only the hashes belong in the lock.

## Verified on this change

Executed on Windows 11 x86_64, Python 3.14.7, pip 26.2.1:

- Fresh virtual environment, `--require-hashes` install of the full lock, then
  the editable project install with `--no-deps --no-build-isolation`. Both
  succeeded with no unlisted package pulled in.
- 21 unit tests pass. Ruff lint and format checks pass. The deterministic stub
  smoke runs and reports `g8_passed: false`, `g10_passed: false` as intended.
- The Compose stack was started on this host to check the environment itself, not
  only the Python packages. That run exposed a Windows-only defect in
  `platform/init_secrets.py`, fixed separately in PR #9 and deliberately not part
  of this change. With that fix applied, all three services reach healthy and
  `platform/smoke.py` passes: this is the first recorded platform smoke pass on
  Windows. Without it the broker stays unhealthy and the smoke cannot run.

## Recorded but not executed

- The `manylinux_2_17_x86_64` and `manylinux_2_17_aarch64` `ruff` wheels were
  downloaded and hashed on this machine, not installed or run. An aarch64 wheel
  existing is not ARM64 validation.
- Real ARM64 execution belongs to KAN-53 and KAN-44 with actual Pi 5 hardware.

## Platform tool versions

| Environment | Docker | Compose |
|---|---|---|
| Gabriel, Windows 11 | 28.1.1 | v2.35.1-desktop.1 |
| Şükrü, CachyOS (from `docs/LINUX_VALIDATION.md`) | 29.7.2 | 5.4.0 |

These are recorded, not pinned. The PR #2 follow-up about Compose output shape was
measured here rather than assumed: `docker compose ps --format json` returns JSON
Lines on v2.35.1, so the line-oriented parser in `platform/smoke.py` is correct on
this host and needs no change. Compose has altered this format across major
versions before, so the check is worth repeating on a version bump.

Container images are pinned by digest in `platform/compose.yaml` and are the
authoritative platform pin. Host Docker and Compose versions are development
tooling and are expected to differ between team machines.

## Out of scope for KAN-10

- Scientific stack (`scikit-learn`, `numpy`, `joblib`). Those belong to R1's
  model work; pinning them before Onur selects versions would freeze choices
  that are not ours to make. ADR-0001 already defers this to R1/R3 jointly.
- ARM64 runtime validation, per the section above.
- `telemetry` and `measure` are absent from `[tool.setuptools.packages.find]`
  because they contain no Python package yet. KAN-38 adds `telemetry`.
