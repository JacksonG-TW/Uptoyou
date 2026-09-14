"""The API refuses to serve a database whose schema is not the one this code ships against.

*Written 2026-09-11 with candidate 15, on the evaluator's catch.* When `migrate` left the stack's
boot (owner 「一次」) so that N instances cannot race one migration, `api`'s
`depends_on: {migrate: service_completed_successfully}` went with it — and **D115's «a failed
migration stops the API one container earlier» went with that**. On the deploy path the guarantee
survived, because `pull-deploy.sh` runs the schema step under `set -e` and stops. Everywhere else
— a plain `docker compose up -d --wait` on any development machine — there was suddenly nothing at
all between an API process and a schema nobody had applied.

**So the guard moves into the code, which is the form this project keeps choosing for a reason.**
A step in a script is a promise that holds where somebody wrote it; a check at startup holds
everywhere the code runs, including the paths nobody thought about — the same argument as a
whitelist over a convention (D55), a foreign key over a check (0024), and a query that starts at
the right table so the wrong answer is unreachable (D114).

**What it does.** Reads `alembic_version` and compares it with the head this source tree carries.
Equal: nothing is logged and the API serves. Different or absent: **both revisions are logged and
the process exits non-zero**, so `docker compose up --wait` fails loudly rather than a member
meeting the mismatch inside a request. The cost is one query at boot.

**What it deliberately does NOT do: migrate.** That is the whole point of the ruling it belongs to
— a process that fixes the schema it finds is a process that races N of its siblings.

**Amended 2026-09-11, the same day, on the reviewer's re-read — and the amendment is the difference
between this file working and this file reading as though it worked.** The guard runs on the
server's own session, which connects as `upto_api`, and that role held no grant on
`alembic_version`. So the read was refused, `check_or_exit`'s broad `except` logged «could not be
checked — serving anyway», and **the guard never fired once in the product**. Two changes: revision
0043 grants `upto_api` SELECT on that table, and a read that is *refused* now exits 3 instead of
warning — being unable to see the revision says nothing about whether the schema matches, so it
cannot be treated as «probably fine». A transport failure still warns and serves, because a
database that is merely unreachable is `db`'s healthcheck to report.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

_log = logging.getLogger(__name__)

#: Where the migrations live relative to this file: `src/upto/…` → `api/migrations/versions`.
VERSIONS = Path(__file__).resolve().parents[2] / "migrations" / "versions"

_REVISION = re.compile(r"^revision(?::\s*str)?\s*=\s*[\"']([^\"']+)", re.M)
_DOWN = re.compile(r"^down_revision(?::\s*[^=]+)?\s*=\s*[\"']([^\"']+)", re.M)


class SchemaMismatch(RuntimeError):
    """The database is not at the revision this code was written against."""


def head_revision(versions: Path | None = None) -> str:
    """The one revision nothing else points back to — read from the files, not from Alembic.

    **Parsed rather than imported** so this costs no Alembic dependency at API startup and cannot
    be affected by a half-configured `alembic.ini`. If the tree ever grows two heads this raises
    rather than guessing, because «which head» is a question a guard must not answer by itself.
    """
    directory = versions or VERSIONS
    revisions, downs = set(), set()
    for path in directory.glob("*.py"):
        text_ = path.read_text(encoding="utf-8")
        found = _REVISION.search(text_)
        if found:
            revisions.add(found.group(1))
        down = _DOWN.search(text_)
        if down:
            downs.add(down.group(1))
    heads = revisions - downs
    if len(heads) != 1:
        raise SchemaMismatch(
            "this tree has {} migration heads ({}) — a guard cannot choose between them"
            .format(len(heads), ", ".join(sorted(heads)) or "none")
        )
    return heads.pop()


def decide(found: str | None, expected: str) -> str:
    """The whole rule, with no database and no driver anywhere near it. Returns `expected`.

    **Split out from `assert_current` on purpose, and the split is the testability.** What this
    guard *decides* — current serves, behind refuses, ahead refuses, never-migrated refuses, and
    what each refusal has to say — depends on two strings and nothing else. Kept inside the async
    function it could only be exercised through a session, which drags SQLAlchemy in, which drags
    every case into the build-and-drop tempo for a rule that needs neither. So the rule is here and
    host-side; `assert_current` below is the two lines that fetch the string and hand it over, and
    *that* wiring is what the build-and-drop case proves.
    """
    if found is None:
        raise SchemaMismatch(
            "the database has no alembic_version row — it has never been migrated. This code "
            "expects {}. Run `docker compose run --rm migrate` before starting the stack."
            .format(expected)
        )
    if found != expected:
        raise SchemaMismatch(
            "the database is at revision {} and this code ships against {}. Run "
            "`docker compose run --rm migrate` — the schema is applied once per version, from the "
            "deploy, and never by an API instance (owner 「一次」, 2026-09-11)."
            .format(found, expected)
        )
    return expected


async def assert_current(session, versions: Path | None = None) -> str:
    """Read the database's revision and put it to `decide`. Raises `SchemaMismatch`, or returns it.

    The import is local so this module stays importable with the standard library alone — see
    `decide` for why that matters to the tests.
    """
    from sqlalchemy import text  # noqa: PLC0415

    found = await session.scalar(text("select version_num from alembic_version"))
    return decide(found, head_revision(versions))


async def check_or_exit(session_factory_) -> None:
    """The startup call. Serves in silence when current; logs both revisions and exits otherwise.

    **`os._exit` rather than a raised exception**, and the reason is the failure this guard exists
    for: an exception inside a lifespan is caught by uvicorn, which logs it and — depending on the
    path — can leave a process that answers nothing while `--wait` keeps waiting for a healthcheck
    that will never pass. A non-zero exit is the signal compose understands, so the stack fails at
    the container that is wrong, loudly, which is what `depends_on` used to buy.
    """
    try:
        async with session_factory_()() as session:
            await assert_current(session)
    except SchemaMismatch as mismatch:
        _log.error("schema: %s", mismatch)
        os._exit(3)  # noqa: SLF001 — see the docstring: the exit code is the contract here
    except Exception as failure:  # noqa: BLE001
        # **The split below is the reviewer's catch of 2026-09-11, and without it this guard was
        # decorative.** Every startup in the product took this branch: the server connects as
        # `upto_api`, which held no grant on `alembic_version`, so the read raised
        # `InsufficientPrivilegeError` — an ordinary exception — and the guard logged a warning and
        # served whatever schema it found. Revision 0043 grants that SELECT; this decides what
        # happens when the read fails anyway.
        #
        # **A guard that cannot read its own answer has not passed, it has failed to ask.** Being
        # unable to see `alembic_version` — no privilege, or no table — says nothing about whether
        # the schema matches, so it cannot be treated as «probably fine». It exits, and names what
        # stopped it, because the alternative is the state that was live until today: a process
        # that reports healthy while the one check standing between it and a wrong schema never ran.
        #
        # **A transport failure is different in kind and keeps the old behaviour.** A database that
        # cannot be reached at all is `db`'s healthcheck to report, not this guard's, and turning a
        # slow start into a refusal would make every cold boot a deploy failure.
        # **Refused at the door: the role's password is wrong, or the role does not exist**
        # (the reviewer's should on candidate 22, 2026-09-14, from CI run 34824356992). That run
        # never created the roles, every connection as `upto_api` was refused, and this branch
        # logged «could not be checked — serving anyway» while `/health` said the database was
        # unreachable, which was false. A process that cannot log in reads nothing, so no wrong
        # schema can be served; but it is a configuration fault a restart will never fix, and it
        # gets **its own exit code, 4**, because its fix is not exit 3's: not `migrate`'s schema,
        # but a password in `.env` and the role in the database disagreeing.
        if _is_refused_credential(failure):
            _log.error(
                "schema: the database refused the server's role %s (%s) — refusing to serve. Its "
                "password in app/.env (UPTO_API_DB_PASSWORD) and the role in the database disagree, "
                "or the role does not exist. `docker compose run --rm migrate` creates the roles and "
                "sets their passwords from .env.",
                _role_of(session_factory_), type(_innermost(failure)).__name__,
            )
            os._exit(4)  # noqa: SLF001 — its own code: the fix differs from exit 3's
        if _is_unreadable(failure):
            _log.error(
                "schema: alembic_version could not be READ (%s) — refusing to serve. The guard "
                "reads it as the server's own role; revision 0043 grants that SELECT to upto_api. "
                "Run `docker compose run --rm migrate`.",
                failure,
            )
            os._exit(3)  # noqa: SLF001 — same contract as the mismatch above
        _log.warning("schema: could not be checked (%s) — serving anyway", failure)


def _chain(failure: BaseException):
    """The exception and everything behind it, by `__cause__` and then `__context__`.

    **Both links, because the two paths differ** (the reviewer's note): a failed query is wrapped by
    SQLAlchemy with `raise … from`, which sets `__cause__`; a failed *connect* can surface with the
    driver's error only on `__context__`. Bounded, so a cycle cannot hang a startup.
    """
    seen, current = 0, failure
    while current is not None and seen < 10:
        yield current
        current, seen = (current.__cause__ or current.__context__), seen + 1


def _innermost(failure: BaseException) -> BaseException:
    last = failure
    for last in _chain(failure):
        pass
    return last


def _is_refused_credential(failure: BaseException) -> bool:
    """Did the database refuse the role itself — a wrong password, or a role that does not exist?

    asyncpg raises **InvalidPasswordError** (a subclass of InvalidAuthorizationSpecificationError)
    for both, because PostgreSQL answers «password authentication failed» for a missing role too, on
    purpose, so a client cannot probe which role names exist. Matched by name, like `_is_unreadable`,
    so this module stays importable with the standard library alone.
    """
    return any(type(link).__name__ in ("InvalidPasswordError", "InvalidAuthorizationSpecificationError")
               for link in _chain(failure))


def _role_of(session_factory_) -> str:
    """The role name the server connects as, for the log line — never the password."""
    try:
        return session_factory_().kw["bind"].url.username or "(unknown)"
    except Exception:  # noqa: BLE001 — a log line must not become a second failure
        return "(unknown)"


def _is_unreadable(failure: BaseException) -> bool:
    """Is this «I asked and was refused» rather than «I could not reach the database»?

    **Matched on the driver's own exception names, walked down the `__cause__` chain**, because
    SQLAlchemy wraps asyncpg's `InsufficientPrivilegeError` in a `ProgrammingError` whose type says
    nothing. Matching names rather than importing asyncpg keeps this module importable with the
    standard library alone, which is what lets `decide` and this rule be tested host-side.

    The two that count: **InsufficientPrivilege** (the role may not read the table — what was live
    in the product until 2026-09-11) and **UndefinedTable** (there is no `alembic_version` at all,
    which is a database nothing has ever migrated, not a database that is merely unreachable).
    """
    return any(type(link).__name__ in ("InsufficientPrivilegeError", "UndefinedTableError")
               for link in _chain(failure))
