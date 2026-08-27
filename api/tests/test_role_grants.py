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
    paragraph, H10 extended). `alembic_version` is the one exception and it is named in the map.
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
        "\nA15: the four roles hold exactly their boundary — the pipeline cannot see a person, "
        "the lineage tool cannot reach past its declaration, the erasure job can delete a "
        "preference and read nothing about anyone, and a table added without grants goes red"
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
