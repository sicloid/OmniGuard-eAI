"""Untouched IoT-23 malware holdout selection (ADR-0004, decision 7b).

The rule reads published metadata only: family, file size and whether a flow label
file exists. It never reads a capture or a model score. `selection.json` records the
candidates as they were fetched, the Lead-approved budget and tie-break, the
exclusions and the selection. `python -m data.holdout.selection --check` recomputes
the selection from the recorded candidates and fails if the recorded one differs, so
a hand edit cannot quietly change which captures are held out.

Nothing here downloads data. SHA-256 values are added to the manifest right after
download, before any audit, and the captures are scored once, after the freeze that
decision 7b describes.
"""

import argparse
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

MANIFEST = Path(__file__).with_name("selection.json")
PRIMARY_CAPTURE_PATTERN = r"\d{4}-\d{2}-\d{2}(?:-\d{2}-\d{2}-\d{2})?-\d{1,3}(?:\.\d{1,3}){3}\.pcap"
_PRIMARY = re.compile(PRIMARY_CAPTURE_PATTERN)
_NUMBER = re.compile(r"-(\d+)-(\d+)$")
SEEN, UNSEEN = "seen_family", "unseen_family"


class SelectionError(ValueError):
    """The recorded metadata cannot produce, or does not match, the fixed selection."""


@dataclass(frozen=True)
class Candidate:
    scenario: str
    family: str
    pcap: str
    pcap_bytes: int
    label_path: str | None
    label_bytes: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.scenario, str) or not _NUMBER.search(self.scenario):
            raise SelectionError(f"{self.scenario!r}: scenario id needs a numeric suffix")
        if not isinstance(self.family, str) or not self.family.strip():
            raise SelectionError(f"{self.scenario}: family must be nonempty text")
        if type(self.pcap_bytes) is not int or self.pcap_bytes <= 0:
            raise SelectionError(f"{self.scenario}: pcap_bytes must be a positive integer")
        if (self.label_path is None) != (self.label_bytes is None):
            raise SelectionError(f"{self.scenario}: label path and size must be given together")
        if self.label_bytes is not None and (
            type(self.label_bytes) is not int or self.label_bytes <= 0
        ):
            raise SelectionError(f"{self.scenario}: label_bytes must be a positive integer")

    @property
    def number(self) -> tuple[int, int]:
        major, minor = _NUMBER.search(self.scenario).groups()
        return int(major), int(minor)

    @property
    def download_bytes(self) -> int:
        return self.pcap_bytes + (self.label_bytes or 0)


@dataclass(frozen=True)
class Pick:
    role: str
    candidate: Candidate


def is_primary_capture(name: str) -> bool:
    """The full capture IoT-23 labels; excerpts such as `-only5000` or per-port cuts are not."""
    return _PRIMARY.fullmatch(name) is not None


def ineligibility(candidate: Candidate, excluded: Mapping[str, str]) -> str | None:
    if candidate.scenario in excluded:
        return excluded[candidate.scenario]
    if not is_primary_capture(candidate.pcap):
        return f"{candidate.pcap} is not a primary capture"
    if candidate.label_path is None:
        return "no published conn.log.labeled"
    return None


def select(
    candidates: Sequence[Candidate],
    *,
    seen_family: str,
    unseen_order: Sequence[str],
    unseen_needed: int,
    budget_bytes: int,
    excluded: Mapping[str, str],
    development_families: Iterable[str],
) -> tuple[list[Pick], list[str]]:
    """Apply decision 7b: smallest primary capture per family, in the fixed order.

    Size ties go to the smaller numeric scenario id. A family whose smallest capture
    does not fit the remaining budget is skipped for the next family in the order.
    """
    scenarios = [c.scenario for c in candidates]
    if len(scenarios) != len(set(scenarios)):
        raise SelectionError("duplicate scenario in candidates")
    if type(unseen_needed) is not int or unseen_needed < 1:
        raise SelectionError("unseen_needed must be a positive integer")
    if type(budget_bytes) is not int or budget_bytes <= 0:
        raise SelectionError("budget_bytes must be a positive integer")
    development = set(development_families)
    if seen_family not in development:
        raise SelectionError(f"{seen_family} is not a development family, so it is not 'seen'")
    if overlap := development & set(unseen_order):
        raise SelectionError(f"unseen order lists development families: {sorted(overlap)}")

    pool = [c for c in candidates if ineligibility(c, excluded) is None]

    def smallest(family: str) -> Candidate | None:
        members = [c for c in pool if c.family == family]
        return min(members, key=lambda c: (c.pcap_bytes, c.number)) if members else None

    notes: list[str] = []
    seen = smallest(seen_family)
    if seen is None or seen.download_bytes > budget_bytes:
        raise SelectionError(f"no eligible {seen_family} capture fits the budget")
    picks = [Pick(SEEN, seen)]
    spent = seen.download_bytes
    for family in unseen_order:
        if sum(p.role == UNSEEN for p in picks) == unseen_needed:
            break
        candidate = smallest(family)
        if candidate is None:
            notes.append(f"{family}: no eligible capture")
            continue
        if spent + candidate.download_bytes > budget_bytes:
            notes.append(
                f"{family}: {candidate.scenario} needs {candidate.download_bytes} bytes, "
                f"{budget_bytes - spent} remain"
            )
            continue
        picks.append(Pick(UNSEEN, candidate))
        spent += candidate.download_bytes
    if sum(p.role == UNSEEN for p in picks) < unseen_needed:
        raise SelectionError(f"fewer than {unseen_needed} unseen families fit the budget")
    return picks, notes


def _candidates(document: Mapping) -> list[Candidate]:
    fields = ("scenario", "family", "pcap", "pcap_bytes", "label_path", "label_bytes")
    return [Candidate(**{name: entry[name] for name in fields}) for entry in document["candidates"]]


def check(path: Path = MANIFEST) -> tuple[list[Pick], list[str]]:
    """Recompute the selection from the manifest's candidates and compare every recorded field."""
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        rule = document["rule"]
        if rule["primary_capture_pattern"] != PRIMARY_CAPTURE_PATTERN:
            raise SelectionError("manifest pattern differs from the code's primary-capture pattern")
        picks, notes = select(
            _candidates(document),
            seen_family=rule["seen_family"],
            unseen_order=rule["unseen_family_order"],
            unseen_needed=rule["unseen_families_needed"],
            budget_bytes=rule["budget_bytes"],
            excluded=document["excluded"],
            development_families=rule["development_scenarios"].values(),
        )
        recorded = document["selection"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, SelectionError):
            raise
        raise SelectionError(f"invalid holdout manifest: {exc}") from exc

    if len(recorded) != len(picks):
        raise SelectionError(
            f"manifest records {len(recorded)} captures, the rule selects {len(picks)}"
        )
    for entry, pick in zip(recorded, picks, strict=True):
        c = pick.candidate
        expected = {
            "role": pick.role,
            "scenario": c.scenario,
            "family": c.family,
            "pcap": c.pcap,
            "pcap_bytes": c.pcap_bytes,
            "label_path": c.label_path,
            "label_bytes": c.label_bytes,
            "download_bytes": c.download_bytes,
        }
        differing = sorted(k for k, v in expected.items() if entry.get(k) != v)
        if differing:
            raise SelectionError(f"{c.scenario}: recorded {differing} differ from the rule")
    total = sum(p.candidate.download_bytes for p in picks)
    if document.get("download_bytes_total") != total:
        raise SelectionError(f"download_bytes_total should be {total}")
    return picks, notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--check", action="store_true", help="verify the recorded selection")
    args = parser.parse_args()
    picks, notes = check(args.manifest)
    for pick in picks:
        c = pick.candidate
        print(f"{pick.role:14} {c.scenario:30} {c.family:14} {c.download_bytes:>14,d} bytes")
    total = sum(p.candidate.download_bytes for p in picks)
    print(f"{'total':60} {total:>14,d} bytes")
    for note in notes:
        print("skipped:", note)
    print("selection matches the rule" if args.check else "")


if __name__ == "__main__":
    main()
