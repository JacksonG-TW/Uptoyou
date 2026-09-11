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
        # A database that cannot be reached at all is `db`'s healthcheck to report, not this
        # guard's — it must not turn a slow start into a refusal.
        _log.warning("schema: could not be checked (%s) — serving anyway", failure)
