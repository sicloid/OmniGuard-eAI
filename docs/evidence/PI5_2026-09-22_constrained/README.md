# Pi 5 ARM64: constrained-power functional run (22 September 2026)

This bundle records a real Raspberry Pi 5 run of `bash lab/run_docker.sh` at
Git commit `87f1024eb320ef21aa52f04288f048755fb7eb0a`. The command ran
inside `measure.pi_guard` with the predeclared maximum load of 0.5 per core and
temperature ceiling of 80 °C. The Pi ran Raspberry Pi OS (Debian 13), Linux
`6.18.50+rpt-rpi-2712` on `aarch64`; the host virtual environment used Python
3.14.7 and the lab container printed Python 3.11.2. These are separate Python
environments.

The Docker lab command exited 0. Its log records isolated namespaces with no
default routes, nftables apply/readback and expiry/release, UDS peer credentials,
UDP/TCP block and restore, and namespace cleanup. This is an **ARM64 functional
observation**. It is not a model accuracy, G8 real-model, G10 telemetry, or Pi
performance result.

The guard correctly returned `invalid (before_load_high)`: pre-run one-minute
load was 2.66796875 on four cores (0.667 per core), above the declared 0.5
limit. The after-run load was 3.2529296875; the command contributed to that
number. Temperature was 68.6 → 69.7 °C and firmware throttling bits were zero
at both samples. The 17.60 s wall interval in `verdict.json` is **not an accepted
benchmark**. Subsequent inspection found repeated USB `over-current change`
events on empty ports, which contaminate host load. The owner has no 27 W supply
available and has chosen to proceed with the existing power setup. Later
external fan power reduced temperature: the separate
`power_observation.json` sample reads 43.3 °C with no current throttling, while
the boot power profile reports 3000 mA, USB over-current detected, and load
6.2333984375 on four cores. That later reading is **not part of the guarded
run** and does not change its verdict. The fan is powered outside the Pi's fan
header, so the Pi's fan RPM sensor cannot verify its speed.

The raw guard samples and lab log are included here so a reviewer can verify
the distinction between successful function and invalid measurement. They are
copied byte-for-byte from the Pi's ignored `artifacts/` directory. The lab log
names additional temporary evidence paths on the Pi; this bundle does not claim
to contain those files.

| File | SHA-256 |
|---|---|
| `before.json` | `06d1d74767a06d3960d953f5be1ad9028a409176e11f38bdc0a1e701ad0192e6` |
| `after.json` | `4cfe0d0bd6c1dca4a581be5dbe8241265d4bca81b43c255` |
| `verdict.json` | `eb8fa7065834d1cf957bdec96e771b023cdfe5fdf13a1202885bdb991cf3ff03` |
| `run.log` | `e6380891f0e70890307fde8f090cb33f83deadb6fb195d1265d4bca81b43c255` |
| `power_observation.json` | `8b24278f47533106a4365deb051871a6149040133575fa197c60feda8fd20188` |

Recheck the bundle with `sha256sum -c SHA256SUMS`. KAN-46 accepts the guard's
correct invalidation behavior; KAN-53's separate ARM64 result and its G10
prerequisite remain subject to owner review. Do not tune the load ceiling after
seeing this run or present its timing as a Pi cost estimate.
