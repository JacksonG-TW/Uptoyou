"""One temporary database per build-and-drop test, made the same way for all of them (2026-10-10).

Until this file, `with_temporary_database` was copied into 37 tests and the copies had drifted:
about half ran the second `alembic upgrade head` that proves the migrations are idempotent, the
rest did not, and the drop at the end differed in whether it forced. One helper, one behaviour:

1. drop any leftover database of this name, and create it;
2. `alembic upgrade head` **twice** — the second run must apply nothing (a migration that runs again
   is not idempotent, and the box re-runs `migrate` on every deploy);
3. the test's own setup, then its scenario;
4. drop the database, forcing out any connection the scenario left open — even when it failed.

Runs inside the `tests` service (the owner's credential, D115), as every build-and-drop test does.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


class CouldNotStart(Exception):
    """Raised by a scenario that could not begin (its server never came up): the helper says so and
    returns 2, the build-and-drop tests' «not run» code. A scenario's RETURN value is never read —
    on 2026-10-10 a scenario that returned a publication id became the process's exit code."""


def urls(test_db: str) -> tuple:
    """(the admin url, the test database's url), both from `UPTO_DATABASE_URL`."""
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + test_db


async def _admin(admin_url: str, statement: str) -> None:
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await admin.dispose()


def migrate(environment: dict) -> Optional[tuple]:
    """`alembic upgrade head` twice. None on success, else `(exit code, what to print)`:
    2 when alembic itself failed (the test could not run), **1 when the second run applied a
    migration** — that is a defect the test found, not a test that could not run (the reviewer's
    should, 2026-10-10: it was an assert's 1 in the copies that checked it)."""
    for attempt in (1, 2):
        done = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv", env=environment,
                              capture_output=True)
        said = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        if done.returncode != 0:
            return 2, said
        if attempt == 2 and "Running upgrade" in said:
            return 1, "the second `alembic upgrade head` ran a migration — not idempotent:\n" + said
    return None


async def with_temporary_database(
    test_db: str,
    scenario: Callable[[str, dict], Awaitable[object]],
) -> int:
    """Make `test_db`, migrate it twice, run `scenario(test_url, environment)`, drop it.

    Returns 1 when the second migration applies anything (not idempotent), 2 when the database
    cannot be migrated or the scenario raises `CouldNotStart`, else 0.
    What the scenario returns is ignored. A failing check inside it raises or prints as it always
    did; the drop happens either way.
    """
    admin_url, test_url = urls(test_db)
    await _admin(admin_url, 'drop database if exists "{}" with (force)'.format(test_db))
    await _admin(admin_url, 'create database "{}"'.format(test_db))
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        failed = migrate(environment)
        if failed is not None:
            code, said = failed
            print(said, file=sys.stderr)
            return code
        try:
            await scenario(test_url, environment)
        except CouldNotStart as reason:
            print(reason, file=sys.stderr)
            return 2
        return 0
    finally:
        await _admin(admin_url, 'drop database if exists "{}" with (force)'.format(test_db))
