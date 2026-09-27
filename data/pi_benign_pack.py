"""Validate KAN-66 Pi evidence and build one benign device pack."""

import argparse
import hashlib
import ipaddress
import json
import re
from pathlib import Path

from data.ciciot2023.build_benign import device_map
from data.samplepack.build import BENIGN_LABEL, CaptureSpec, build_sample_pack

_IPV4_INTERFACE = re.compile(r"\b(\d+(?:\.\d+){3}/\d+)\b")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def build(evidence: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = evidence / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["run_directory"] = evidence.name
    if manifest.get("schema") != "omniguard.benign-pi-capture/1":
        raise ValueError("unexpected Pi capture manifest schema")
    if manifest.get("duration_seconds", 0) < 3600:
        raise ValueError("Pi evidence is shorter than one device-hour")
    if manifest.get("tcpdump_exit") != 0:
        raise ValueError("Pi capture did not exit successfully")
    if manifest.get("device_frames", 0) <= 0:
        raise ValueError("Pi evidence has no device frames")
    if (
        manifest.get("throttled_before") != "throttled=0x0"
        or manifest.get("throttled_after") != "throttled=0x0"
    ):
        raise ValueError("Pi capture has missing or nonzero throttling evidence")
    pcap = evidence / manifest["pcap"]
    if _sha256(pcap) != manifest.get("pcap_sha256"):
        raise ValueError("Pi capture hash mismatch")
    matched = _IPV4_INTERFACE.search(manifest.get("interface_address", ""))
    if not matched:
        raise ValueError("Pi interface address does not declare an IPv4 prefix")
    lan = str(ipaddress.ip_interface(matched.group(1)).network)
    devices, ambiguous = device_map(pcap, lan=lan)
    device_ip = manifest.get("device_ip")
    if device_ip not in devices:
        raise ValueError("captured device IP has no unambiguous source MAC")
    selected = {device_ip: devices[device_ip]}
    spec = CaptureSpec(
        group_id=f"Pi5-{manifest['boot_id']}",
        pcap=pcap,
        lan_cidrs=(lan,),
        devices=selected,
        source_url="owner-controlled Raspberry Pi KAN-66 capture",
        license="owner-generated evidence",
        declared_label=BENIGN_LABEL,
        notes=(
            "One-hour endpoint capture with explicit device-IP BPF; scripted scenarios "
            "and power/thermal provenance are pinned in the source manifest."
        ),
        group_by_device=True,
    )
    result = build_sample_pack([spec], output)
    (output / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    (output / "device_mapping.json").write_text(
        json.dumps(
            {"selected": selected, "ambiguous_ip_to_macs": ambiguous},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.evidence, args.out)["totals"], sort_keys=True))


if __name__ == "__main__":
    main()
