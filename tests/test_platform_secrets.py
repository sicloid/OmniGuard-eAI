"""Credentials must reach the containers byte-for-byte on every host platform."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

# platform/ is deliberately not a Python package, so it cannot be imported by
# name without shadowing the standard library module. Load it by path instead.
SOURCE = Path(__file__).resolve().parents[1] / "platform" / "init_secrets.py"
_spec = importlib.util.spec_from_file_location("omniguard_init_secrets", SOURCE)
init_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(init_secrets)


class SecretWriteTests(unittest.TestCase):
    def test_secret_is_written_without_line_separator_translation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mqtt_password"
            init_secrets.write_secret(path, b"0123abcd\n")
            try:
                self.assertEqual(path.read_bytes(), b"0123abcd\n")
            finally:
                path.chmod(0o600)

    def test_existing_secret_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "postgres_password"
            path.write_bytes(b"already-there\n")
            init_secrets.write_secret(path, b"replacement\n")
            self.assertEqual(path.read_bytes(), b"already-there\n")


if __name__ == "__main__":
    unittest.main()
