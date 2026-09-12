"""ADR-0003 canonical JSON encoding.

One encoding is used both on the wire and as the `event_id` derivation input.
Using a different encoding in either place would make identities depend on the
producing platform, so every caller goes through `canonical_bytes`.
"""

import json


class CanonicalError(ValueError):
    """The document cannot be encoded deterministically."""


def canonical_bytes(document: object) -> bytes:
    """Encode as UTF-8 JSON with sorted keys, compact separators and no NaN.

    `allow_nan=False` rejects NaN and infinities rather than emitting the
    non-standard literals that a strict consumer would refuse to parse.
    """
    try:
        text = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CanonicalError(f"not canonically encodable: {exc}") from exc
    return text.encode("utf-8")
