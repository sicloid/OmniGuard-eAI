"""Build a separately reported CICIoT2023 EGRESS attack stress pack."""

import argparse
import json
from pathlib import Path

from data.ciciot2023.build_benign import LAN, LICENSE, SOURCE_URL, device_map
from data.samplepack.build import MALICIOUS_LABEL, CaptureSpec, build_sample_pack


def build(path: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    devices, ambiguous = device_map(path)
    spec = CaptureSpec(
        group_id=f"CICIoT2023-{path.parent.name}-{path.stem}",
        pcap=path,
        lan_cidrs=(LAN,),
        devices=devices,
        source_url=SOURCE_URL,
        license=LICENSE,
        declared_label=MALICIOUS_LABEL,
        notes=(
            "Folder-level attack declaration used as a transfer stress label. It is not "
            "flow-level ground truth; results stay separate from IoT-23. Ambiguous IP/MAC "
            "ownership is excluded."
        ),
        group_by_device=True,
    )
    manifest = build_sample_pack([spec], output)
    (output / "device_mapping.json").write_text(
        json.dumps(
            {
                "capture": path.name,
                "mapped_ip_count": len(devices),
                "device_count": len(set(devices.values())),
                "ambiguous_ip_to_macs": ambiguous,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcap", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.pcap, args.out)["totals"], sort_keys=True))


if __name__ == "__main__":
    main()
