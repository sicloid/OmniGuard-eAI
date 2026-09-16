"""The migration runner must apply each file once and refuse to start on drift.

These tests cover the runner's decision logic against an injected executor. They do
not execute SQL, so they are not evidence that 001 applies: that comes from running
`platform/migrate.py` against the real Compose database. What they do prove is that a
failed migration is never recorded, that an edited or missing applied file stops
startup, and that two runners cannot both apply the same version.
"""

import importlib.util
import re
import tempfile
import unittest
from pathlib import Path

# platform/ is deliberately not a Python package, so it cannot be imported by name
# without shadowing the standard library module. Load it by path instead.
SOURCE = Path(__file__).resolve().parents[1] / "platform" / "migrate.py"
_spec = importlib.util.spec_from_file_location("omniguard_migrate", SOURCE)
migrate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migrate)

GUARD = re.compile(r"WHERE version = '(\d{3})'")
RECORD = re.compile(r"VALUES \('(\d{3})', '([a-z0-9_]+)', '([0-9a-f]{64})'\)")
# What the guard says the recorded row must be for this runner to treat it as its own.
EXPECTED = re.compile(
    r"recorded\.name = '([a-z0-9_]+)'\s+AND recorded\.checksum = '([0-9a-f]{64})'"
)


class FakeDatabase:
    """Models only what the runner depends on: all-or-nothing scripts and the guard.

    A script either records its migration or leaves the database untouched. That is the
    property the runner relies on for rollback, so the fake refuses to represent a
    partially applied script at all.
    """

    def __init__(self, applied=None):
        self.applied = dict(applied or {})
        self.scripts = []
        self.fail_on = {}
        self.before_apply = None

    def run_script(self, sql):
        self.scripts.append(sql)
        if "CREATE TABLE IF NOT EXISTS schema_migrations" in sql:
            return
        version = GUARD.search(sql).group(1)
        if self.before_apply is not None:
            hook, self.before_apply = self.before_apply, None
            hook(self)
        if version in self.applied:
            # The guard compares the whole recorded row, so the fake answers the way the
            # server does: the same bytes are a lost race, different bytes are drift.
            name, checksum = self.applied[version]
            if (name, checksum) == EXPECTED.search(sql).groups():
                raise migrate.ExecutorError(
                    f"ERROR:  {migrate.ALREADY_APPLIED}\n"
                    f"CONTEXT:  PL/pgSQL function inline_code_block"
                )
            raise migrate.ExecutorError(
                f"ERROR:  {migrate.HISTORY_DRIFT}: {version} is recorded as name={name} "
                f"checksum={checksum}\nCONTEXT:  PL/pgSQL function inline_code_block"
            )
        if version in self.fail_on:
            # The transaction aborts, so nothing from this script survives.
            raise migrate.ExecutorError(self.fail_on[version])
        record = RECORD.search(sql)
        self.applied[record.group(1)] = (record.group(2), record.group(3))

    def fetch(self, sql):
        return tuple(
            (version, name, checksum) for version, (name, checksum) in sorted(self.applied.items())
        )


def write(directory, name, body="CREATE TABLE placeholder (id integer);\n"):
    path = Path(directory) / name
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


class DiscoveryTests(unittest.TestCase):
    def test_the_real_migrations_are_discoverable_in_version_order(self):
        migrations = migrate.discover()
        self.assertEqual([m.version for m in migrations], ["001", "002"])
        self.assertEqual([m.name for m in migrations], ["initial_schema", "boot_ordering"])

    def test_the_additive_migration_does_not_touch_the_applied_one(self):
        # 001 is applied and its checksum recorded. KAN-40 adds to the schema; a DROP,
        # an ALTER of an existing column or a re-CREATE of events would be rewriting
        # history through a new file instead of editing the old one.
        body = re.sub(r"--[^\n]*", "", migrate.discover()[1].body).upper()
        for forbidden in ("DROP TABLE", "DROP COLUMN", "ALTER COLUMN", "CREATE TABLE EVENTS"):
            with self.subTest(forbidden):
                self.assertNotIn(forbidden, body)

    def test_the_additive_migration_carries_the_boot_ordering_columns(self):
        body = re.sub(r"--[^\n]*", "", migrate.discover()[1].body).lower()
        self.assertIn("create table boots", body)
        for column in ("producer_id", "boot_id", "sequence"):
            with self.subTest(column):
                self.assertIn(column, body)

    def test_the_initial_migration_declares_no_boot_columns(self):
        # KAN-39's agreed scope: boot identity arrives in KAN-40's additive 002. The
        # comments name those columns to explain their absence, so only the statements
        # are checked; leaving the comments in would let the prose satisfy the test.
        body = re.sub(r"--[^\n]*", "", migrate.discover()[0].body).lower()
        for absent in ("boot_id", "boot_started_at", "producer_id", "boots"):
            with self.subTest(absent):
                self.assertNotIn(absent, body)

    def test_the_initial_migration_carries_run_id_and_a_unique_event_id(self):
        body = migrate.discover()[0].body
        self.assertIn("run_id", body)
        self.assertIn("event_id        text             PRIMARY KEY", body)

    def test_filenames_that_are_not_numbered_migrations_are_rejected(self):
        bad = ("1_initial.sql", "001-initial.sql", "001_Initial.sql", "initial.sql", "001_a.txt")
        for name in bad:
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                write(directory, name)
                with self.assertRaises(migrate.MigrationError):
                    migrate.discover(Path(directory))

    def test_two_files_claiming_one_version_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "001_first.sql")
            write(directory, "001_second.sql")
            with self.assertRaises(migrate.MigrationError):
                migrate.discover(Path(directory))

    def test_a_file_managing_its_own_transaction_is_rejected(self):
        for body in ("BEGIN;\nCREATE TABLE t (id int);\nCOMMIT;\n", "SAVEPOINT s;\n"):
            with self.subTest(body), tempfile.TemporaryDirectory() as directory:
                write(directory, "001_initial.sql", body)
                with self.assertRaises(migrate.MigrationError):
                    migrate.discover(Path(directory))

    def test_transaction_control_after_another_statement_on_the_same_line_is_rejected(self):
        # Reported on PR #31 and reproduced on PostgreSQL 17.6: a line-anchored check
        # accepts this file, the table survives the failing statement that follows, no
        # migration row is recorded, the COMMIT releases the advisory lock, and the
        # runner still reports a clean rollback. The statement boundary is what matters,
        # not the line boundary.
        body = "CREATE TABLE partial_probe(id int); COMMIT;\nSELECT 1/0;\n"
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "001_initial.sql", body)
            with self.assertRaises(migrate.MigrationError) as raised:
                migrate.discover(Path(directory))
            self.assertIn("COMMIT", str(raised.exception))

    def test_transaction_control_hidden_behind_a_comment_is_rejected(self):
        bodies = (
            "/* prepare the table */ COMMIT;\n",
            "CREATE TABLE t (id int); -- record it\n END;\n",
            "CREATE TABLE t (id int);\n/* nested /* comment */ */ ABORT;\n",
        )
        for body in bodies:
            with self.subTest(body), tempfile.TemporaryDirectory() as directory:
                write(directory, "001_initial.sql", body)
                with self.assertRaises(migrate.MigrationError):
                    migrate.discover(Path(directory))

    def test_every_transaction_ending_statement_is_rejected(self):
        endings = (
            "BEGIN;",
            "COMMIT;",
            "END;",
            "ROLLBACK;",
            "ABORT;",
            "SAVEPOINT s;",
            "RELEASE SAVEPOINT s;",
            "START TRANSACTION;",
            "PREPARE TRANSACTION 'x';",
        )
        for ending in endings:
            with self.subTest(ending), tempfile.TemporaryDirectory() as directory:
                write(directory, "001_initial.sql", f"CREATE TABLE t (id int);\n{ending}\n")
                with self.assertRaises(migrate.MigrationError):
                    migrate.discover(Path(directory))

    def test_transaction_keywords_inside_quoted_text_are_not_transaction_control(self):
        # Rejecting these would make the check unusable for any file that mentions the
        # words; the scanner must read statements, not search for keywords.
        bodies = (
            "INSERT INTO notes (body) VALUES ('COMMIT; BEGIN;');\n",
            'CREATE TABLE "commit" (id int);\n',
            "COMMENT ON TABLE t IS 'ends with END;';\n",
            "CREATE TABLE t (id int); -- do not add CONCURRENTLY here\n",
            "CREATE INDEX i ON t (id); /* COMMIT belongs to the runner */\n",
        )
        for body in bodies:
            with self.subTest(body), tempfile.TemporaryDirectory() as directory:
                write(directory, "001_initial.sql", body)
                self.assertEqual(len(migrate.discover(Path(directory))), 1)

    def test_case_end_is_not_transaction_control(self):
        body = "CREATE VIEW v AS SELECT CASE WHEN true THEN 1 ELSE 0 END AS flag;\n"
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "001_initial.sql", body)
            self.assertEqual(len(migrate.discover(Path(directory))), 1)

    def test_plpgsql_begin_inside_dollar_quoting_is_not_transaction_control(self):
        body = "DO $r$\nBEGIN\n    PERFORM 1;\nEND\n$r$;\n"
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "001_initial.sql", body)
            self.assertEqual(len(migrate.discover(Path(directory))), 1)

    def test_concurrently_is_rejected_because_it_cannot_run_in_a_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "001_initial.sql", "CREATE INDEX CONCURRENTLY i ON t (id);\n")
            with self.assertRaises(migrate.MigrationError):
                migrate.discover(Path(directory))

    def test_the_checksum_covers_bytes_so_a_whitespace_edit_is_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, "001_initial.sql", "CREATE TABLE t (id int);\n")
            before = migrate.discover(Path(directory))[0].checksum
            path.write_text("CREATE TABLE t (id int);\n\n", encoding="utf-8", newline="\n")
            self.assertNotEqual(before, migrate.discover(Path(directory))[0].checksum)


class ScriptTests(unittest.TestCase):
    def test_a_migration_is_sent_as_one_locked_guarded_transaction(self):
        script = migrate.script_for(migrate.discover()[0])
        self.assertTrue(script.startswith("BEGIN;"))
        self.assertTrue(script.rstrip().endswith("COMMIT;"))
        self.assertIn(f"pg_advisory_xact_lock({migrate.LOCK_KEY})", script)
        self.assertIn(migrate.ALREADY_APPLIED, script)
        self.assertEqual(script.count("BEGIN;"), 1)
        self.assertEqual(script.count("COMMIT;"), 1)
        # The lock is taken before anything the migration does.
        self.assertLess(script.index("pg_advisory_xact_lock"), script.index("CREATE TABLE events"))

    def test_the_guard_checks_the_whole_recorded_row_not_only_the_version(self):
        migration = migrate.discover()[0]
        script = migrate.script_for(migration)
        self.assertIn(f"recorded.name = '{migration.name}'", script)
        self.assertIn(f"recorded.checksum = '{migration.checksum}'", script)
        self.assertIn(migrate.HISTORY_DRIFT, script)
        # The guard runs after the lock, so what it reads cannot change under it.
        self.assertLess(script.index("pg_advisory_xact_lock"), script.index("recorded.checksum"))

    def test_the_recorded_checksum_is_the_checksum_of_the_file(self):
        migration = migrate.discover()[0]
        self.assertIn(migration.checksum, migrate.script_for(migration))
        self.assertEqual(migration.checksum, migrate.checksum_of(migration.path.read_bytes()))


class RunnerTests(unittest.TestCase):
    def directory(self, *names):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        for index, name in enumerate(names, start=1):
            write(directory, name, f"CREATE TABLE t{index} (id integer);\n")
        return Path(directory)

    def test_a_clean_database_applies_every_migration_in_order(self):
        directory = self.directory("001_first.sql", "002_second.sql")
        database = FakeDatabase()
        outcome = migrate.migrate(database, directory)
        self.assertEqual(outcome.applied, ("001", "002"))
        self.assertEqual(outcome.already_current, ())
        self.assertEqual(sorted(database.applied), ["001", "002"])
        # Bootstrap first, then one script per migration, in version order.
        self.assertIn("CREATE TABLE IF NOT EXISTS schema_migrations", database.scripts[0])
        self.assertEqual([RECORD.search(s).group(1) for s in database.scripts[1:]], ["001", "002"])

    def test_a_second_startup_applies_nothing(self):
        directory = self.directory("001_first.sql")
        database = FakeDatabase()
        migrate.migrate(database, directory)
        scripts = len(database.scripts)
        outcome = migrate.migrate(database, directory)
        self.assertEqual(outcome.applied, ())
        self.assertEqual(outcome.already_current, ("001",))
        # Only the idempotent bootstrap ran the second time.
        self.assertEqual(len(database.scripts), scripts + 1)

    def test_a_concurrent_runner_that_loses_the_race_applies_nothing(self):
        directory = self.directory("001_first.sql")
        database = FakeDatabase()
        migration = migrate.discover(directory)[0]
        # The other runner commits after we read the pending list but before our lock.
        database.before_apply = lambda db: db.applied.__setitem__(
            migration.version, (migration.name, migration.checksum)
        )
        outcome = migrate.migrate(database, directory)
        self.assertEqual(outcome.applied, ())
        self.assertEqual(outcome.skipped, ("001",))
        self.assertEqual(database.applied[migration.version][1], migration.checksum)

    def test_a_concurrent_runner_that_recorded_different_bytes_stops_startup(self):
        # Reported on PR #31: the guard checked existence only, so a version recorded
        # from bytes this checkout does not have was reported as a skipped success while
        # its schema body never ran. Disagreement is not a race that was lost.
        directory = self.directory("001_first.sql")
        database = FakeDatabase()
        database.before_apply = lambda db: db.applied.__setitem__("001", ("first", "f" * 64))
        with self.assertRaises(migrate.MigrationError) as raised:
            migrate.migrate(database, directory)
        self.assertIn(migrate.HISTORY_DRIFT, str(raised.exception))

    def test_a_concurrent_runner_that_recorded_another_name_stops_startup(self):
        directory = self.directory("001_first.sql")
        database = FakeDatabase()
        checksum = migrate.discover(directory)[0].checksum
        database.before_apply = lambda db: db.applied.__setitem__("001", ("renamed", checksum))
        with self.assertRaises(migrate.MigrationError) as raised:
            migrate.migrate(database, directory)
        self.assertIn(migrate.HISTORY_DRIFT, str(raised.exception))

    def test_history_written_by_the_winner_is_reverified_before_later_migrations(self):
        # The winner may have recorded more than the version this runner was applying.
        # Re-reading only that one row would let the rest of its history through unseen.
        directory = self.directory("001_first.sql", "002_second.sql")
        database = FakeDatabase()
        migration = migrate.discover(directory)[0]

        def winner(db):
            db.applied["001"] = (migration.name, migration.checksum)
            db.applied["003"] = ("from_another_checkout", "a" * 64)

        database.before_apply = winner
        with self.assertRaises(migrate.MigrationError) as raised:
            migrate.migrate(database, directory)
        self.assertIn("not on disk", str(raised.exception))
        # 002 was never sent: the disagreement is refused before anything later runs.
        self.assertNotIn("002", database.applied)
        self.assertEqual([RECORD.search(s).group(1) for s in database.scripts[1:]], ["001"])

    def test_a_version_the_winner_applied_ahead_of_us_is_reported_as_skipped(self):
        directory = self.directory("001_first.sql", "002_second.sql")
        database = FakeDatabase()
        second = migrate.discover(directory)[1]
        database.before_apply = lambda db: db.applied.__setitem__(
            "002", (second.name, second.checksum)
        )
        outcome = migrate.migrate(database, directory)
        self.assertEqual(outcome.applied, ("001",))
        self.assertEqual(outcome.skipped, ("002",))
        self.assertEqual(outcome.already_current, ())

    def test_a_failed_migration_is_not_recorded_and_is_retried_next_start(self):
        directory = self.directory("001_first.sql", "002_second.sql")
        database = FakeDatabase()
        database.fail_on["002"] = 'ERROR:  relation "t1" does not exist'
        with self.assertRaises(migrate.MigrationError) as raised:
            migrate.migrate(database, directory)
        self.assertIn("rolled back", str(raised.exception))
        self.assertEqual(sorted(database.applied), ["001"])
        database.fail_on.clear()
        self.assertEqual(migrate.migrate(database, directory).applied, ("002",))

    def test_a_later_migration_is_not_attempted_after_an_earlier_one_fails(self):
        directory = self.directory("001_first.sql", "002_second.sql")
        database = FakeDatabase()
        database.fail_on["001"] = "ERROR:  syntax error"
        with self.assertRaises(migrate.MigrationError):
            migrate.migrate(database, directory)
        self.assertEqual(database.applied, {})
        attempted = [RECORD.search(s).group(1) for s in database.scripts[1:]]
        self.assertEqual(attempted, ["001"])


class DriftTests(unittest.TestCase):
    def test_an_edited_applied_migration_stops_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, "001_first.sql", "CREATE TABLE t (id integer);\n")
            database = FakeDatabase()
            migrate.migrate(database, Path(directory))
            path.write_text("CREATE TABLE t (id bigint);\n", encoding="utf-8", newline="\n")
            with self.assertRaises(migrate.MigrationError) as raised:
                migrate.migrate(database, Path(directory))
            self.assertIn("changed after it was applied", str(raised.exception))

    def test_an_applied_migration_missing_from_disk_stops_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "001_first.sql")
            write(directory, "002_second.sql")
            database = FakeDatabase()
            migrate.migrate(database, Path(directory))
            (Path(directory) / "002_second.sql").unlink()
            with self.assertRaises(migrate.MigrationError) as raised:
                migrate.migrate(database, Path(directory))
            self.assertIn("not on disk", str(raised.exception))

    def test_a_new_file_numbered_below_applied_history_stops_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            write(directory, "002_second.sql")
            database = FakeDatabase()
            migrate.migrate(database, Path(directory))
            write(directory, "001_inserted_late.sql")
            with self.assertRaises(migrate.MigrationError) as raised:
                migrate.migrate(database, Path(directory))
            self.assertIn("renumber", str(raised.exception))

    def test_drift_is_detected_before_any_pending_migration_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write(directory, "001_first.sql", "CREATE TABLE t (id integer);\n")
            database = FakeDatabase()
            migrate.migrate(database, Path(directory))
            path.write_text("CREATE TABLE t (id bigint);\n", encoding="utf-8", newline="\n")
            write(directory, "002_second.sql")
            scripts = len(database.scripts)
            with self.assertRaises(migrate.MigrationError):
                migrate.migrate(database, Path(directory))
            self.assertNotIn("002", database.applied)
            # Bootstrap only: the pending migration was never sent.
            self.assertEqual(len(database.scripts), scripts + 1)


if __name__ == "__main__":
    unittest.main()
