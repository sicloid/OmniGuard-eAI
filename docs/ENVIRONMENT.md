# Environment and dependency lock — KAN-10

11 September 2026. Scope: interpreter pin, hash-verified dependency lock and
recorded platform tool versions. This document states what was executed and what
was only recorded; it does not claim ARM64 runtime validation.

## Interpreter

`.python-version` pins **3.14.7**. CI installs exactly 3.14.7 on both
`ubuntu-latest`, `windows-latest` and `macos-latest`.

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

The core lock also pins pip 26.2.1. `requirements-ml.lock` includes the core and
R1's scikit-learn 1.8.0 / numpy 2.5.3 combination plus scipy 1.18.1, joblib 1.6.0,
threadpoolctl 3.6.0 and cloudpickle 3.1.2. Transitive versions are explicitly listed
in `requirements-ml.in`; this is a resolved environment, not a model-quality claim.

12 September review found that Onur uses macOS ARM64 (PR #11/#14), contrary to
the original lock's platform assumption. Both locks now use universal resolution
with published wheel/source hashes, covering macOS too. Hash availability is not
runtime evidence: the commands below validate the actual host; Linux ARM64/Pi
execution remains KAN-53/44. CI executes Linux x86_64, Windows and macOS runners.

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

The lock explicitly pins pip. A distributor can change the `ensurepip` bundle
without changing Python's version, so the interpreter pin alone does not pin pip.
Use `requirements-ml.lock` instead of `requirements.lock` for ML work. Never
install unlocked extras afterward and call the resulting environment locked.

## Regenerating the locks

Generation tool used in this review: uv 0.12.13. Run from the repository root:

```sh
uv pip compile requirements.in --upgrade --python-version 3.14.7 --universal --generate-hashes --no-emit-index-url -o requirements.lock
uv pip compile requirements-ml.in --upgrade --python-version 3.14.7 --universal --generate-hashes --no-emit-index-url -o requirements-ml.lock
```

Review changed versions/hashes, then repeat clean installs and `pip check` on
team platforms. Hash locks do not prove arbitrary source builds or Pi support.
Do not commit downloaded wheels or virtual environments.

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

- Model training results and production artifact compatibility beyond the
  current loader. The ML environment is now locked using R1's selected versions;
  that does not approve a trained artifact or complete KAN-9.
- ARM64 runtime validation, per the section above.
- `telemetry` and `measure` are absent from `[tool.setuptools.packages.find]`
  because they contain no Python package yet. KAN-38 adds `telemetry`.

## 12 September Linux follow-up

The earlier Windows evidence above is retained as historical evidence for the
original PR. The review adds macOS coverage, an explicit pip pin and an ML lock.
Clean installation and exact results are recorded in the PR review after execution.
System Python on CachyOS remains 3.14.6; the project uses managed Python 3.14.7.

Measured on CachyOS x86_64, Python 3.14.7: fresh venv installed the full ML lock
with pip `--require-hashes`, then editable project with `--no-deps
--no-build-isolation`; `pip check` passed and all 21 branch unit tests passed.
Combined candidate code ran 123 tests including real RF round-trip without skips.
Raw local logs are outside Git in review-audit/. CI validates hosted platforms.
