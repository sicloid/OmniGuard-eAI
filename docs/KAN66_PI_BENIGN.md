# KAN-66 — controlled benign Raspberry Pi capture

## Hardware boundary

The capture host is the owner's Raspberry Pi 5 running Raspberry Pi OS. It is
connected over Wi-Fi and Tailscale. The available supply does not provide the
official 27 W operating envelope. The fan has a separate power connection and
runs continuously at 100%. The project therefore does not use this capture to
claim full-power Raspberry Pi latency, throughput or energy performance.

Temperature is retained as environment provenance. Stable or low temperature
is expected with the externally powered fan, but temperature alone does not
validate the run. The acceptance guard requires `get_throttled` to be `0x0`
both before and after capture. A nonzero or missing value invalidates Pi timing
claims. Functional capture and benign-model evidence remain usable only when
their own manifest checks pass.

## Capture contract

The accepted run must:

- last at least 3,600 seconds;
- use an explicit BPF filter for the Pi's captured WLAN address;
- contain at least one IPv4 or IPv6 frame for that device;
- finish `tcpdump` successfully and record zero/nonzero kernel statistics
  without rewriting them;
- pin the PCAP, scenario log and manifest with SHA-256;
- record boot ID, kernel, interface/address, start/end UTC, load, temperature
  and throttling observations;
- contain only owner-controlled benign activity.

The host pack keeps the Pi `manifest.json` byte-for-byte as
`source_manifest.json`. `pack_provenance.json` separately records the source
directory and the SHA-256 of those original bytes. The scorer verifies that
binding before loading either model, so host-side normalization cannot silently
rewrite device provenance.

The first full pilot retained 6,976 packets with zero kernel drops, but its
manifest failed because a temperature value containing an apostrophe was
embedded as Python source. That run is excluded. Manifest serialization now
passes string values through environment variables and `os.environ`; no shell
quoted value is emitted as Python syntax. The clean run directory declared
before scoring is `omniguard-benign-v3-20260928`.

## Accepted result

The declared run completed for exactly 3,600 seconds on Raspberry Pi 5 ARM64.
It retained 4,749 IPv4 device frames, exited with `tcpdump_exit=0`, and recorded
`throttled=0x0` both before and after capture. The raw PCAP SHA-256 is
`5400cd3aef6f206b5d304909bcacbcd5feb8507f71c1a206251e8cc52acb59b9`.

The shared extractor produced 328 benign windows. Frozen KAN-19 marked 246
anomalous (75.00% window FPR), caused 10 false quarantine episodes and blocked
2,980 seconds. The ExtraTrees candidate marked zero anomalous windows and
caused no quarantine in this run. Because observed traffic occupied only
0.4556 device-hours, its zero-event rule-of-three upper bound is still 6.58
false quarantines per observed device-hour. See the
[hash-pinned evidence](evidence/KAN66_PI_2026-09-28/README.md).

## Evaluation boundary

After validation, the raw PCAP is converted with the same five-second feature
extractor used by training and runtime. The frozen KAN-19 profile and the
ExtraTrees candidate are replayed through the same `DevicePolicy` with N=2 and
a 300-second lease. The report includes window FPR, false quarantine episodes,
observed/span device-hour rates, blocked time, rejection/reset counters and a
rule-of-three upper bound when no quarantine is observed.

This is one device-hour from one device. It can expose a deployment failure and
compare the two pinned profiles on fresh owner traffic; it cannot establish a
population-wide benign false-positive rate.
