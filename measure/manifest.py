"""The versioned record of one measurement run: frozen at the start, closed at the end.

R3 is accountable for this format and for writing it (KAN-42, 12 September 2026). The
values, however, come from three roles, and the manifest says so per field instead of
leaving a reader to guess whether a blank means "zero" or "nobody supplied it":

- **R1 (Onur)** — dataset and model provenance: capture and parent-capture hashes, the
  split manifest hash, the model artifact SHA-256 and the label version.
- **R2 (Şükrü)** — the run's relationship to the machine and the network: boot and host
  clock mapping, `t0`, and sink/forwarding evidence.
- **R3 (Gabriel)** — the format, the environment, the measured figures, and writing it.

Two rules this file enforces rather than documents:

- **The configuration is frozen before the run.** After `freeze()`, changing it raises.
  A configuration edited while the run is in flight describes a run that never happened.
- **A failed or partial run is kept.** `freeze()` writes the opening document
  immediately, so a process that dies mid-run leaves a manifest marked `incomplete`
  rather than no manifest at all. Nothing here deletes a run.
"""

import json
import os
import platform
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from measure.clocks import Clock, UnixInstant

MANIFEST_FORMAT = "omniguard-experiment-manifest/1"
FILENAME = "manifest.json"

INCOMPLETE, COMPLETED, FAILED = "incomplete", "completed", "failed"


class ManifestError(Exception):
    """The manifest would have recorded something untrue."""


@dataclass
class ProvenanceFromR1:
    """Dataset and model identity. Supplied by R1; None means not supplied."""

    sample_pack_sha256: str | None = None
    windows_sha256: str | None = None
    split_manifest_sha256: str | None = None
    model_sha256: str | None = None
    model_meta_sha256: str | None = None
    feature_schema_version: str | None = None
    label_version: str | None = None


@dataclass
class ProvenanceFromR2:
    """How the run maps onto the machine and the wire. Supplied by R2."""

    host_id: str | None = None
    boot_id: str | None = None
    boot_started_at: float | None = None
    monotonic_to_unix_offset: float | None = None
    t0_unix: float | None = None
    sink_evidence: str | None = None


def _pending(section) -> list[str]:
    return sorted(name for name, value in vars(section).items() if value is None)


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
    _frozen: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _started: UnixInstant | None = field(default=None, init=False)

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
        """Write the opening document and refuse further configuration changes."""
        if self._frozen:
            raise ManifestError("this run is already frozen")
        self._started = self.clock.now()
        # Copy so a later mutation of the caller's dict cannot rewrite a frozen run.
        self.config = json.loads(json.dumps(self.config, sort_keys=True))
        self._frozen = True
        self._write(self._document(status=INCOMPLETE, outcome=None, measurements=None))
        return self.path

    def set_config(self, config: dict) -> None:
        if self._frozen:
            raise ManifestError("the configuration is frozen; a changed config is a different run")
        self.config = config

    def close(self, *, measurements: dict, status: str = COMPLETED, outcome: dict | None = None):
        """Write the final document. A failed run is closed as failed, never removed."""
        if not self._frozen:
            raise ManifestError("freeze the run before closing it")
        if self._closed:
            raise ManifestError("this run is already closed")
        if status not in (COMPLETED, FAILED):
            raise ManifestError(f"status must be {COMPLETED} or {FAILED}, not {status!r}")
        self._closed = True
        self._write(self._document(status=status, outcome=outcome, measurements=measurements))
        return self.path

    def _document(self, *, status: str, outcome: dict | None, measurements: dict | None) -> dict:
        return {
            "manifest_format": MANIFEST_FORMAT,
            "run_id": self.run_id,
            "status": status,
            "started_at_unix": None if self._started is None else self._started.seconds,
            "closed_at_unix": self.clock.now().seconds if status != INCOMPLETE else None,
            "environment": self.environment(),
            "config": self.config,
            "provenance": {
                "r1": asdict(self.r1),
                "r2": asdict(self.r2),
                # Named so a reader never has to infer that a null was a measurement.
                "not_supplied": {"r1": _pending(self.r1), "r2": _pending(self.r2)},
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
    return json.loads((Path(directory) / FILENAME).read_text(encoding="utf-8"))
