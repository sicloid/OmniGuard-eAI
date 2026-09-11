import hashlib
import json
import platform
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from core.schema import SCHEMA_VERSION
from model.artifact import (
    META_FILENAME,
    MODEL_FILENAME,
    ArtifactCompatibilityError,
    ArtifactFormatError,
    ArtifactIntegrityError,
    ArtifactMetadata,
    RuntimeEnvironment,
    build_metadata,
    check_compatibility,
    current_environment,
    load_model,
    parse_metadata,
    write_metadata,
)

ENV = RuntimeEnvironment("3.14.7", "1.8.0", "2.3.4")
ORDER = ("pkt_count", "l3_bytes")
MODEL_BYTES = b"not-a-real-model: deserializer is injected in tests"
MODEL_SHA = hashlib.sha256(MODEL_BYTES).hexdigest()
MANIFEST_SHA = "a" * 64


def metadata(**changes) -> ArtifactMetadata:
    base = ArtifactMetadata(
        meta_format="omniguard-model-meta/1",
        model_id="rf-baseline",
        model_version="0.1.0",
        schema_version=SCHEMA_VERSION,
        feature_schema_version="features-1",
        feature_order=ORDER,
        window_seconds=5,
        window_semantics="half-open-epoch-aligned",
        threshold=0.5,
        model_sha256=MODEL_SHA,
        training_manifest_sha256=MANIFEST_SHA,
        python_version=ENV.python_version,
        sklearn_version=ENV.sklearn_version,
        numpy_version=ENV.numpy_version,
    )
    return replace(base, **changes)


def meta_dict(**changes) -> dict:
    return json.loads(metadata().to_json()) | changes


class MetadataParsingTests(unittest.TestCase):
    def test_round_trip_preserves_every_field(self):
        meta = metadata()
        self.assertEqual(parse_metadata(meta.to_json()), meta)

    def test_rejects_missing_and_unknown_keys(self):
        missing = meta_dict()
        del missing["threshold"]
        for document in (missing, meta_dict(extra="field")):
            with self.subTest(keys=sorted(document)), self.assertRaises(ArtifactFormatError):
                parse_metadata(json.dumps(document))

    def test_rejects_duplicate_keys_and_nonfinite_constants(self):
        text = metadata().to_json()
        duplicated = text.replace('"threshold": 0.5', '"threshold": 0.5, "threshold": 0.1')
        for document in (duplicated, text.replace("0.5", "NaN"), "[]", "{", ""):
            with self.subTest(document=document[:40]), self.assertRaises(ArtifactFormatError):
                parse_metadata(document)

    def test_rejects_invalid_field_values(self):
        for field, value in (
            ("meta_format", "omniguard-model-meta/2"),
            ("model_id", " "),
            ("feature_order", ["dup", "dup"]),
            ("feature_order", []),
            ("feature_order", "pkt_count"),
            ("threshold", 1.5),
            ("threshold", True),
            ("window_seconds", 5.0),
            ("window_seconds", True),
            ("model_sha256", MODEL_SHA.upper()),
            ("training_manifest_sha256", "abc"),
            ("sklearn_version", None),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ArtifactFormatError):
                parse_metadata(json.dumps(meta_dict(**{field: value})))


class CompatibilityTests(unittest.TestCase):
    def test_matching_environment_passes(self):
        check_compatibility(
            metadata(), ENV, feature_schema_version="features-1", feature_order=ORDER
        )

    def test_python_patch_release_is_compatible(self):
        check_compatibility(metadata(), replace(ENV, python_version="3.14.9"))

    def test_each_mismatch_is_rejected(self):
        for meta, env, kwargs in (
            (metadata(schema_version="0.1.0-draft"), ENV, {}),
            (metadata(window_seconds=10), ENV, {}),
            (metadata(window_semantics="sliding"), ENV, {}),
            (metadata(), replace(ENV, python_version="3.13.2"), {}),
            (metadata(), replace(ENV, sklearn_version="1.9.1"), {}),
            (metadata(), replace(ENV, sklearn_version=None), {}),
            (metadata(), replace(ENV, numpy_version="2.3.5"), {}),
            (metadata(), ENV, {"feature_schema_version": "features-2"}),
            (metadata(), ENV, {"feature_order": tuple(reversed(ORDER))}),
        ):
            with (
                self.subTest(meta=meta, env=env, kwargs=kwargs),
                self.assertRaises(ArtifactCompatibilityError),
            ):
                check_compatibility(meta, env, **kwargs)

    def test_error_lists_every_problem(self):
        env = replace(ENV, sklearn_version="1.9.1", numpy_version=None)
        with self.assertRaises(ArtifactCompatibilityError) as caught:
            check_compatibility(metadata(), env)
        self.assertIn("scikit-learn", str(caught.exception))
        self.assertIn("numpy", str(caught.exception))

    def test_current_environment_reports_running_interpreter(self):
        self.assertEqual(current_environment().python_version, platform.python_version())


class LoadModelTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        (self.dir / MODEL_FILENAME).write_bytes(MODEL_BYTES)
        write_metadata(metadata(), self.dir)
        self.calls = []

    def deserialize(self, stream):
        data = stream.read()
        self.calls.append(data)
        return {"model": data}

    def load(self, **kwargs):
        options = {"expected_model_sha256": MODEL_SHA, "env": ENV, "deserialize": self.deserialize}
        return load_model(self.dir, **options | kwargs)

    def test_loads_verified_bytes_after_all_checks(self):
        loaded = self.load(feature_schema_version="features-1", feature_order=ORDER)
        self.assertEqual(loaded.metadata, metadata())
        self.assertEqual(loaded.model, {"model": MODEL_BYTES})
        self.assertEqual(self.calls, [MODEL_BYTES])

    def test_tampered_model_bytes_are_never_deserialized(self):
        (self.dir / MODEL_FILENAME).write_bytes(MODEL_BYTES + b"!")
        with self.assertRaises(ArtifactIntegrityError):
            self.load()
        self.assertEqual(self.calls, [])

    def test_metadata_for_another_artifact_is_rejected(self):
        with self.assertRaises(ArtifactIntegrityError):
            self.load(expected_model_sha256="b" * 64)
        self.assertEqual(self.calls, [])

    def test_incompatible_environment_blocks_deserialization(self):
        with self.assertRaises(ArtifactCompatibilityError):
            self.load(env=replace(ENV, sklearn_version="1.9.1"))
        self.assertEqual(self.calls, [])

    def test_malformed_expected_hash_is_rejected(self):
        with self.assertRaises(ArtifactFormatError):
            self.load(expected_model_sha256=MODEL_SHA.upper())
        self.assertEqual(self.calls, [])

    def test_missing_files_raise_integrity_error(self):
        for name in (MODEL_FILENAME, META_FILENAME):
            with self.subTest(name=name):
                (self.dir / name).rename(self.dir / f"{name}.bak")
                with self.assertRaises(ArtifactIntegrityError):
                    self.load()
                (self.dir / f"{name}.bak").rename(self.dir / name)
        self.assertEqual(self.calls, [])


class BuildMetadataTests(unittest.TestCase):
    def test_build_hashes_model_file_and_records_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / MODEL_FILENAME
            path.write_bytes(MODEL_BYTES)
            meta = build_metadata(
                path,
                env=ENV,
                model_id="rf-baseline",
                model_version="0.1.0",
                feature_schema_version="features-1",
                feature_order=ORDER,
                threshold=0.5,
                training_manifest_sha256=MANIFEST_SHA,
            )
        self.assertEqual(meta, metadata())

    def test_build_refuses_environment_without_ml_stack(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / MODEL_FILENAME
            path.write_bytes(MODEL_BYTES)
            with self.assertRaises(ArtifactFormatError):
                build_metadata(
                    path,
                    env=replace(ENV, numpy_version=None),
                    model_id="rf-baseline",
                    model_version="0.1.0",
                    feature_schema_version="features-1",
                    feature_order=ORDER,
                    threshold=0.5,
                    training_manifest_sha256=MANIFEST_SHA,
                )


if __name__ == "__main__":
    unittest.main()
