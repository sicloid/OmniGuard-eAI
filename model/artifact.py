"""KAN-9 model artifact contract: strict metadata and fail-fast checks before loading.

`model.joblib` is a pickle; deserializing it executes code. These checks do not make
an untrusted file safe. They ensure that a trusted, locally produced artifact is the
one pinned by the deployment and matches the runtime before any byte is unpickled.
"""

import hashlib
import io
import json
import platform
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import BinaryIO

from core.schema import SCHEMA_VERSION, nonempty, probability

META_FORMAT = "omniguard-model-meta/1"
MODEL_FILENAME = "model.joblib"
META_FILENAME = "model.meta.json"
WINDOW_SECONDS = 5
WINDOW_SEMANTICS = "half-open-epoch-aligned"

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ArtifactError(ValueError):
    """No model was loaded; callers must not fall back to a default decision."""


class ArtifactFormatError(ArtifactError):
    """Metadata or a supplied argument is malformed."""


class ArtifactCompatibilityError(ArtifactError):
    """Well-formed metadata that does not match this runtime or feature catalog."""


class ArtifactIntegrityError(ArtifactError):
    """Artifact files are missing or are not the pinned bytes."""


class ArtifactLoadError(ArtifactError):
    """A verified artifact could not be deserialized; no model is available."""


@dataclass(frozen=True)
class RuntimeEnvironment:
    python_version: str
    sklearn_version: str | None
    numpy_version: str | None


def _package_version(name: str) -> str | None:
    try:
        return importlib_metadata.version(name)
    except importlib_metadata.PackageNotFoundError:
        return None


def current_environment() -> RuntimeEnvironment:
    """Read installed versions without importing (and so without initializing) the ML stack."""
    return RuntimeEnvironment(
        platform.python_version(), _package_version("scikit-learn"), _package_version("numpy")
    )


def _sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ArtifactFormatError(f"{field} must be 64 lowercase hex characters")


@dataclass(frozen=True)
class ArtifactMetadata:
    meta_format: str
    model_id: str
    model_version: str
    schema_version: str
    feature_schema_version: str
    feature_order: tuple[str, ...]
    window_seconds: int
    window_semantics: str
    threshold: float
    model_sha256: str
    training_manifest_sha256: str
    python_version: str
    sklearn_version: str
    numpy_version: str

    def __post_init__(self) -> None:
        try:
            self._validate()
        except ArtifactFormatError:
            raise
        except ValueError as exc:
            raise ArtifactFormatError(str(exc)) from exc

    def _validate(self) -> None:
        if self.meta_format != META_FORMAT:
            raise ArtifactFormatError(f"meta_format must be {META_FORMAT}")
        for name in (
            "model_id",
            "model_version",
            "schema_version",
            "feature_schema_version",
            "window_semantics",
            "python_version",
            "sklearn_version",
            "numpy_version",
        ):
            nonempty(getattr(self, name), name)
        if type(self.feature_order) is not tuple or not self.feature_order:
            raise ArtifactFormatError("feature_order must be a nonempty tuple")
        for name in self.feature_order:
            nonempty(name, "feature name")
        if len(set(self.feature_order)) != len(self.feature_order):
            raise ArtifactFormatError("duplicate feature name")
        if type(self.window_seconds) is not int or self.window_seconds <= 0:
            raise ArtifactFormatError("window_seconds must be a positive integer")
        probability(self.threshold, "threshold")
        _sha256(self.model_sha256, "model_sha256")
        _sha256(self.training_manifest_sha256, "training_manifest_sha256")

    def to_json(self) -> str:
        document = asdict(self) | {"feature_order": list(self.feature_order)}
        return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"


_FIELDS = frozenset(f.name for f in fields(ArtifactMetadata))


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ArtifactFormatError("duplicate key in metadata")
    return dict(pairs)


def _reject_constant(name: str) -> None:
    raise ArtifactFormatError(f"nonfinite constant {name} in metadata")


def parse_metadata(text: str) -> ArtifactMetadata:
    try:
        document = json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise ArtifactFormatError(f"metadata is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ArtifactFormatError("metadata must be a JSON object")
    if missing := sorted(_FIELDS - document.keys()):
        raise ArtifactFormatError(f"missing metadata fields: {', '.join(missing)}")
    if unknown := sorted(document.keys() - _FIELDS):
        raise ArtifactFormatError(f"unknown metadata fields: {', '.join(unknown)}")
    if not isinstance(document["feature_order"], list):
        raise ArtifactFormatError("feature_order must be a JSON array")
    return ArtifactMetadata(**document | {"feature_order": tuple(document["feature_order"])})


def check_compatibility(
    meta: ArtifactMetadata,
    env: RuntimeEnvironment,
    *,
    feature_schema_version: str | None = None,
    feature_order: tuple[str, ...] | None = None,
) -> None:
    """Raise one error listing every mismatch; return None only when all checks pass.

    scikit-learn and numpy must match exactly: scikit-learn supports unpickling only
    with the version that saved the model. Python must match major.minor.
    """
    problems = []
    if meta.schema_version != SCHEMA_VERSION:
        problems.append(f"schema_version {meta.schema_version} != runtime {SCHEMA_VERSION}")
    if meta.window_seconds != WINDOW_SECONDS or meta.window_semantics != WINDOW_SEMANTICS:
        problems.append(
            f"window {meta.window_seconds}s/{meta.window_semantics} != "
            f"runtime {WINDOW_SECONDS}s/{WINDOW_SEMANTICS}"
        )
    if meta.python_version.split(".")[:2] != env.python_version.split(".")[:2]:
        problems.append(f"Python {meta.python_version} != runtime {env.python_version}")
    for label, trained, installed in (
        ("scikit-learn", meta.sklearn_version, env.sklearn_version),
        ("numpy", meta.numpy_version, env.numpy_version),
    ):
        if trained != installed:
            problems.append(f"{label} {trained} != runtime {installed or 'not installed'}")
    if feature_schema_version is not None and meta.feature_schema_version != feature_schema_version:
        problems.append(
            f"feature_schema_version {meta.feature_schema_version} != "
            f"extractor {feature_schema_version}"
        )
    if feature_order is not None and meta.feature_order != feature_order:
        problems.append("feature_order differs from the extractor catalog")
    if problems:
        raise ArtifactCompatibilityError("; ".join(problems))


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ArtifactIntegrityError(f"cannot read artifact file {path.name}") from exc


def build_metadata(
    model_path: Path,
    *,
    model_id: str,
    model_version: str,
    feature_schema_version: str,
    feature_order: tuple[str, ...],
    threshold: float,
    training_manifest_sha256: str,
    env: RuntimeEnvironment | None = None,
) -> ArtifactMetadata:
    """Describe an already saved model file using the environment that produced it."""
    env = env or current_environment()
    return ArtifactMetadata(
        meta_format=META_FORMAT,
        model_id=model_id,
        model_version=model_version,
        schema_version=SCHEMA_VERSION,
        feature_schema_version=feature_schema_version,
        feature_order=feature_order,
        window_seconds=WINDOW_SECONDS,
        window_semantics=WINDOW_SEMANTICS,
        threshold=threshold,
        model_sha256=hashlib.sha256(_read(Path(model_path))).hexdigest(),
        training_manifest_sha256=training_manifest_sha256,
        python_version=env.python_version,
        sklearn_version=env.sklearn_version,
        numpy_version=env.numpy_version,
    )


def write_metadata(meta: ArtifactMetadata, artifact_dir: Path) -> Path:
    path = Path(artifact_dir) / META_FILENAME
    path.write_text(meta.to_json(), encoding="utf-8")
    return path


@dataclass(frozen=True)
class LoadedArtifact:
    metadata: ArtifactMetadata
    model: object


def _joblib_load(stream: BinaryIO) -> object:
    import joblib  # deferred: only needed once every check has passed

    return joblib.load(stream)


def load_model(
    artifact_dir: Path,
    *,
    expected_model_sha256: str,
    expected_metadata_sha256: str,
    env: RuntimeEnvironment | None = None,
    feature_schema_version: str | None = None,
    feature_order: tuple[str, ...] | None = None,
    deserialize: Callable[[BinaryIO], object] = _joblib_load,
) -> LoadedArtifact:
    """Load a pinned artifact, deserializing only bytes whose hash was just verified.

    Both expected hashes must come from trusted deployment configuration, not be
    recomputed from untrusted files at load time. The metadata hash binds threshold,
    feature order, environment and model identity to that trust anchor. Both files
    are read once; the verified bytes are the bytes parsed/deserialized.
    """
    _sha256(expected_model_sha256, "expected_model_sha256")
    _sha256(expected_metadata_sha256, "expected_metadata_sha256")
    artifact_dir = Path(artifact_dir)
    meta_bytes = _read(artifact_dir / META_FILENAME)
    if hashlib.sha256(meta_bytes).hexdigest() != expected_metadata_sha256:
        raise ArtifactIntegrityError("metadata bytes do not match the pinned SHA-256")
    try:
        meta_text = meta_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ArtifactFormatError("metadata is not UTF-8") from exc
    meta = parse_metadata(meta_text)
    if meta.model_sha256 != expected_model_sha256:
        raise ArtifactIntegrityError("metadata describes a different artifact than the pinned one")
    check_compatibility(
        meta,
        env or current_environment(),
        feature_schema_version=feature_schema_version,
        feature_order=feature_order,
    )
    data = _read(artifact_dir / MODEL_FILENAME)
    if hashlib.sha256(data).hexdigest() != expected_model_sha256:
        raise ArtifactIntegrityError("model bytes do not match the pinned SHA-256")
    try:
        model = deserialize(io.BytesIO(data))
    except Exception as exc:
        raise ArtifactLoadError("verified model could not be deserialized") from exc
    return LoadedArtifact(meta, model)
