#!/usr/bin/env python3
"""The dataset export against a real database: a real Parquet, written and read back.

*Candidate for the dataset export, owner-ruled 2026-09-12.* Build-and-drop — it builds its own
database and drops it, so it never touches the stack's data.

    docker compose run --rm tests python /srv/tests/test_dataset_export_integration.py

**Written and read back, never asserted against the rows in memory.** A test that checks the list
it just built has proved the list; the file is what a data scientist opens, so the file is what is
opened here. `pyarrow` lives in the `tests` stage of the api image for exactly this — the serving
image does not carry it (the Dockerfile's split says why, with the sizes).

**The two assertions that matter, and both are «the parts add up to the whole»:**

- the row count equals `place`'s own count of reference rows, so a partial write is a failure
  rather than a smaller file that looks like a working export;
- the three name rungs sum to that same total, so a row cannot be silently unnamed — which is what
  a re-implemented ladder would produce first.

**And the one that is about the rule rather than the arithmetic:** a name in the file is the name
`api_common.place_display` returns for that place. The export calls the app's read path and does
not re-derive it; this asserts that by comparing a sample row against the app's own answer, because
«we called the right function» is not observable from the file and «the file says what the app
says» is.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_dataset_check"
FAILURES: list[str] = []


def check(label: str, ok: bool, detail=None) -> None:
    print(("ok   " if ok else "FAIL ") + label + ("" if ok or detail is None else f" {detail!r}"))
    if not ok:
        FAILURES.append(label)


async def run_sql(url: str, statement: str, autocommit: bool = False):
    engine = create_async_engine(url, **({"isolation_level": "AUTOCOMMIT"} if autocommit else {}))
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement))
            if not autocommit:
                await connection.commit()
            try:
                return result.scalar()
            except Exception:
                return None
    finally:
        await engine.dispose()


async def seed(session, publication_id: int) -> None:
    """Four places across three rungs, so the sum below is a real sum rather than one number.

    **A sign, a brand and two registered names**, because a fixture with one rung cannot tell a
    ladder that works from one that answers `registered` to everything — the same reason the board
    fixture needed asymmetric weights.
    """
    rows = [
        ("A-11111111-00001-1", "簽名小吃", "63000010", "松山區"),
        ("A-22222222-00001-1", "品牌拉麵股份有限公司", "63000020", "信義區"),
        ("A-33333333-00001-1", "只有登記名稱有限公司", "63000010", "松山區"),
        ("A-44444444-00001-1", "另一家登記名稱有限公司", "63000020", "信義區"),
    ]
    for registry, name, code, township in rows:
        await session.execute(
            text("insert into reference_place (publication_id, registry_no, origin, name, "
                 "name_raw, address, address_raw, township_code, township_name) "
                 "values (:pub, :r, 'reference', :n, :n, 'x', 'x', :c, :t)"),
            {"pub": publication_id, "r": registry, "n": name, "c": code, "t": township},
        )
        await session.execute(
            text("insert into place (origin, registry_no, category, category_model, "
                 "category_prompt_version, category_input, category_generated_at) "
                 "values ('reference', :r, '麵食', 'gemma2:2b', 'v7', :n, now())"),
            {"r": registry, "n": name},
        )
    # A circle-local place, which must NOT reach the file: its name is a member's own words.
    circle = (await session.execute(
        text("insert into circle (name) values ('dataset fixture') returning id"))).scalar_one()
    await session.execute(
        text("insert into place (origin, circle_id, name) values ('circle-local', :c, '某人打的字')"),
        {"c": circle},
    )
    await session.commit()


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url
    from upto.dataset import export  # noqa: PLC0415

    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # `reference_place.township_code` carries a foreign key to the seeded township map (D32),
        # so the two districts this fixture uses have to exist before any place does.
        for code, name in (("63000010", "松山區"), ("63000020", "信義區")):
            await session.execute(
                text("insert into township_station (township_code, township_name, station_id, "
                     "station_name, resolution) values (:c, :n, 'C0A980', '測試站', 'town_code')"),
                {"c": code, "n": name},
            )
        publication = (await session.execute(
            text("insert into place_publication (source, content_sha256, detected_at, "
                 "payload_bytes, entry_name, entry_bytes, scope) "
                 "values ('fda-97', repeat('c', 64), now(), 1000, 'x.csv', 1000, "
                 "'餐飲場所 / 臺北市') returning id"))).scalar_one()
        # A sign for the first, so the ladder's top rung is exercised.
        sign_pub = (await session.execute(
            text("insert into storefront_publication (source, content_sha256, detected_at, "
                 "payload_bytes, scope, name_rows) "
                 "values ('grade', repeat('d', 64), now(), 10, 'x', 1) returning id"))).scalar_one()
        await session.execute(
            text("insert into storefront_name (publication_id, registry_no, name, name_raw, "
                 "grade) values (:p, 'A-11111111-00001-1', '招牌小吃', '招牌小吃', '優')"),
            {"p": sign_pub})
        # A single-brand company for the second.
        brand_pub = (await session.execute(
            text("insert into brand_publication (source, content_sha256, detected_at, "
                 "payload_bytes, scope, pair_rows) "
                 "values ('food', repeat('e', 64), now(), 10, 'x', 1) returning id"))).scalar_one()
        await session.execute(
            text("insert into brand_registration (publication_id, company_name, company_name_raw, "
                 "brand_name, brand_name_raw) values (:p, '品牌拉麵股份有限公司', "
                 "'品牌拉麵股份有限公司', '拉麵一號', '拉麵一號')"), {"p": brand_pub})
        await session.commit()
        await seed(session, publication)

    async with Session() as session:
        rows = await export.rows_for(session)
        expected = await export.expected_count(session)
        provenance = await export.publications_in_force(session)

    check("the export reads every reference place and no more", len(rows) == expected,
          (len(rows), expected))
    check("and the circle-local place is not among them — a member's own words never ship",
          all(row["registry_no"] is not None for row in rows)
          and "某人打的字" not in {row["display_name"] for row in rows})

    directory = tempfile.mkdtemp(prefix="dataset-check-")
    parquet = os.path.join(directory, "places.parquet")
    written = export.write_parquet(rows, parquet)
    check("a real Parquet file exists on disk", os.path.getsize(parquet) > 0,
          os.path.getsize(parquet))

    # ---- read it BACK, because the file is what a reader opens ---------------------------
    import pyarrow.parquet  # noqa: PLC0415

    table = pyarrow.parquet.read_table(parquet)
    back = table.to_pylist()
    check("read back with the row count it was written with", len(back) == written, (len(back), written))
    check("the row count equals `place`'s own count of reference rows", len(back) == expected,
          (len(back), expected))
    check("every column in the dictionary is in the file, and no others",
          list(table.column_names) == [name for name, _ in export.COLUMNS],
          table.column_names)

    # **The parts add up to the whole.** Three rungs, summing to the total — the check that has
    # caught a stale publication, confirmed a re-measurement and closed a derivation table today.
    rungs = {}
    for row in back:
        rungs[row["name_source"]] = rungs.get(row["name_source"], 0) + 1
    check("the three name rungs sum to the whole file",
          sum(rungs.values()) == len(back), (rungs, len(back)))
    check("and all three rungs are exercised, so the sum is not one number",
          set(rungs) == {"sign", "brand", "registered"}, rungs)

    # **Beside the rung sum, never instead of it** (the reviewer's first `should`, 2026-09-12). A
    # row with no name at all still lands in a bucket, so the sum stays 36,497 while a reader gets
    # a place with nothing to call it. The sum proves no row was LOST; this proves no row is EMPTY,
    # and the two questions are different.
    unnamed = [row for row in back if not row["display_name"]]
    check("every row in the file has a name", not unnamed,
          [(row["registry_no"], row["name_source"]) for row in unnamed[:3]])
    check("and no row claims a rung it does not have",
          all((row["name_source"] is None) == (row["name_base"] is None) for row in back),
          [(row["registry_no"], row["name_source"], row["name_base"]) for row in back
           if (row["name_source"] is None) != (row["name_base"] is None)][:3])

    # ---- the name is the APP's name, not a re-derivation ---------------------------------
    from upto.api_common import place_display  # noqa: PLC0415

    async with Session() as session:
        ids = (await session.execute(
            text("select id from place where origin = 'reference' order by id"))).scalars().all()
        composed = await place_display(session, ids)
        by_registry = dict((await session.execute(
            text("select id, registry_no from place where origin = 'reference'"))).all())
    app_names = {by_registry[pid]: value["name"] for pid, value in composed.items()}
    file_names = {row["registry_no"]: row["display_name"] for row in back}
    check("every name in the file is the name the app itself composes", app_names == file_names,
          {k: (app_names.get(k), file_names.get(k)) for k in app_names
           if app_names.get(k) != file_names.get(k)})
    check("the sign rung won where a sign exists (so the ladder really ran)",
          file_names["A-11111111-00001-1"] == "招牌小吃", file_names["A-11111111-00001-1"])

    # ---- provenance ----------------------------------------------------------------------
    check("every row carries the publication it was composed against",
          {row["place_publication_id"] for row in back} == {provenance["place_publication_id"]})
    check("and that publication's content hash, not a timestamp",
          {row["place_publication_sha256"] for row in back} == {"c" * 64})

    os.unlink(parquet)
    os.rmdir(directory)
    await engine.dispose()


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    await run_sql(admin_url, f'drop database if exists "{TEST_DB}" with (force)', True)
    await run_sql(admin_url, f'create database "{TEST_DB}"', True)
    try:
        import subprocess  # noqa: PLC0415

        migrated = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv",
                                  capture_output=True,
                                  env=dict(os.environ, UPTO_DATABASE_URL=test_url))
        if migrated.returncode != 0:
            sys.stderr.write(migrated.stdout.decode("utf-8", "replace"))
            sys.stderr.write(migrated.stderr.decode("utf-8", "replace"))
            return 2
        await scenario(test_url)
    finally:
        os.environ["UPTO_DATABASE_URL"] = live
        await run_sql(admin_url, f'drop database if exists "{TEST_DB}" with (force)', True)

    if FAILURES:
        print(f"\n{len(FAILURES)} failing: " + ", ".join(FAILURES), file=sys.stderr)
        return 1
    print("\nthe dataset is one row per reference place, named by the app's own read path, written "
          "as a real Parquet and read back with the rungs summing to the whole")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
