"""Apply numbered SQL migrations exactly once, under a single runner lock.

This runner decides *which* files run, in what order, and refuses to start when the
recorded history and the files on disk disagree. It does not re-implement PostgreSQL
semantics: transactions, rollback and the advisory lock are the database's, and the
SQL itself is only proved by running it against the real Compose database. Unit tests
cover the decision logic; they are not evidence that the schema applies.

The executor is injected so that decision logic is testable without Docker. The real
one shells into the Compose `postgres` service, following `platform/smoke.py`: the
credential is read inside the container and never enters host argv.

Each migration is sent as one script wrapped in one transaction. A failure anywhere
inside it rolls the whole file back, so a half-applied migration is never recorded.
The advisory lock is taken inside that same transaction, which serialises concurrent
runners without leaving a lock behind if a runner dies.
"""

import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "migrations"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "compose.yaml")]

# A stable, project-specific advisory lock key. Derived rather than invented so two
# unrelated components cannot collide on a hand-picked integer.
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"omniguard.platform.migrations").digest()[:8], "big", signed=True
)

# Raised by the guard inside a migration transaction when another runner won the race.
# It aborts that transaction on purpose: rolling back is how the loser applies nothing.
ALREADY_APPLIED = "omniguard-migration-already-applied"
# Raised by the same guard when the row that runner recorded is not the migration this
# one holds. Losing the race is normal; disagreeing about what was applied is not, and
# reporting it as a skipped success would accept a schema nobody on disk describes.
HISTORY_DRIFT = "omniguard-migration-history-drift"

FILENAME = re.compile(r"^(\d{3})_([a-z0-9]+(?:_[a-z0-9]+)*)\.sql$")
# CONCURRENTLY cannot run inside a transaction block; it would fail at apply time.
CONCURRENTLY = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)
DOLLAR_TAG = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")
LEADING_WORDS = re.compile(r"^([A-Za-z_]+)(?:\s+([A-Za-z_]+))?")

# The runner owns the transaction, so a file must not open or close one itself. These
# are matched as the first word of a statement, not anywhere in a line: a COMMIT that
# ends the runner's transaction mid-file leaves earlier DDL committed, records no
# migration row, releases the advisory lock, and still reports a clean rollback.
TRANSACTION_CONTROL = frozenset({"BEGIN", "COMMIT", "END", "ROLLBACK", "ABORT", "SAVEPOINT"})
# Two-word forms whose first word is legitimate on its own (PREPARE stmt, RELEASE lock).
TRANSACTION_CONTROL_PAIRS = frozenset(
    {("START", "TRANSACTION"), ("PREPARE", "TRANSACTION"), ("RELEASE", "SAVEPOINT")}
)


def sanitised(body: str) -> str:
    """Blank out comments, string literals, quoted identifiers and dollar-quoted bodies.

    Statement boundaries and leading keywords can only be read once the text that may
    legitimately contain `;`, `COMMIT` or `BEGIN` is removed. Regions are replaced by
    spaces rather than deleted so offsets, and therefore reported line numbers, survive.
    A PL/pgSQL block legitimately contains BEGIN/END; it is dollar-quoted, so it is
    blanked here and only transaction control at the statement level remains visible.
    """
    out: list[str] = []
    position, size = 0, len(body)
    while position < size:
        character = body[position]
        if body.startswith("--", position):
            end = body.find("\n", position)
            end = size if end == -1 else end
        elif body.startswith("/*", position):
            # PostgreSQL block comments nest, so depth is counted rather than assumed.
            depth, end = 1, position + 2
            while end < size and depth:
                if body.startswith("/*", end):
                    depth, end = depth + 1, end + 2
                elif body.startswith("*/", end):
                    depth, end = depth - 1, end + 2
                else:
                    end += 1
        elif character in "'\"":
            end = position + 1
            while end < size:
                if body[end] != character:
                    end += 1
                elif end + 1 < size and body[end + 1] == character:
                    end += 2  # A doubled quote is an escaped quote, not the end.
                else:
                    end += 1
                    break
        elif (opening := DOLLAR_TAG.match(body, position)) is not None:
            tag = opening.group(0)
            closing = body.find(tag, opening.end())
            # Unterminated quoting is the database's error to report, not ours to guess;
            # the rest of the file is treated as quoted so nothing inside it is read.
            end = size if closing == -1 else closing + len(tag)
        else:
            out.append(character)
            position += 1
            continue
        out.append(" " * (end - position))
        position = end
    return "".join(out)


def statements(body: str) -> tuple[str, ...]:
    """Split a file into top-level statements, with their quoted content blanked out."""
    return tuple(part.strip() for part in sanitised(body).split(";") if part.strip())


def transaction_control_in(body: str) -> str | None:
    """Return the offending statement keyword, or None when the file opens no transaction."""
    for statement in statements(body):
        words = LEADING_WORDS.match(statement)
        if words is None:
            continue
        first = words.group(1).upper()
        second = (words.group(2) or "").upper()
        if first in TRANSACTION_CONTROL:
            return first
        if (first, second) in TRANSACTION_CONTROL_PAIRS:
            return f"{first} {second}"
    return None


BOOTSTRAP = f"""
BEGIN;
SELECT pg_advisory_xact_lock({LOCK_KEY});
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text        PRIMARY KEY,
    name       text        NOT NULL,
    checksum   text        NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
COMMIT;
"""


class MigrationError(Exception):
    """The runner refuses to continue; the database is left as it was found."""


class ExecutorError(Exception):
    """The database rejected a statement. Carries the server's own message."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    path: Path
    body: str
    checksum: str


@dataclass(frozen=True)
class Outcome:
    applied: tuple[str, ...]
    skipped: tuple[str, ...]
    already_current: tuple[str, ...]


def checksum_of(data: bytes) -> str:
    """Hash the file bytes, so a whitespace-only edit to an applied file is still drift."""
    return hashlib.sha256(data).hexdigest()


def discover(directory: Path = MIGRATIONS) -> tuple[Migration, ...]:
    if not directory.is_dir():
        raise MigrationError(f"migrations directory is missing: {directory}")
    found: dict[str, Migration] = {}
    for path in sorted(directory.iterdir()):
        if path.name.startswith("."):
            continue
        match = FILENAME.match(path.name)
        if not match or not path.is_file():
            raise MigrationError(f"not a NNN_name.sql migration file: {path.name}")
        version, name = match.group(1), match.group(2)
        if version in found:
            raise MigrationError(f"duplicate migration version {version}: {path.name}")
        data = path.read_bytes()
        body = data.decode("utf-8")
        if (control := transaction_control_in(body)) is not None:
            raise MigrationError(
                f"{path.name} manages its own transaction ({control}); the runner does that"
            )
        if CONCURRENTLY.search(sanitised(body)):
            raise MigrationError(
                f"{path.name} uses CONCURRENTLY, which cannot run in one transaction"
            )
        if not body.strip():
            raise MigrationError(f"{path.name} is empty")
        found[version] = Migration(version, name, path, body, checksum_of(data))
    if not found:
        raise MigrationError(f"no migrations found in {directory}")
    return tuple(found[version] for version in sorted(found))


def script_for(migration: Migration) -> str:
    """One transaction: lock, re-check under the lock, apply, record.

    The re-check matters because the pending list was read before the lock was held,
    and it compares the whole recorded row rather than only the version. Another runner
    that recorded this version from different bytes has left history this runner cannot
    vouch for; existence alone would read that as "already done" and continue applying
    later migrations onto a schema no file on disk describes. Raising inside the
    transaction is what makes the losing runner a no-op instead of a second application
    of the same DDL.
    """
    return (
        f"BEGIN;\n"
        f"SELECT pg_advisory_xact_lock({LOCK_KEY});\n"
        f"DO $omniguard_guard$\n"
        f"DECLARE\n"
        f"    recorded record;\n"
        f"BEGIN\n"
        f"    SELECT name, checksum INTO recorded\n"
        f"    FROM schema_migrations WHERE version = '{migration.version}';\n"
        f"    IF FOUND THEN\n"
        f"        IF recorded.name = '{migration.name}'\n"
        f"           AND recorded.checksum = '{migration.checksum}'\n"
        f"        THEN RAISE EXCEPTION '{ALREADY_APPLIED}';\n"
        f"        END IF;\n"
        f"        RAISE EXCEPTION '{HISTORY_DRIFT}: {migration.version} is recorded as "
        f"name=% checksum=%, but this runner holds "
        f"name={migration.name} checksum={migration.checksum}',\n"
        f"            recorded.name, recorded.checksum;\n"
        f"    END IF;\n"
        f"END\n"
        f"$omniguard_guard$;\n"
        f"\n{migration.body.strip()}\n\n"
        f"INSERT INTO schema_migrations (version, name, checksum)\n"
        f"VALUES ('{migration.version}', '{migration.name}', '{migration.checksum}');\n"
        f"COMMIT;\n"
    )


def read_applied(executor) -> dict[str, tuple[str, str]]:
    rows = executor.fetch("SELECT version, name, checksum FROM schema_migrations ORDER BY version")
    return {row[0]: (row[1], row[2]) for row in rows}


def verify(migrations: tuple[Migration, ...], applied: dict[str, tuple[str, str]]) -> None:
    """Refuse to start on any disagreement between recorded history and the files.

    An applied migration that changed, or that is no longer on disk, means the database
    is not the one these files describe. Continuing would apply later migrations on top
    of an unknown schema, so this stops instead.
    """
    on_disk = {migration.version: migration for migration in migrations}
    for version, (name, checksum) in sorted(applied.items()):
        migration = on_disk.get(version)
        if migration is None:
            raise MigrationError(
                f"migration {version}_{name}.sql is recorded as applied but is not on disk"
            )
        if migration.checksum != checksum:
            raise MigrationError(
                f"{migration.path.name} changed after it was applied: "
                f"recorded {checksum[:12]}, on disk {migration.checksum[:12]}"
            )
        if migration.name != name:
            raise MigrationError(
                f"migration {version} is recorded as {version}_{name}.sql but is on disk as "
                f"{migration.path.name}; renaming an applied migration is history drift"
            )
    if applied:
        highest = max(applied)
        for migration in migrations:
            if migration.version not in applied and migration.version < highest:
                raise MigrationError(
                    f"{migration.path.name} is unapplied but sorts before applied {highest}; "
                    "renumber it rather than inserting into applied history"
                )


def migrate(executor, directory: Path = MIGRATIONS) -> Outcome:
    migrations = discover(directory)
    executor.run_script(BOOTSTRAP)
    applied = read_applied(executor)
    verify(migrations, applied)
    done, skipped, current = [], [], tuple(sorted(applied))
    for migration in migrations:
        if migration.version in applied:
            if migration.version not in current:
                # Applied by another runner while this one was working, not before it.
                skipped.append(migration.version)
            continue
        try:
            executor.run_script(script_for(migration))
        except ExecutorError as error:
            message = str(error)
            if HISTORY_DRIFT in message:
                raise MigrationError(
                    f"{migration.path.name} disagrees with the history another runner "
                    f"recorded under the lock: {message}"
                ) from error
            if ALREADY_APPLIED in message:
                # Another runner committed the same bytes between our read and our lock.
                # Its transaction rolled back; nothing of ours was written. Its history is
                # re-read and re-verified before any later migration is sent, because that
                # runner may also have recorded versions this checkout cannot account for.
                skipped.append(migration.version)
                applied = read_applied(executor)
                verify(migrations, applied)
                continue
            raise MigrationError(
                f"{migration.path.name} failed and was rolled back: {error}"
            ) from error
        done.append(migration.version)
        applied[migration.version] = (migration.name, migration.checksum)
    return Outcome(tuple(done), tuple(skipped), current)


class ComposePsql:
    """Runs SQL as the migration role inside the Compose `postgres` service."""

    def __init__(self, user: str = "omniguard", database: str = "omniguard", timeout: int = 60):
        self.user, self.database, self.timeout = user, database, timeout

    def _psql(self, *args: str, stdin: str | None = None) -> str:
        result = subprocess.run(
            [
                *COMPOSE,
                "exec",
                "-T",
                "postgres",
                "psql",
                "-U",
                self.user,
                "-d",
                self.database,
                "-v",
                "ON_ERROR_STOP=1",
                *args,
            ],
            input=stdin,
            text=True,
            capture_output=True,
            timeout=self.timeout,
        )
        if result.returncode != 0:
            raise ExecutorError((result.stderr or result.stdout).strip())
        return result.stdout

    def run_script(self, sql: str) -> None:
        self._psql("-f", "-", stdin=sql)

    def fetch(self, sql: str) -> tuple[tuple[str, ...], ...]:
        output = self._psql("-A", "-t", "-F", "\t", "-c", sql)
        return tuple(tuple(line.split("\t")) for line in output.splitlines() if line)


def main() -> int:
    try:
        outcome = migrate(ComposePsql())
    except (MigrationError, ExecutorError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print(
            "FAIL: psql timed out; the database may still be applying a migration.",
            file=sys.stderr,
        )
        return 1
    print(f"already applied: {', '.join(outcome.already_current) or 'none'}")
    print(f"applied now:     {', '.join(outcome.applied) or 'none'}")
    if outcome.skipped:
        print(f"applied concurrently by another runner: {', '.join(outcome.skipped)}")
    print("PASS: schema is at the revision these migration files describe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
