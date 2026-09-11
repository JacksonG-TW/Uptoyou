#!/usr/bin/env python3
"""The API refuses to serve a schema that is not the one it ships against. Host-side, no database.

*Written 2026-09-11 with candidate 15, on the evaluator's catch.* When `migrate` left the stack's
boot so N instances cannot race one migration, `api`'s `depends_on` went with it — and so did
D115's «a failed migration stops the API one container earlier» on every path except the deploy.
`schema_guard` puts the guarantee back in the code; this asserts what it decides.

**The head is parsed from the migration files**, so these cases build a fake versions directory
rather than mocking Alembic: what is asserted is the rule, on inputs a real tree could have.

**Host-side means the standard library alone**, so nothing here imports SQLAlchemy and nothing
here has a session. `upto.schema_guard.decide` holds the whole rule for that reason. The half this
file cannot reach — that the API actually asks the database and actually exits 3 — is
`test_schema_guard_integration.py`, and neither file is sufficient without the other.

    python3 app/api/tests/test_schema_guard.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from upto.schema_guard import SchemaMismatch, _is_unreadable, decide, head_revision  # noqa: E402


def chain(directory: Path, revisions: list[str]) -> None:
    """Write a linear migration chain: 0001 ← 0002 ← … Each file carries only what is read."""
    previous = None
    for revision in revisions:
        body = 'revision = "{}"\ndown_revision = {}\n'.format(
            revision, '"{}"'.format(previous) if previous else "None")
        (directory / "{}_x.py".format(revision)).write_text(body, encoding="utf-8")
        previous = revision


class TheHeadIsTheOneNothingPointsBackTo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="schema-guard-")
        self.dir = Path(self.tmp)

    def test_a_linear_chain_has_one_head(self):
        chain(self.dir, ["0001", "0002", "0003"])
        self.assertEqual(head_revision(self.dir), "0003")

    def test_two_heads_raise_rather_than_choosing(self):
        """**A guard must not answer «which head» by itself.** A tree with two heads is a mistake
        somebody made, and picking one would let the API serve against whichever branch sorted
        first — a wrong answer delivered confidently, which is the failure this file exists for."""
        chain(self.dir, ["0001", "0002"])
        (self.dir / "0003_other.py").write_text(
            'revision = "0003"\ndown_revision = "0001"\n', encoding="utf-8")
        with self.assertRaises(SchemaMismatch) as caught:
            head_revision(self.dir)
        self.assertIn("2 migration heads", str(caught.exception))

    def test_an_empty_directory_raises(self):
        with self.assertRaises(SchemaMismatch):
            head_revision(self.dir)

    def test_the_real_tree_has_exactly_one_head(self):
        """Not a fixture: the repository's own migrations, so a second head added by a merge fails
        here rather than at an instance's boot."""
        real = Path(__file__).resolve().parents[1] / "migrations" / "versions"
        self.assertRegex(head_revision(real), r"^\d{4}$")


class TheGuardDecides(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="schema-guard-")
        self.dir = Path(self.tmp)
        chain(self.dir, ["0001", "0002", "0003"])

    def run_guard(self, stored):
        """**No session, not even a stubbed one, and that is deliberate.** A fake session proves
        the fake session was called; the real question is what the guard decides about two
        revisions. `assert_current`'s remaining job — read `alembic_version`, hand the string to
        `decide` — is the one thing a stub cannot vouch for, so it is proven against a real
        database in `test_schema_guard_integration.py` instead."""
        return decide(stored, head_revision(self.dir))

    def test_a_current_database_passes_and_returns_the_revision(self):
        self.assertEqual(self.run_guard("0003"), "0003")

    def test_a_database_one_revision_behind_is_refused(self):
        """The case the deploy path is meant to prevent and a plain `up` no longer did."""
        with self.assertRaises(SchemaMismatch) as caught:
            self.run_guard("0002")
        message = str(caught.exception)
        # **Both revisions in the message**, because «the schema is wrong» sends a reader to look
        # for which one — and the answer is the whole of the fix.
        self.assertIn("0002", message)
        self.assertIn("0003", message)
        self.assertIn("run --rm migrate", message)

    def test_a_database_AHEAD_of_the_code_is_also_refused(self):
        """**The rollback case, and it is not symmetric with being behind.** Rolling the code back
        to an earlier image leaves the database at a newer revision; serving then means running
        code against columns it does not know about. Refusing says so instead."""
        with self.assertRaises(SchemaMismatch):
            self.run_guard("0004")

    def test_a_database_that_was_never_migrated_says_so_in_those_words(self):
        with self.assertRaises(SchemaMismatch) as caught:
            self.run_guard(None)
        self.assertIn("never been migrated", str(caught.exception))


class AskingAndBeingRefusedIsNotPassing(unittest.TestCase):
    """`_is_unreadable` — the rule added 2026-09-11 after the guard was found never to fire.

    The server connects as `upto_api`, which held no grant on `alembic_version`, so the read raised
    an ordinary exception and the broad `except` served anyway. **Being refused the answer says
    nothing about whether the schema matches**, so it must exit; being unable to reach the database
    at all is `db`'s healthcheck to report and must not. A pure function on an exception chain, so
    it is tested here and needs no driver.
    """

    @staticmethod
    def _wrapped(name):
        """SQLAlchemy wraps the driver's error, so the chain is what has to be walked."""
        inner = type(name, (Exception,), {})("permission denied for table alembic_version")
        outer = RuntimeError("(sqlalchemy...ProgrammingError) ...")
        outer.__cause__ = inner
        return outer

    def test_a_refused_read_is_unreadable(self):
        self.assertTrue(_is_unreadable(self._wrapped("InsufficientPrivilegeError")))

    def test_a_missing_table_is_unreadable(self):
        """A database with no `alembic_version` at all has never been migrated — not unreachable."""
        self.assertTrue(_is_unreadable(self._wrapped("UndefinedTableError")))

    def test_a_transport_failure_is_NOT(self):
        """The one that must keep warning and serving, or every cold boot is a deploy failure."""
        self.assertFalse(_is_unreadable(self._wrapped("ConnectionDoesNotExistError")))
        self.assertFalse(_is_unreadable(OSError("connection refused")))

    def test_the_walk_terminates_on_a_cycle(self):
        """A chain that points at itself must not hang the boot it was added to protect."""
        one = RuntimeError("a")
        one.__cause__ = one
        self.assertFalse(_is_unreadable(one))


if __name__ == "__main__":
    unittest.main(verbosity=2)
