"""Validate and expose the frozen runtime profile without loading model bytes."""

import argparse
import json
import re
from pathlib import Path

PROFILE_FORMAT = "omniguard-runtime-profile/1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class RuntimeProfileError(ValueError):
    """The selected runtime profile is malformed or incomplete."""


def load_profile(path: Path) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("profile_format") != PROFILE_FORMAT:
        raise RuntimeProfileError("unexpected runtime profile format")
    if not isinstance(document.get("profile_id"), str) or not document["profile_id"]:
        raise RuntimeProfileError("profile_id must be a non-empty string")

    artifact = document.get("artifact")
    if not isinstance(artifact, dict):
        raise RuntimeProfileError("artifact must be an object")
    for field in ("model_id", "model_version"):
        if not isinstance(artifact.get(field), str) or not artifact[field]:
            raise RuntimeProfileError(f"artifact.{field} must be a non-empty string")
    for field in ("model_sha256", "metadata_sha256"):
        if not isinstance(artifact.get(field), str) or not _SHA256.fullmatch(artifact[field]):
            raise RuntimeProfileError(f"artifact.{field} must be a lowercase SHA-256")
    threshold = artifact.get("threshold")
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not 0 <= threshold <= 1
    ):
        raise RuntimeProfileError("artifact.threshold must be in [0, 1]")

    policy = document.get("policy")
    if not isinstance(policy, dict):
        raise RuntimeProfileError("policy must be an object")
    if not isinstance(policy.get("n"), int) or isinstance(policy["n"], bool) or policy["n"] < 1:
        raise RuntimeProfileError("policy.n must be a positive integer")
    lease = policy.get("lease_seconds")
    if not isinstance(lease, (int, float)) or isinstance(lease, bool) or lease <= 0:
        raise RuntimeProfileError("policy.lease_seconds must be positive")

    selection = document.get("selection")
    if not isinstance(selection, dict) or not selection.get("reason"):
        raise RuntimeProfileError("selection rationale is required")
    limitations = selection.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(item, str) and item for item in limitations)
    ):
        raise RuntimeProfileError("selection.limitations must be a non-empty string list")
    return document


def field(document: dict, name: str) -> str:
    values = {
        "model_id": document["artifact"]["model_id"],
        "model_version": document["artifact"]["model_version"],
        "model_sha256": document["artifact"]["model_sha256"],
        "metadata_sha256": document["artifact"]["metadata_sha256"],
        "threshold": document["artifact"]["threshold"],
        "n": document["policy"]["n"],
        "lease_seconds": document["policy"]["lease_seconds"],
    }
    if name not in values:
        raise RuntimeProfileError(f"unsupported runtime profile field: {name}")
    return str(values[name])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument(
        "field",
        choices=(
            "model_id",
            "model_version",
            "model_sha256",
            "metadata_sha256",
            "threshold",
            "n",
            "lease_seconds",
        ),
    )
    args = parser.parse_args()
    print(field(load_profile(args.profile), args.field))


if __name__ == "__main__":
    main()
