#!/usr/bin/env python3
"""A15 / D115 — the four service roles reach exactly their boundary and no further.

Run inside the stack:
    docker compose exec api python /srv/tests/test_role_grants.py

Builds its own database and drops it, so it never touches the stack's data. The roles are
cluster-wide, so they are the live ones; the grants are the ones revision 0032 issues here.

**The assertion that matters most is the deny half.** Checking that `upto_ingest` can write a
publication proves the pipeline still works and nothing else. Checking that it **cannot read
`preference`** is the ruling: §3.0 and D14 say the pipeline never sees a person, and until A15 that
was a habit rather than a mechanism.

**The second most important thing here is DR-8: this test is shown able to fail.** A coverage check
that has never gone red is a check nobody has calibrated — the same rule H41's sampler and H50's
fixture both land on. So it creates a probe table inside a transaction, asserts the coverage check
reports that table as ungranted, and rolls back. If that assertion ever stops holding, the coverage
half above is decoration.
"""

import asyncio
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from upto import roles as role_map  # noqa: E402

TEST_DB = "upto_role_grants_check"
FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   {}".format(name))
    else:
        FAILURES.append(name)
        print("FAIL {} {}".format(name, detail))


async def granted(connection, role, table, privilege):
    return (
        await connection.execute(
            text("select has_table_privilege(:r, :t, :p)"),
            {"r": role, "t": table, "p": privilege},
        )
    ).scalar_one()


async def ungranted_tables(connection):
    """Every table in `public` that no service role can touch at all.

    This is the check that goes red when a table is added without its grants (D115's cost
    paragraph, H10 extended).

    **`alembic_version` used to be the one exception and is not one since revision 0043.** It is an
    ordinary row of the map now — `upto_api` holds SELECT on it, because the startup guard reads it
    as the server's own role and a table nobody may read is a table a guard cannot guard (the
    reviewer's re-read of candidate 15, 2026-09-11). `role_map.OWNER_ONLY` is empty, and this loop
    still consults it so that the next exception has to be argued in that tuple rather than here.
    """
    tables = (
        await connection.execute(
            text("select tablename from pg_tables where schemaname = 'public' order by tablename")
        )
    ).scalars().all()
    out = []
    for table in tables:
        if table in role_map.OWNER_ONLY:
            continue
        reachable = False
        for role in role_map.SERVICE_ROLES:
            if await granted(connection, role, table, "select"):
                reachable = True
                break
        if not reachable:
            out.append(table)
    return out


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url)
    grants = role_map.grants()

    async with engine.connect() as connection:
        # --- the map is issued: every privilege it names is actually held ------------------
        missing = []
        for role, tables in grants.items():
            for table, privileges in tables.items():
                for privilege in privileges:
                    if not await granted(connection, role, table, privilege):
                        missing.append((role, table, privilege))
        check("every grant the map names was issued by revision 0032", not missing, missing[:6])

        # --- the deny half, which is the ruling ---------------------------------------------
        leaks = []
        for table in role_map.INGEST_DENIED:
            for privilege in ("select", "insert", "update", "delete"):
                if await granted(connection, role_map.INGEST, table, privilege):
                    leaks.append((table, privilege))
        check("the pipeline can do NOTHING to a table that names a person (§3.0, D14)",
              not leaks, leaks[:6])

        # **The one a reader should check first.** If this line ever passes vacuously the whole
        # file is decoration, so the table is named rather than looped over.
        check("upto_ingest cannot read `preference`",
              not await granted(connection, role_map.INGEST, "preference", "select"))
        check("upto_ingest cannot read `member`",
              not await granted(connection, role_map.INGEST, "member", "select"))

        # H20's boundary is a GRANT now and the Python list is the second line.
        check("upto_lineage cannot read `weight_contribution`",
              not await granted(connection, role_map.LINEAGE, "weight_contribution", "select"))
        check("upto_lineage cannot read `preference`",
              not await granted(connection, role_map.LINEAGE, "preference", "select"))

        # The narrowest role in the product, and the one grant taken from the Done line's wording.
        check("upto_erasure may delete a preference",
              await granted(connection, role_map.ERASURE, "preference", "delete"))
        check("upto_erasure may READ weight_contribution — D24's pinned-version filter needs it",
              await granted(connection, role_map.ERASURE, "weight_contribution", "select"))
        check("but may not write it",
              not await granted(connection, role_map.ERASURE, "weight_contribution", "update"))
        check("and may not read a member",
              not await granted(connection, role_map.ERASURE, "member", "select"))

        # The API's own line: D115 gives it INSERT on `place` and never UPDATE.
        check("upto_api may insert a place (a circle-local proposal, live.py)",
              await granted(connection, role_map.API, "place", "insert"))
        check("and may not update one — the classifier's columns are the pipeline's",
              not await granted(connection, role_map.API, "place", "update"))
        check("upto_api reads the ledger and never writes it",
              await granted(connection, role_map.API, "ingest_run", "select")
              and not await granted(connection, role_map.API, "ingest_run", "insert"))

        # --- revision 0043: the guard can read its own answer, and nothing more --------------
        #
        # **The line that would have caught candidate 15's dead guard.** Until 2026-09-11 the api
        # could not read `alembic_version` at all, so `check_or_exit` took its «could not be
        # checked — serving anyway» branch on every startup in the product while the integration
        # test passed as the owner. Read-yes is the fix; the three write checks are the ruling —
        # Alembic's row is written once per version by the owner, from `migrate` (「一次」).
        check("upto_api may READ alembic_version — the startup guard's whole basis (0043)",
              await granted(connection, role_map.API, "alembic_version", "select"))
        for privilege in ("insert", "update", "delete"):
            check("and may not {} it — only `migrate` writes that row".format(privilege),
                  not await granted(connection, role_map.API, "alembic_version", privilege))
        for role in role_map.SERVICE_ROLES:
            if role == role_map.API:
                continue
            check("{} may not read alembic_version — one role needs it, not four".format(role),
                  not await granted(connection, role, "alembic_version", "select"))

        # --- A22: the backup role reads everything and writes nothing ----------------------
        #
        # **The pair that matters is read-yes / write-no on a table it was never named for.**
        # `pg_read_all_data` is granted at the cluster level (revision 0038), so the assertion is
        # not "the map lists it" — the map does not — but that a table nobody thought about is
        # readable and unwritable. `preference` is the right table to ask about: it is the most
        # sensitive thing here, the backup must contain it, and the role must not be able to
        # change one word of it.
        check("upto_backup may read `preference` — a backup that skips it is not a backup",
              await granted(connection, role_map.BACKUP, "preference", "select"))
        for table in ("preference", "weight_contribution", "place", "round"):
            for privilege in ("insert", "update", "delete"):
                check("upto_backup cannot {} `{}`".format(privilege, table),
                      not await granted(connection, role_map.BACKUP, table, privilege))

        # **H61 — and this is the assertion, not the comment above it.** `ungranted_tables` proves
        # "a table added without grants goes red" by asking whether ANY role in `SERVICE_ROLES`
        # can SELECT it. A role holding `pg_read_all_data` can SELECT everything, including the
        # table somebody forgets to grant next year — so putting this one in that tuple would make
        # the coverage check pass for ever, silently, and DR-8 below would be the only thing left
        # standing. The membership is therefore load-bearing and is pinned here.
        check("H61: upto_backup is NOT in SERVICE_ROLES — it would blind the coverage check",
              role_map.BACKUP not in role_map.SERVICE_ROLES, role_map.SERVICE_ROLES)
        check("and it is in no grants map either — its reach is a cluster role, not a table list",
              role_map.BACKUP not in role_map.grants())

        # --- coverage: no table is unreachable by every role -------------------------------
        orphans = await ungranted_tables(connection)
        check("every table in public is reachable by the role that owns its boundary",
              not orphans, orphans)

    # --- DR-8: the coverage check is shown able to fail ------------------------------------
    #
    # **A check that has never gone red is a check nobody has calibrated.** The probe table is
    # created and rolled back inside one transaction, so nothing survives it.
    async with engine.begin() as connection:
        await connection.execute(text("create table probe_no_grants (id bigint)"))
        orphans = await ungranted_tables(connection)
        check("DR-8: a new table with no grants makes the coverage check red",
              "probe_no_grants" in orphans, orphans)
        await connection.rollback()

    async with engine.connect() as connection:
        still = (
            await connection.execute(
                text("select count(*) from pg_tables where tablename = 'probe_no_grants'")
            )
        ).scalar_one()
    check("and the probe left nothing behind", still == 0, still)

    await engine.dispose()
    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        raise SystemExit(1)
    print(
        "\nA15/A22: the five roles hold exactly their boundary — the pipeline cannot see a "
        "person, the lineage tool cannot reach past its declaration, the erasure job can delete a "
        "preference and read nothing about anyone, the backup role reads every table and writes "
        "none and is deliberately outside the coverage check (H61), and a table added without "
        "grants goes red"
    )


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrate = subprocess.run(
            ["alembic", "upgrade", "head"], cwd="/srv", env=environment, capture_output=True
        )
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2
        await scenario(test_url)
    finally:
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text('drop database if exists "{}" with (force)'.format(TEST_DB))
            )
        await admin.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
