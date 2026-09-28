"""Hash and classify every locally downloaded CICIoT2023 raw capture."""

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def inventory(root: Path) -> dict:
    captures = []
    for path in sorted(root.rglob("*.pcap")):
        relative = path.relative_to(root)
        captures.append(
            {
                "path": relative.as_posix(),
                "attack_or_role": relative.parts[0],
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return {
        "schema": "omniguard.ciciot2023-local-inventory/1",
        "root_name": root.name,
        "capture_count": len(captures),
        "total_bytes": sum(row["bytes"] for row in captures),
        "captures": captures,
        "warning": (
            "Inventory is provenance, not authorization for training. Direction/topology and "
            "data role must be accepted before a capture enters an experiment."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"{result['capture_count']} captures, {result['total_bytes']} bytes")


if __name__ == "__main__":
    main()
