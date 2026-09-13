"""Reproducible IoT-23 sample pack: the six captures audited in KAN-13.

Each scenario is one group. LAN and device addresses come from the audit
(data/DATASET_AUDIT.md), not from guesswork; running the builder with a wrong LAN
would report traffic as OUTSIDE rather than invent directions.

Usage: python -m data.samplepack.iot23 --captures ~/omniguard-data/iot23 --out ~/omniguard-data/samplepack
"""

import argparse
import json
from pathlib import Path

from data.samplepack.build import CaptureSpec, build_sample_pack

BASE_URL = "https://mcfp.felk.cvut.cz/publicDatasets/IoT-23-Dataset/IndividualScenarios"
LICENSE = "IoT-23, Stratosphere Laboratory (CTU); confirm licence terms on the dataset page before publication"

SCENARIOS = (
    (
        "CTU-Honeypot-Capture-4-1",
        "2018-10-25-14-06-32-192.168.1.132.pcap",
        "192.168.1.0/24",
        "192.168.1.132",
        "honeypot-4-1",
        True,
    ),
    (
        "CTU-Honeypot-Capture-5-1",
        "2018-09-21-capture.pcap",
        "192.168.2.0/24",
        "192.168.2.3",
        "honeypot-5-1",
        True,
    ),
    (
        "CTU-Honeypot-Capture-7-1",
        "2019-07-03-16-41-09-192.168.1.158.pcap",
        "192.168.1.0/24",
        "192.168.1.158",
        "somfy-7-1",
        False,
    ),
    (
        "CTU-IoT-Malware-Capture-3-1",
        "2018-05-21_capture.pcap",
        "192.168.2.0/24",
        "192.168.2.5",
        "device-3-1",
        True,
    ),
    (
        "CTU-IoT-Malware-Capture-8-1",
        "2018-07-31-15-15-09-192.168.100.113.pcap",
        "192.168.100.0/24",
        "192.168.100.113",
        "device-8-1",
        True,
    ),
    (
        "CTU-IoT-Malware-Capture-34-1",
        "2018-12-21-15-50-14-192.168.1.195.pcap",
        "192.168.1.0/24",
        "192.168.1.195",
        "device-34-1",
        True,
    ),
)


def _has_fields_header(path: Path) -> bool:
    """A downloaded 404 page is a file too; require a real Zeek header."""
    if not path.is_file():
        return False
    with open(path, encoding="utf-8", errors="replace") as handle:
        return any(line.startswith("#fields") for _, line in zip(range(20), handle, strict=False))


def specs(captures_dir: Path) -> list[CaptureSpec]:
    out = []
    for scenario, pcap, lan, device_ip, device_id, has_labels in SCENARIOS:
        folder = captures_dir / scenario
        conn_log = folder / "conn.log.labeled"
        usable = has_labels and _has_fields_header(conn_log)
        out.append(
            CaptureSpec(
                group_id=scenario,
                pcap=folder / pcap,
                lan_cidrs=(lan,),
                devices={device_ip: device_id},
                source_url=f"{BASE_URL}/{scenario}/",
                license=LICENSE,
                conn_log=conn_log if usable else None,
                declared_label=None if usable else "benign",
                notes=""
                if usable
                else "Honeypot scenario; its conn log is empty, so the label comes from the dataset description.",
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--captures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_sample_pack(specs(args.captures), args.out)
    print(
        json.dumps({"totals": manifest["totals"], "sha256": manifest["windows_sha256"]}, indent=2)
    )
    for capture in manifest["captures"]:
        print(capture["group_id"], capture["windows"], capture["packets"])


if __name__ == "__main__":
    main()
