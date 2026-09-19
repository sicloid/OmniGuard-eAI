"""Give the two login roles a password, and prove each one can actually log in.

`001_initial_schema.sql` creates `omniguard_consumer` and `omniguard_readonly` with
LOGIN but no password, so until now everything has connected as the owner. Grafana
cannot: it reaches PostgreSQL over the internal network and must authenticate as
`omniguard_readonly`.

This is deliberately *not* a numbered migration. `migrate.py` records each file's
checksum in `schema_migrations` and applies it exactly once, which is right for schema
and wrong for a credential:

* a literal password in a migration file would be committed to Git;
* a placeholder substituted at apply time would be recorded under a checksum that
  describes the template rather than the password that was set, and — worse — a
  regenerated `platform/.secrets/` would be skipped as "already applied", leaving the
  roles without a password while `schema_migrations` claims otherwise.

Passwords are environment state, not schema, so they are applied every run instead of
once. Re-running is the normal case, not a repair.

Nothing here prints a credential, and no credential is passed as a command-line
argument: argv is visible to every process on the host and in the container. SQL and
passwords travel on stdin.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]
SECRETS = ROOT / ".secrets"

# role -> the secret file holding its password.
ROLES = {
    "omniguard_consumer": "consumer_password",
    "omniguard_readonly": "readonly_password",
}

# init_secrets.py writes secrets.token_hex(32). Rather than escape an arbitrary string
# into an SQL literal, refuse anything that is not what this project generates: a
# password that cannot contain a quote cannot break out of one. A hand-edited secret is
# a mistake worth failing on, not worth quoting around.
PASSWORD = re.compile(r"\A[0-9a-f]{64}\Z")


class ProvisionError(Exception):
    """A role could not be given a working password."""


class ExecutorError(ProvisionError):
    """psql could not be run, or returned a failure."""


def read_password(name: str, directory: Path = SECRETS) -> str:
    path = directory / name
    if path.is_symlink():
        raise ProvisionError(f"refusing secret symlink: {name}")
    if not path.exists():
        raise ProvisionError(f"missing credential {name}; run platform/init_secrets.py first")
    password = path.read_text(encoding="utf-8").strip()
    if not PASSWORD.fullmatch(password):
        raise ProvisionError(
            f"{name} is not the 64 hex characters init_secrets.py generates; "
            "refusing to build an SQL literal out of it"
        )
    return password


def alter_role_script(role: str, password: str) -> str:
    """One statement. The role name is a fixed key of ROLES, never caller input."""
    if role not in ROLES:
        raise ProvisionError(f"unknown role: {role}")
    if not PASSWORD.fullmatch(password):
        raise ProvisionError("refusing to write a password that failed validation")
    return f"ALTER ROLE {role} PASSWORD '{password}';\n"


def provision(executor, directory: Path = SECRETS) -> tuple[str, ...]:
    """Set each role's password, then log in as that role to prove it took effect.

    The readback matters for the same reason it does in the enforcer: a successful
    ALTER ROLE says the statement ran, not that the role can authenticate. Password
    encryption, pg_hba rules and the role's own LOGIN attribute all sit between the
    two, and Grafana's datasource depends on the second, not the first.
    """
    provisioned = []
    for role, secret_name in ROLES.items():
        password = read_password(secret_name, directory)
        executor.run_script(alter_role_script(role, password))
        if not executor.can_log_in(role, password):
            raise ProvisionError(f"{role} password was set but the role still cannot log in")
        provisioned.append(role)
    return tuple(provisioned)


class ComposePsql:
    """Runs SQL inside the Compose `postgres` service, as migrate.py does."""

    def __init__(self, user: str = "omniguard", database: str = "omniguard", timeout: int = 60):
        self.user, self.database, self.timeout = user, database, timeout

    def _run(self, argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [*COMPOSE, "exec", "-T", "postgres", *argv],
            input=stdin,
            text=True,
            # The database is UTF-8; the pipe must be too. text=True would otherwise
            # encode with the host preferred encoding, which is cp1254 here.
            encoding="utf-8",
            capture_output=True,
            timeout=self.timeout,
        )

    def run_script(self, sql: str) -> None:
        result = self._run(
            ["psql", "-U", self.user, "-d", self.database, "-v", "ON_ERROR_STOP=1", "-f", "-"],
            stdin=sql,
        )
        if result.returncode != 0:
            raise ExecutorError((result.stderr or result.stdout).strip())

    def can_log_in(self, role: str, password: str) -> bool:
        """Connect over TCP as `role`, so the password is actually exercised.

        A Unix-socket connection inside the container can be trusted by pg_hba and
        would pass without ever checking the password. Grafana arrives over TCP, so
        the check does too. The password is read from stdin by the shell rather than
        passed as an argument or an -e environment value, neither of which stays
        private on a shared host.
        """
        result = self._run(
            [
                "sh",
                "-ec",
                "read -r password\n"
                'PGPASSWORD="$password" exec psql -h 127.0.0.1 -U "$0" -d "$1" '
                "-v ON_ERROR_STOP=1 -tAc 'SELECT 1'",
                role,
                self.database,
            ],
            stdin=f"{password}\n",
        )
        if result.returncode == 0:
            return result.stdout.strip() == "1"
        detail = (result.stderr or result.stdout).strip().lower()
        # An authentication refusal is the answer to the question. Anything else — the
        # service being down, the database missing — is not, and must not be reported
        # as "this role cannot log in".
        if "authentication failed" in detail or "no password supplied" in detail:
            return False
        raise ExecutorError(detail or f"psql exited {result.returncode}")


def main() -> int:
    try:
        provisioned = provision(ComposePsql())
    except (ProvisionError, ExecutorError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("FAIL: psql timed out; is the Compose database running?", file=sys.stderr)
        return 1
    print(f"provisioned: {', '.join(provisioned)}")
    print("PASS: both roles authenticate with the credentials in platform/.secrets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
