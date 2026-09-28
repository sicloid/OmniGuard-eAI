# KAN-66/KAN-69 fresh Pi benign evidence

The accepted source is the owner-controlled Raspberry Pi 5 capture directory
`omniguard-benign-v3-20260928`. The raw PCAP stays outside Git. Its SHA-256 is
`5400cd3aef6f206b5d304909bcacbcd5feb8507f71c1a206251e8cc52acb59b9`.

The capture lasted exactly 3,600 seconds, retained 4,749 IPv4 device frames,
finished with `tcpdump_exit=0`, and recorded `throttled=0x0` before and after.
The Pi used the available non-27 W supply and an externally powered fan fixed at
100%, so this is functional/fresh-benign evidence rather than a performance or
energy benchmark.

The same extractor produced 328 benign five-second windows. With N=2 and a
300-second lease:

| Profile | Anomalous windows | Window FPR | False quarantines | Blocked seconds |
|---|---:|---:|---:|---:|
| Frozen KAN-19 | 246 / 328 | 75.00% | 10 | 2,980 |
| ExtraTrees candidate | 0 / 328 | 0.00% | 0 | 0 |

The candidate's zero is not zero risk. Only 0.4556 observed device-hours were
present across the one-hour span; the rule-of-three upper bound is 6.58 false
quarantines per observed device-hour. The runtime decision also considers the
IoT-23 validation, CICIoT device-disjoint benign evaluation, CIC Backdoor
transfer stress and hash-pinned G8 results. The candidate is selected only for
the bounded competition/demo profile, with its 6.41% Backdoor stress recall
reported as a material limitation.

`source-manifest.json` is the exact Pi manifest. `pack-provenance.json` binds
those source bytes to the generated pack. `comparison.json` is the immutable
two-profile scorer output; its adjacent checksum pins the result.
