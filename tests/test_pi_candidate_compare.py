import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from model.pi_candidate_compare import score


class PiCandidateCompareTests(unittest.TestCase):
    def fixture(self, root: Path) -> tuple[Path, Path]:
        pack = root / "pack"
        pack.mkdir()
        source = b'{"device_ip":"192.168.4.7"}\n'
        (pack / "source_manifest.json").write_bytes(source)
        (pack / "pack_provenance.json").write_text(
            json.dumps(
                {
                    "source_directory": "declared-run",
                    "source_manifest_sha256": hashlib.sha256(source).hexdigest(),
                }
            )
        )
        spec = root / "spec.json"
        spec.write_text(
            json.dumps(
                {
                    "spec_version": "pi-benign-candidate-comparison/1",
                    "source": {"run_directory": "declared-run"},
                }
            )
        )
        return pack, spec

    def test_rejects_source_manifest_changed_after_pack_build(self):
        with tempfile.TemporaryDirectory() as directory:
            pack, spec = self.fixture(Path(directory))
            (pack / "source_manifest.json").write_text('{"device_ip":"changed"}\n')
            with self.assertRaisesRegex(ValueError, "pack provenance"):
                score(pack, spec, {}, Path(directory) / "result.json")


if __name__ == "__main__":
    unittest.main()
