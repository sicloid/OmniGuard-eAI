import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from measure.result_freeze import create, verify


class ResultFreezeTests(unittest.TestCase):
    def repository(self, parent: Path) -> Path:
        root = parent / "repo"
        root.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"], cwd=root, check=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
        (root / "declaration.json").write_text('{"policy":"N2-L300"}\n')
        (root / "evidence").mkdir()
        (root / "evidence" / "result.json").write_text('{"passed":true}\n')
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        return root

    def test_freeze_is_hash_pinned_and_detects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(Path(directory))
            output = Path(directory) / "freeze.json"
            document = create(
                root,
                [Path("evidence")],
                Path("declaration.json"),
                output,
                frozen_at_utc="2026-09-28T00:00:00Z",
            )
            self.assertEqual(len(document["files"]), 1)
            self.assertEqual(verify(root, output)["git_commit"], document["git_commit"])
            (root / "evidence" / "result.json").write_text('{"passed":false}\n')
            with self.assertRaisesRegex(ValueError, "evidence drift"):
                verify(root, output)

    def test_refuses_a_dirty_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(Path(directory))
            (root / "untracked.txt").write_text("not declared\n")
            with self.assertRaisesRegex(ValueError, "clean"):
                create(
                    root,
                    [Path("evidence")],
                    Path("declaration.json"),
                    Path(directory) / "freeze.json",
                    frozen_at_utc="2026-09-28T00:00:00Z",
                )

    def test_manifest_contains_declaration_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(Path(directory))
            output = Path(directory) / "freeze.json"
            create(
                root,
                [Path("evidence/result.json")],
                Path("declaration.json"),
                output,
                frozen_at_utc="2026-09-28T00:00:00Z",
            )
            saved = json.loads(output.read_text())
            self.assertEqual(saved["declaration"]["content"]["policy"], "N2-L300")

    def test_exclusive_create_refuses_an_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(Path(directory))
            output = Path(directory) / "freeze.json"
            output.write_text("occupied\n")
            with self.assertRaises(FileExistsError):
                create(
                    root,
                    [Path("evidence")],
                    Path("declaration.json"),
                    output,
                    frozen_at_utc="2026-09-28T00:00:00Z",
                )
            self.assertEqual(output.read_text(), "occupied\n")

    @unittest.skipIf(os.name == "nt", "Windows CI cannot create unprivileged symlinks")
    def test_refuses_symlink_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.repository(Path(directory))
            (root / "alias.json").symlink_to(root / "evidence" / "result.json")
            subprocess.run(["git", "add", "alias.json"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "symlink"], cwd=root, check=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                create(
                    root,
                    [Path("alias.json")],
                    Path("declaration.json"),
                    Path(directory) / "freeze.json",
                    frozen_at_utc="2026-09-28T00:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
