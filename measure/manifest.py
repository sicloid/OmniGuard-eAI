"""The versioned record of one measurement run: frozen at the start, closed at the end.

R3 is accountable for this format and for writing it (KAN-42, 12 September 2026). The
values, however, come from three roles, and the manifest says so per field instead of
leaving a reader to guess whether a blank means "zero" or "nobody supplied it":

- **R1 (Onur)** — dataset and model provenance: the pack manifest hash (which itself
  pins every capture hash), the split manifest hash, the model and metadata hashes, the
  frozen threshold policy, and which data role the run was allowed to touch.
- **R2 (Şükrü)** — the run's relationship to the machine and the network: boot and host
  clock mapping, `t0`, and sink/forwarding evidence.
- **R3 (Gabriel)** — the format, the environment, the measured figures, and writing it.

Three rules this file enforces rather than documents:

- **The run is sealed before it starts.** `freeze()` takes a deep snapshot of the
  configuration and pre-run provenance, and refuses later changes to either —
  whether by editing a nested value, replacing the whole attribute, or calling
  `set_config`. What is published is the snapshot, not whatever the caller holds now.
  A configuration or a provenance hash edited while the run is in flight describes a
  run that never happened, and ADR-0004 decision 7b requires those hashes recorded
  *before* a holdout run rather than alongside its results. R2's actual `t0` and
  sink result are the only post-run observations; `close()` accepts them with the
  same run ID. Format `/2` distinguishes this timing from historical `/1` records.
  7b's other half — N and
  the lease — is checked in the sealed config by the same rule, so a `holdout` run
  cannot publish an empty `holdout_preconditions_unmet` while recording no policy.
- **A run directory belongs to one run.** `freeze()` claims `manifest.json` with an
  exclusive create, so a second run pointed at the same directory fails there instead
  of replacing the first run's evidence. Only the run that claimed it may close it.
- **A failed or partial run is kept.** `freeze()` writes the opening document
  immediately, so a process that dies mid-run leaves a manifest marked `incomplete`
  rather than no manifest at all. Nothing here deletes a run. `_frozen` and `_closed`
  are set only once the document is actually on disk, so a write that fails can be
  retried instead of leaving the run permanently unclosable.
"""

import json
import os
import platform
import re
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from math import isfinite
from pathlib import Path

from measure.clocks import Clock, UnixInstant

MANIFEST_FORMAT = "omniguard-experiment-manifest/2"
FILENAME = "manifest.json"

INCOMPLETE, COMPLETED, FAILED = "incomplete", "completed", "failed"

# ADR-0004 decision 7 separates what a run is allowed to read. A run that does not say
# which of the three it was cannot be told apart from one that quietly used the holdout.
DATA_ROLES = ("development", "holdout", "external_transfer")

SHA256 = re.compile(r"^[0-9a-f]{64}$")

# Attributes that describe *which* run this is. Sealed together at freeze time.
SEALED = frozenset({"run_id", "directory", "config", "clock", "r1", "r2"})


class ManifestError(Exception):
    """The manifest would have recorded something untrue."""


def _hashes(section) -> None:
    """Reject anything that is not a full SHA-256, so a truncated copy is not published.

    A hash shortened for a report (`d30725a9…`) identifies nothing, and publishing it
    beside real ones invites a reader to treat it as provenance.
    """
    for name, value in vars(section).items():
        if name.endswith("_sha256") and value is not None and not SHA256.match(str(value)):
            raise ManifestError(
                f"{name} must be 64 lowercase hex characters or None, not {value!r}"
            )


@dataclass
class ProvenanceFromR1:
    """Dataset and model identity. Supplied by R1; None means not supplied.

    Field names follow what R1's merged runners already write, so the same bytes are
    not published under two names. The mapping, agreed on this PR's review:

    | here | R1 writes it as |
    |---|---|
    | `pack_manifest_sha256` | `PackProvenance.manifest_sha256` |
    | `windows_sha256` | `windows_sha256` |
    | `split_manifest_sha256` | `training_manifest_sha256` (hash of `split.manifest.json`) |
    | `model_sha256` | `model_sha256` |
    | `model_meta_sha256` | `metadata_sha256` (exact `model.meta.json` bytes) |
    | `threshold_policy_sha256` | the KAN-19 frozen operating policy hash |
    | `holdout_selection_sha256` | hash of `data/holdout/selection.json` |

    There is no capture-hash field: the pack manifest already pins every `pcap_sha256`
    and `conn_log_sha256`, so a second copy here could only disagree with it.

    `label_rule_version` is R1's explicit version for the window-label rule, carried in
    a versioned pack-manifest update. Until R1 supplies one it stays absent; it is not
    derived here, because a hash invented at this end would name a rule R1 never
    published.

    N and the lease are policy parameters rather than provenance, so they are not
    fields here. They live in the sealed `config` under `POLICY_CONFIG_KEY`, and a
    holdout run that does not record them is reported as unmet exactly like a missing
    hash — decision 7b asks for both halves.
    """

    pack_manifest_sha256: str | None = None
    windows_sha256: str | None = None
    split_manifest_sha256: str | None = None
    model_sha256: str | None = None
    model_meta_sha256: str | None = None
    threshold_policy_sha256: str | None = None
    holdout_selection_sha256: str | None = None
    feature_schema_version: str | None = None
    label_rule_version: str | None = None
    data_role: str | None = None

    def __post_init__(self) -> None:
        _hashes(self)
        if self.data_role is not None and self.data_role not in DATA_ROLES:
            raise ManifestError(f"data_role must be one of {DATA_ROLES} or None")


# What ADR-0004 decision 7b requires from R1 before the untouched holdout is scored.
HOLDOUT_PRECONDITIONS = (
    "feature_schema_version",
    "model_sha256",
    "model_meta_sha256",
    "threshold_policy_sha256",
    "pack_manifest_sha256",
    "holdout_selection_sha256",
)

# Decision 7b also lists N and the lease. They are policy parameters rather than
# provenance, so they live in the sealed configuration — under a versioned block, so
# that widening this contract later cannot change what an already written manifest was
# claiming. The names are `gateway.policy.DevicePolicy`'s own, so a recorded run can be
# compared with the policy that produced it without a translation step.
POLICY_CONFIG_KEY = "policy"
POLICY_CONFIG_VERSION = "omniguard-policy-config/1"


@dataclass
class ProvenanceFromR2:
    """R2 machine context sealed before the run; observations arrive at close."""

    host_id: str | None = None
    boot_id: str | None = None
    boot_started_at: float | None = None
    monotonic_to_unix_offset: float | None = None
    t0_unix: float | None = None
    sink_evidence: str | None = None

    def __post_init__(self) -> None:
        _hashes(self)


@dataclass(frozen=True)
class ObservedFromR2:
    """Actual replay/sink observations, recorded after the same run has executed."""

    run_id: str
    t0_unix: float | None = None
    sink_evidence: str | None = None

    def __post_init__(self) -> None:
        if self.t0_unix is not None and not _positive(self.t0_unix):
            raise ManifestError("observed t0_unix must be a positive finite Unix timestamp")
        if self.sink_evidence is not None and (
            not isinstance(self.sink_evidence, str) or not self.sink_evidence.strip()
        ):
            raise ManifestError("observed sink_evidence must be nonempty text")


def _pending(section: dict) -> list[str]:
    return sorted(name for name, value in section.items() if value is None)


def _positive(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
        and value > 0
    )


def _unmet_policy_config(config) -> list[str]:
    """Name the sealed policy parameters a holdout run did not record.

    A requirement only the prose enforces is not enforced: the R1 hashes were checked
    while N and the lease, which decision 7b lists beside them, were left to a sentence
    in a README. A value that is present but unusable — `n: 0`, a negative lease, a
    block written against a different version of this contract — counts as unrecorded,
    because it cannot describe the policy that actually ran.
    """
    block = config.get(POLICY_CONFIG_KEY) if isinstance(config, dict) else None
    if not isinstance(block, dict):
        return [f"config.{POLICY_CONFIG_KEY}"]

    unmet = []
    if block.get("policy_config_version") != POLICY_CONFIG_VERSION:
        unmet.append(f"config.{POLICY_CONFIG_KEY}.policy_config_version")
    n = block.get("n")
    # N counts windows, so a float is a different quantity, not a rounding question.
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        unmet.append(f"config.{POLICY_CONFIG_KEY}.n")
    lease = block.get("lease_seconds")
    if not _positive(lease):
        unmet.append(f"config.{POLICY_CONFIG_KEY}.lease_seconds")
    bound = block.get("max_lease")
    # Optional, but a bound that does not bound the lease it is recorded with is worse
    # than an absent one: it reads as a ceiling this run never had.
    if bound is not None and (not _positive(bound) or (_positive(lease) and bound < lease)):
        unmet.append(f"config.{POLICY_CONFIG_KEY}.max_lease")
    return unmet


def _unmet_holdout_preconditions(r1: dict, config) -> list[str]:
    """Name the 7b requirements a holdout run did not record, rather than read as clean."""
    if r1.get("data_role") != "holdout":
        return []
    missing = [name for name in HOLDOUT_PRECONDITIONS if r1.get(name) is None]
    return missing + _unmet_policy_config(config)


@dataclass
class ExperimentManifest:
    """One run. Create it, freeze it, then close it exactly once."""

    run_id: str
    directory: Path
    config: dict
    clock: Clock = field(default_factory=Clock)
    r1: ProvenanceFromR1 = field(default_factory=ProvenanceFromR1)
    r2: ProvenanceFromR2 = field(default_factory=ProvenanceFromR2)
    notes: str = ""
    _sealed: bool = field(default=False, init=False)
    _reserved: bool = field(default=False, init=False)
    _frozen: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _started: UnixInstant | None = field(default=None, init=False)
    _snapshot: dict | None = field(default=None, init=False, repr=False)

    def __setattr__(self, name: str, value) -> None:
        # Replacing the whole attribute would otherwise walk around set_config and the
        # snapshot both, which is how a frozen run silently became a different one.
        if name in SEALED and getattr(self, "_sealed", False):
            raise ManifestError(
                f"{name} is sealed for this run; a changed {name} describes a different run"
            )
        object.__setattr__(self, name, value)

    @property
    def path(self) -> Path:
        return Path(self.directory) / FILENAME

    def environment(self) -> dict:
        return {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or None,
            "cpu_count": os.cpu_count(),
        }

    def freeze(self) -> Path:
        """Seal the run, claim its directory, and write the opening document.

        Safe to call again only after a write failure: the snapshot and the claim are
        taken once, and `_frozen` is set after the document reaches disk.
        """
        if self._frozen:
            raise ManifestError("this run is already frozen")
        if not self._sealed:
            if self.r2.t0_unix is not None or self.r2.sink_evidence is not None:
                raise ManifestError(
                    "t0_unix and sink_evidence are observed during the run; "
                    "supply them to close(r2_observed=...)"
                )
            self._started = self.clock.now()
            # A deep copy, kept privately: nothing the caller still holds a reference to
            # can reach the published document, at any nesting depth.
            self._snapshot = {
                "config": json.loads(json.dumps(self.config, sort_keys=True)),
                "r1": asdict(self.r1),
                "r2": asdict(self.r2),
            }
            self._sealed = True
        self._reserve()
        self._write(
            self._document(status=INCOMPLETE, outcome=None, measurements=None, r2_observed=None)
        )
        self._frozen = True
        return self.path

    def set_config(self, config: dict) -> None:
        if self._sealed:
            raise ManifestError("the configuration is frozen; a changed config is a different run")
        self.config = config

    def close(
        self,
        *,
        measurements: dict,
        status: str = COMPLETED,
        outcome: dict | None = None,
        r2_observed: ObservedFromR2 | None = None,
    ):
        """Write the final document. A failed run is closed as failed, never removed."""
        if not self._frozen:
            raise ManifestError("freeze the run before closing it")
        if self._closed:
            raise ManifestError("this run is already closed")
        if status not in (COMPLETED, FAILED):
            raise ManifestError(f"status must be {COMPLETED} or {FAILED}, not {status!r}")
        if r2_observed is not None:
            if not isinstance(r2_observed, ObservedFromR2):
                raise ManifestError("r2_observed must be an ObservedFromR2 record")
            if r2_observed.run_id != self.run_id:
                raise ManifestError("R2 observations belong to a different run_id")
        self._assert_still_ours()
        closed_at_unix = self.clock.now().seconds
        if r2_observed is not None and r2_observed.t0_unix is not None:
            started_at_unix = self._started.seconds
            if not started_at_unix <= r2_observed.t0_unix <= closed_at_unix:
                raise ManifestError(
                    "observed t0_unix must fall within this run's open/close window"
                )
        self._write(
            self._document(
                status=status,
                outcome=outcome,
                measurements=measurements,
                r2_observed=r2_observed,
                closed_at_unix=closed_at_unix,
            )
        )
        self._closed = True
        return self.path

    def _reserve(self) -> None:
        """Claim manifest.json for this run with an exclusive create.

        Atomic replacement protects one write; it does not establish who owns the run
        record. Two runs pointed at one directory must fail here, before either has
        written anything, rather than at the end when the loser has already overwritten
        the winner's evidence.
        """
        if self._reserved:
            return
        directory = Path(self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            raise ManifestError(
                f"{self.path} already holds a run record; recorded runs are never "
                "overwritten. Give this run its own directory."
            ) from None
        self._reserved = True

    def _assert_still_ours(self) -> None:
        """Refuse to close over a record this run did not write."""
        try:
            existing = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise ManifestError(
                f"{self.path} no longer exists; this run cannot close a record it does not hold"
            ) from None
        except json.JSONDecodeError:
            raise ManifestError(
                f"{self.path} is not a document this run wrote; refusing to overwrite it"
            ) from None
        if existing.get("run_id") != self.run_id:
            raise ManifestError(
                f"{self.path} now records run {existing.get('run_id')!r}, not "
                f"{self.run_id!r}; closing would overwrite another run's evidence"
            )

    def _document(
        self,
        *,
        status: str,
        outcome: dict | None,
        measurements: dict | None,
        r2_observed: ObservedFromR2 | None,
        closed_at_unix: float | None = None,
    ) -> dict:
        snapshot = self._snapshot or {}
        r1, r2 = snapshot.get("r1", {}), dict(snapshot.get("r2", {}))
        if r2_observed is not None:
            r2["t0_unix"] = r2_observed.t0_unix
            r2["sink_evidence"] = r2_observed.sink_evidence
        return {
            "manifest_format": MANIFEST_FORMAT,
            "run_id": self.run_id,
            "status": status,
            "started_at_unix": None if self._started is None else self._started.seconds,
            "closed_at_unix": closed_at_unix,
            "environment": self.environment(),
            "config": snapshot.get("config"),
            "provenance": {
                "r1": r1,
                "r2": r2,
                "r2_observation_phase": (
                    "at-close"
                    if r2_observed is not None
                    and (r2_observed.t0_unix is not None or r2_observed.sink_evidence is not None)
                    else None
                ),
                # Named so a reader never has to infer that a null was a measurement.
                "not_supplied": {"r1": _pending(r1), "r2": _pending(r2)},
                # ADR-0004 7b, named rather than assumed satisfied by a holdout run.
                # Covers the sealed policy config as well as the R1 hashes: both halves
                # of 7b, or a holdout run can publish an empty list while recording
                # neither N nor the lease.
                "holdout_preconditions_unmet": _unmet_holdout_preconditions(
                    r1, snapshot.get("config")
                ),
            },
            "measurements": measurements,
            "outcome": outcome,
            "notes": self.notes or None,
        }

    def _write(self, document: dict) -> None:
        directory = Path(self.directory)
        directory.mkdir(parents=True, exist_ok=True)
        # Atomic replace: a crash mid-write must not leave half a manifest behind.
        handle, temporary = tempfile.mkstemp(dir=directory, prefix=".manifest-", suffix=".json")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
                json.dump(document, file, indent=2, sort_keys=True, ensure_ascii=False)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise


def read_manifest(directory: Path) -> dict:
    document = json.loads((Path(directory) / FILENAME).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("manifest_format") != MANIFEST_FORMAT:
        raise ManifestError(
            f"unsupported manifest_format: expected {MANIFEST_FORMAT}; "
            "historical /1 records require an explicit migration"
        )
    return document
