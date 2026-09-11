#!/usr/bin/env python3
"""An API process refuses to serve a database that is not at the revision its code ships against.

*Written 2026-09-11 with candidate 15, on the evaluator's catch.* When `migrate` left the stack's
boot (owner 「一次」) so that N instances cannot race one migration, `api`'s
`depends_on: {migrate: service_completed_successfully}` went with it, and D115's «a failed
migration stops the API one container earlier» went with that on every path except the deploy.
`upto.schema_guard` put the guarantee back in the code.

**This is the half `test_schema_guard.py` cannot reach, and the two are not interchangeable.**
Host-side, `decide` is exercised on pairs of strings and proves the rule. Here a real uvicorn is
started against a real database that has been rolled back one revision, and what is asserted is
the thing only a process can demonstrate: it **exits**, with the code compose reads, having said
which two revisions it was between. A rule that is right in a unit test and never reached from
`main.py` is the failure this file exists for — and it is not hypothetical, because the wiring
between the two is exactly one `await` in a lifespan.

**It also asserts the boring direction**, that a database at head serves, because a guard that
refuses everything passes every test above and ships a stack that will not boot.

    docker compose run --rm tests python /srv/tests/test_schema_guard_integration.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys

# **Async everywhere, including the two administrative statements.** The api image installs
# `asyncpg` and no libpq client at all (H1), so `create_engine` on a `postgresql://` URL dies
# `No module named 'psycopg2'` — measured here before this line existed.
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DB = "upto_schema_guard_check"
PORT = 8904

FAILURES: list[str] = []


def check(label: str, ok: bool, detail=None) -> None:
    print(("ok   " if ok else "FAIL ") + label + ("" if ok or detail is None else f" {detail!r}"))
    if not ok:
        FAILURES.append(label)


def alembic(url: str, *argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["alembic", *argv], cwd="/srv", capture_output=True,
                          env=dict(os.environ, UPTO_DATABASE_URL=url))


async def run_sql(url: str, statement: str, autocommit: bool = False):
    engine = create_async_engine(url, **({"isolation_level": "AUTOCOMMIT"} if autocommit else {}))
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement))
            # A `create database` returns no rows and `.scalar()` on it raises
            # `ResourceClosedError` — one helper for both shapes, so ask before taking a value.
            return result.scalar() if result.returns_rows else None
    finally:
        await engine.dispose()


async def stored_revision(url: str) -> str | None:
    return await run_sql(url, "select version_num from alembic_version")


def start_api(url: str) -> subprocess.Popen:
    return subprocess.Popen(
        ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd="/srv/src", env=dict(os.environ, UPTO_DATABASE_URL=url),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def wait_for_exit(process: subprocess.Popen, seconds: float = 30) -> tuple[int | None, str]:
    try:
        output, _ = process.communicate(timeout=seconds)
        return process.returncode, output
    except subprocess.TimeoutExpired:
        process.kill()
        output, _ = process.communicate()
        return None, output


async def main() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head_, _, _ = live.rpartition("/")
    admin_url, test_url = head_ + "/postgres", head_ + "/" + TEST_DB

    await run_sql(admin_url, f'drop database if exists "{TEST_DB}" with (force)', True)
    await run_sql(admin_url, f'create database "{TEST_DB}"', True)

    try:
        upgraded = alembic(test_url, "upgrade", "head")
        if upgraded.returncode != 0:
            sys.stderr.write(upgraded.stdout.decode("utf-8", "replace"))
            sys.stderr.write(upgraded.stderr.decode("utf-8", "replace"))
            return 2
        at_head = await stored_revision(test_url)
        check("a freshly migrated database reports a revision", at_head is not None, at_head)

        # --- one revision behind: the state the deploy path prevents and a plain `up` did not ---
        rolled = alembic(test_url, "downgrade", "-1")
        if rolled.returncode != 0:
            sys.stderr.write(rolled.stdout.decode("utf-8", "replace"))
            sys.stderr.write(rolled.stderr.decode("utf-8", "replace"))
            return 2
        behind = await stored_revision(test_url)
        check("and one `downgrade -1` moves it", behind is not None and behind != at_head,
              (behind, at_head))

        code, log = wait_for_exit(start_api(test_url))
        # **The exit code is the contract, not the log line.** `docker compose up --wait` reads a
        # process that ends; a stack whose API logged an error and kept answering nothing is the
        # outcome `os._exit` was chosen over a raised exception to avoid.
        check("an API started against a database one revision behind EXITS", code is not None, log[-400:])
        check("and it exits 3, which is the code compose sees", code == 3, code)
        # Both revisions in the log, because «the schema is wrong» sends a reader looking for
        # which one, and the pair is the whole of the fix.
        check("naming the revision the database is at", behind in log, log[-400:])
        check("and the revision this code ships against", at_head in log, log[-400:])
        check("and naming the command that fixes it", "run --rm migrate" in log, log[-400:])
        # It must not have quietly fixed the schema on the way past: a process that migrates what
        # it finds is a process that races its N siblings, which is the whole of owner 「一次」.
        after = await stored_revision(test_url)
        check("while leaving the schema exactly as it found it (it must never migrate)",
              after == behind, after)

        # --- and the boring direction, without which every assertion above is free ------------
        alembic(test_url, "upgrade", "head")
        serving = start_api(test_url)
        try:
            import httpx  # noqa: PLC0415
            answered = None
            for _ in range(80):
                if serving.poll() is not None:
                    break
                try:
                    answered = httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=2).status_code
                    break
                except httpx.TransportError:
                    await asyncio.sleep(0.25)
            check("an API against a database at head serves", answered == 200,
                  answered if serving.poll() is None else ("exited", serving.poll()))
        finally:
            serving.terminate()
            serving.wait(timeout=10)
    finally:
        await run_sql(admin_url, f'drop database if exists "{TEST_DB}" with (force)', True)

    if FAILURES:
        print(f"\n{len(FAILURES)} failing: " + ", ".join(FAILURES), file=sys.stderr)
        return 1
    print("\nthe guarantee `depends_on` used to buy is back in the code: an API process that finds "
          "a schema it was not written against names both revisions and exits 3 rather than "
          "serving, and it does not migrate what it finds")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
