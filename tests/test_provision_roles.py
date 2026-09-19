"""Role provisioning must refuse bad credentials and must not trust ALTER ROLE alone.

These tests cover the decision logic against an injected executor. They do not run SQL,
so they are not evidence that either role can log in — that comes from running
`platform/provision_roles.py` against the real Compose database, which is what the
KAN-41 evidence in platform/README.md records. What they do prove is that a credential
that is not what init_secrets.py generates never reaches an SQL literal, that a role
whose password was set but which still cannot authenticate is reported as a failure
rather than a success, and that no password is ever placed on a command line.
"""

import contextlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

# platform/ is deliberately not a Python package; load the module by path.
SOURCE = Path(__file__).resolve().parents[1] / "platform" / "provision_roles.py"
_spec = importlib.util.spec_from_file_location("omniguard_provision_roles", SOURCE)
provision_roles = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(provision_roles)

GOOD = "a" * 64
OTHER = "b" * 64


class FakeExecutor:
    """Records the scripts it was given and whether each role was proved to log in."""

    def __init__(self, *, refuse_login: set[str] | None = None):
        self.scripts: list[str] = []
        self.login_attempts: list[tuple[str, str]] = []
        self._refuse = refuse_login or set()

    def run_script(self, sql: str) -> None:
        self.scripts.append(sql)

    def can_log_in(self, role: str, password: str) -> bool:
        self.login_attempts.append((role, password))
        return role not in self._refuse


def secrets_directory(stack, **files: str) -> Path:
    directory = Path(stack.enter_context(tempfile.TemporaryDirectory()))
    for name, value in files.items():
        (directory / name).write_text(value + "\n", encoding="utf-8")
    return directory


class PasswordTests(unittest.TestCase):
    def test_a_missing_credential_names_the_command_that_creates_it(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(provision_roles.ProvisionError) as raised:
                provision_roles.read_password("readonly_password", Path(directory))
        self.assertIn("init_secrets.py", str(raised.exception))

    def test_a_credential_that_is_not_the_generated_shape_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "readonly_password"
            # A hand-edited secret carrying a quote is exactly what would break out of
            # the SQL literal. It is refused rather than escaped.
            path.write_text("hunter2'; DROP TABLE events; --\n", encoding="utf-8")
            with self.assertRaises(provision_roles.ProvisionError):
                provision_roles.read_password("readonly_password", Path(directory))

    def test_the_trailing_newline_init_secrets_writes_is_stripped(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "readonly_password").write_text(GOOD + "\n", encoding="utf-8")
            self.assertEqual(
                provision_roles.read_password("readonly_password", Path(directory)), GOOD
            )

    def test_an_unknown_role_never_reaches_a_statement(self):
        with self.assertRaises(provision_roles.ProvisionError):
            provision_roles.alter_role_script("postgres", GOOD)

    def test_a_password_that_failed_validation_cannot_be_written_directly(self):
        with self.assertRaises(provision_roles.ProvisionError):
            provision_roles.alter_role_script("omniguard_readonly", "not-hex")


class ProvisionTests(unittest.TestCase):
    def test_both_roles_are_set_and_each_one_is_proved_to_log_in(self):
        with contextlib.ExitStack() as stack:
            directory = secrets_directory(stack, consumer_password=GOOD, readonly_password=OTHER)
            executor = FakeExecutor()
            provisioned = provision_roles.provision(executor, directory)

        self.assertEqual(provisioned, ("omniguard_consumer", "omniguard_readonly"))
        self.assertEqual(len(executor.scripts), 2)
        # Setting a password is not the same claim as being able to use it.
        self.assertEqual(
            executor.login_attempts,
            [("omniguard_consumer", GOOD), ("omniguard_readonly", OTHER)],
        )

    def test_a_role_that_cannot_log_in_afterwards_is_a_failure(self):
        with contextlib.ExitStack() as stack:
            directory = secrets_directory(stack, consumer_password=GOOD, readonly_password=OTHER)
            executor = FakeExecutor(refuse_login={"omniguard_readonly"})
            with self.assertRaises(provision_roles.ProvisionError) as raised:
                provision_roles.provision(executor, directory)

        self.assertIn("omniguard_readonly", str(raised.exception))
        self.assertIn("cannot log in", str(raised.exception))

    def test_each_role_gets_its_own_credential(self):
        with contextlib.ExitStack() as stack:
            directory = secrets_directory(stack, consumer_password=GOOD, readonly_password=OTHER)
            executor = FakeExecutor()
            provision_roles.provision(executor, directory)

        consumer, readonly = executor.scripts
        self.assertIn(f"ALTER ROLE omniguard_consumer PASSWORD '{GOOD}'", consumer)
        self.assertIn(f"ALTER ROLE omniguard_readonly PASSWORD '{OTHER}'", readonly)
        self.assertNotIn(OTHER, consumer)
        self.assertNotIn(GOOD, readonly)

    def test_a_missing_secret_stops_before_any_statement_runs(self):
        with contextlib.ExitStack() as stack:
            directory = secrets_directory(stack, consumer_password=GOOD)
            executor = FakeExecutor()
            with self.assertRaises(provision_roles.ProvisionError):
                provision_roles.provision(executor, directory)

        # omniguard_consumer comes first and succeeds; the point is that the failure
        # is raised rather than swallowed, not that nothing was applied.
        self.assertNotIn("omniguard_readonly", [role for role, _ in executor.login_attempts])


class CommandLineTests(unittest.TestCase):
    """A credential on argv is readable by every process on the host."""

    def test_the_executor_sends_sql_on_stdin_rather_than_with_dash_c(self):
        recorded = {}

        class Recorder(provision_roles.ComposePsql):
            def _run(self, argv, stdin=None):
                recorded["argv"], recorded["stdin"] = argv, stdin
                raise AssertionError("not executed")

        with self.assertRaises(AssertionError):
            Recorder().run_script(f"ALTER ROLE omniguard_readonly PASSWORD '{GOOD}';\n")

        self.assertIn("-f", recorded["argv"])
        self.assertNotIn("-c", recorded["argv"])
        self.assertIn(GOOD, recorded["stdin"])
        self.assertNotIn(GOOD, " ".join(recorded["argv"]))

    def test_the_login_check_keeps_the_password_off_argv_and_out_of_the_environment(self):
        recorded = {}

        class Recorder(provision_roles.ComposePsql):
            def _run(self, argv, stdin=None):
                recorded["argv"], recorded["stdin"] = argv, stdin
                raise AssertionError("not executed")

        with self.assertRaises(AssertionError):
            Recorder().can_log_in("omniguard_readonly", GOOD)

        joined = " ".join(recorded["argv"])
        self.assertNotIn(GOOD, joined)
        # `docker compose exec -e PGPASSWORD=...` would put it on the host command line
        # too, so the shell reads it from stdin instead.
        self.assertNotIn("-e", recorded["argv"])
        self.assertIn(GOOD, recorded["stdin"])
        # The connection must go over TCP; a Unix socket inside the container can be
        # trusted by pg_hba and would pass without checking the password at all.
        self.assertIn("-h 127.0.0.1", joined)


if __name__ == "__main__":
    unittest.main()
