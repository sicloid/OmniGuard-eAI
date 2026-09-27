"""Build CICIoT2023 benign windows with device-disjoint MAC-derived groups."""

import argparse
import json
from pathlib import Path

from data.audit import summarize_pcap
from data.samplepack.build import BENIGN_LABEL, CaptureSpec, build_sample_pack

SOURCE_URL = "https://www.unb.ca/cic/datasets/iotdataset-2023.html"
LICENSE = "CIC dataset terms; research use under the owner's granted access"
LAN = "192.168.137.0/24"


def device_map(path: Path, *, lan: str = LAN) -> tuple[dict[str, str], dict[str, list[str]]]:
    summary = summarize_pcap(path, [lan], top=0)
    owners: dict[str, set[str]] = {}
    for mac, addresses in summary.lan_source_mac_ip_bindings.items():
        for address in addresses:
            owners.setdefault(address, set()).add(mac)
    ambiguous = {address: sorted(macs) for address, macs in owners.items() if len(macs) != 1}
    devices = {address: next(iter(macs)) for address, macs in owners.items() if len(macs) == 1}
    if not devices:
        raise ValueError(f"{path.name}: no unambiguous LAN source MAC/IP bindings")
    return devices, ambiguous


def build(root: Path, output: Path, names: list[str]) -> dict:
    specs = []
    mapping_report = []
    for name in names:
        path = root / name
        devices, ambiguous = device_map(path)
        mapping_report.append(
            {
                "capture": name,
                "device_count": len(set(devices.values())),
                "mapped_ip_count": len(devices),
                "ambiguous_ip_to_macs": ambiguous,
            }
        )
        specs.append(
            CaptureSpec(
                group_id=f"CICIoT2023-{path.stem}",
                pcap=path,
                lan_cidrs=(LAN,),
                devices=devices,
                source_url=SOURCE_URL,
                license=LICENSE,
                declared_label=BENIGN_LABEL,
                notes=(
                    "Declared benign by the dataset folder. Device identity is the observed "
                    "Ethernet source MAC; ambiguous IP ownership is excluded."
                ),
                group_by_device=True,
            )
        )
    manifest = build_sample_pack(specs, output)
    (output / "device_mapping.json").write_text(
        json.dumps(mapping_report, indent=2, sort_keys=True) + "\n"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--captures", nargs="+", required=True)
    args = parser.parse_args()
    result = build(args.root, args.out, args.captures)
    print(json.dumps(result["totals"], sort_keys=True))


if __name__ == "__main__":
    main()
