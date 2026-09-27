# CICIoT2023 external benign generalization

The raw 116 GB CICIoT2023 PCAP inventory produced 322,393 benign five-second
windows from 59 stable device identities. The split in
`model/ciciot_benign_spec.json` was committed before either role was scored:
48 devices are development evidence and 11 devices are a one-shot holdout.
A MAC stays in one role across all four source PCAPs.

The frozen KAN-19 Random Forest, threshold 0.9798815486832 and DevicePolicy
N=2/300 s do not generalize to this source:

| Role | Devices | Windows | Window FPR | False quarantines | Quarantines / observed device-hour |
|---|---:|---:|---:|---:|---:|
| Development (KAN-65) | 48 | 243,559 | 19.55% | 1,710 | 5.06 |
| One-shot holdout (KAN-70) | 11 | 78,834 | 21.97% | 532 | 4.86 |

These are external-source results, not deployment prevalence estimates. They show
that strong IoT-23 validation and malware holdout results did not protect against
device/domain shift. The holdout result is reported unchanged and must not be used
to tune a replacement model. Replacement development may use only the declared
CICIoT development devices; the ongoing Raspberry Pi capture supplies fresh
post-selection benign evidence.

## Existing KAN-67 candidate on development devices

The previously trained regularized ExtraTrees candidate was then reproduced on the
same 48 development devices. A preliminary development-only probe had already been
seen, so this is explicitly reproducibility evidence rather than blind confirmation.
The candidate reduced window FPR to 0.957%, false quarantines to 65, and false
quarantines per observed device-hour to 0.192. It was not scored on the consumed
CICIoT holdout. Runtime adoption remains gated on fresh Pi evidence and G8 regression.
