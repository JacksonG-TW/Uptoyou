#!/usr/bin/env python3
"""D85's tax-registry source, against a real PostgreSQL and through the real CLI.

Run inside the stack:
    docker compose exec api python /srv/tests/test_business_tax_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**The runs go through `python -m upto.ingest.run_business_tax`, in a subprocess.** The sibling
integration tests call `ingest_once` directly, which is enough when a source has two exit codes;
this one has three, and an exit code is only real at a process boundary. `--file` and
`--force-parse` are exercised the way a human and the integration test respectively use them —
and never the way a DAG does, because a DAG may not use either.

What it holds:

  * the storage ruling — only 統編 in the **latest** place publication are stored, so a number
    that appears solely in an older publication is read past, and a reference row with no 統編
    offers nothing to join to;
  * the four 行業 pairs land positionally and an absent pair is NULL;
  * the ledger's seventh foreign key names the run that wrote the publication;
  * a second identical run is a silent no-change that never decompresses the file, and a forced
    re-parse writes no duplicate — the primary key refuses it, not the runner's good manners;
  * the disagreement path: content moved while the file's own stamp stood still is **exit 2**,
    with the rows already written and the alarm in the run row's `detail`.
"""

import asyncio
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.ingest import fia  # noqa: E402

TEST_DB = "upto_business_tax_check"
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")

STAMP = "14-AUG-26"

HEADER = (
    "營業地址,統一編號,總機構統一編號,營業人名稱,資本額,設立日期,組織別名稱,使用統一發票,"
    "行業代號,名稱,行業代號1,名稱1,行業代號2,名稱2,行業代號3,名稱3"
)

# The 統編 the latest place publication knows. 12345678 carries no 行業 pair beyond the first.
MATCHED = ("38965019", "61194605", "12345678")
# In the file, and in an *older* place publication only — the filter must read past it.
STALE = "99999999"
# In the file and in no publication of ours, which is the shape of 1.69M of its rows.
UNWANTED = "82554400"


def row(business_no, name, address, industries):
    cells = [
        '"{}"'.format(address), business_no, "", '"{}"'.format(name),
        "100000", "1040413", "獨資", "N",
    ]
    for code, industry_name in list(industries) + [("", "")] * (4 - len(industries)):
        cells.extend([code, industry_name])
    return ",".join(cells)


def tax_zip(rows, stamp=STAMP):
    body = ("﻿" + "\n".join([HEADER, stamp + "," * 15] + rows) + "\n").encode("utf-8")
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            zipfile.ZipInfo("BGMOPEN1.csv", date_time=(2026, 8, 14, 3, 30, 2)), body
        )
    handle.close()
    return handle.name


def rows_of(first_name="原味商行"):
    return [
        row("38965019", first_name, "南投縣中寮鄉永平路371號", (("472927", "豆類製品零售"),)),
        row(
            "61194605", "和興商店", "臺北市松山區八德路四段1號",
            (("472913", "菸酒零售"), ("471913", "雜貨店"), ("562100", "餐館")),
        ),
        row("12345678", "福利麵包食品有限公司", "臺北市信義區菸廠路88號B1", (("562100", "餐館"),)),
        row(UNWANTED, "啟輝環管企業社", "南投縣中寮鄉永平路51之1號", (("812100", "清潔服務"),)),
        row(STALE, "早就換版的店", "臺北市松山區舊路1號", (("562100", "餐館"),)),
    ]


def cli(arguments, test_url):
    """One real run of the module a scheduler calls. Exit codes are the point of the boundary."""
    environment = dict(
        os.environ,
        UPTO_DATABASE_URL=test_url,
        PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""),
        UPTO_INVOKED_BY="test",
    )
    return subprocess.run(
        [sys.executable, "-m", "upto.ingest.run_business_tax"] + arguments,
        env=environment,
        capture_output=True,
        text=True,
    )


async def seed(Session) -> None:
    """Two place publications, so the filter has an older one it must ignore."""
    async with Session() as session:
        older = (
            await session.execute(
                text(
                    "insert into place_publication (source, content_sha256, detected_at, "
                    "payload_bytes, entry_name, entry_bytes, scope) values "
                    "('fda-97', repeat('a', 64), now() - interval '30 days', 1000, 'x.csv', "
                    "1000, '餐飲場所 / 臺北市') returning id"
                )
            )
        ).scalar_one()
        latest = (
            await session.execute(
                text(
                    "insert into place_publication (source, content_sha256, detected_at, "
                    "payload_bytes, entry_name, entry_bytes, scope) values "
                    "('fda-97', repeat('b', 64), now(), 1000, 'x.csv', 1000, "
                    "'餐飲場所 / 臺北市') returning id"
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into reference_place (publication_id, registry_no, origin, name, "
                "name_raw, address, address_raw, business_no, township_code, township_name) "
                "values (:pub, :no, 'reference', :n, :n, 'x', 'x', :biz, null, null)"
            ),
            [
                {"pub": older, "no": "OLD-1", "n": "早就換版的店", "biz": STALE},
                {"pub": latest, "no": "A-1", "n": "原味商行", "biz": MATCHED[0]},
                {"pub": latest, "no": "A-2", "n": "和興商店", "biz": MATCHED[1]},
                # One business, two registered sites: the filter must ask for it once.
                {"pub": latest, "no": "A-3", "n": "福利麵包", "biz": MATCHED[2]},
                {"pub": latest, "no": "A-4", "n": "福利麵包 二店", "biz": MATCHED[2]},
                # No 統編 at all — nothing to offer this join, and not a defect.
                {"pub": latest, "no": "A-5", "n": "無統編的攤", "biz": None},
            ],
        )
        await session.commit()


async def stored_rows(Session, publication_id=None):
    statement = (
        "select business_no, tax_name, address, industry_code, industry_name, "
        "industry_code_1, industry_name_1, industry_code_2, industry_name_2, "
        "industry_code_3, industry_name_3, publication_id from business_tax_row"
    )
    if publication_id is not None:
        statement += " where publication_id = {}".format(int(publication_id))
    async with Session() as session:
        result = await session.execute(text(statement + " order by business_no"))
        return {row.business_no: row for row in result}


async def ledger(Session):
    async with Session() as session:
        result = await session.execute(
            text(
                "select outcome, rows_written, detail, invoked_by, "
                "business_tax_publication_id from ingest_run where source = :s order by id"
            ),
            {"s": fia.SOURCE},
        )
        return result.fetchall()


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    await seed(Session)

    first_file = tax_zip(rows_of())
    changed_file = tax_zip(rows_of(first_name="原味商行(更名)"))

    # 1 — the first run stores one publication and only the matched rows.
    first = cli(["--file", first_file], test_url)
    assert first.returncode == 0, first.stdout + first.stderr
    assert "stored publication" in first.stdout, first.stdout
    assert "5 rows scanned" in first.stdout, "the stamp row was counted as data: " + first.stdout

    rows = await stored_rows(Session)
    assert set(rows) == set(MATCHED), "stored {} — the filter is not the ruled one".format(set(rows))
    assert UNWANTED not in rows, "a row outside the reference list was stored"
    assert STALE not in rows, "a 統編 from an older place publication was stored"

    two_pairs = rows["61194605"]
    assert two_pairs.industry_code == "472913" and two_pairs.industry_name == "菸酒零售"
    assert two_pairs.industry_code_1 == "471913" and two_pairs.industry_name_1 == "雜貨店"
    assert two_pairs.industry_code_2 == "562100", "the third pair must keep its position"
    assert two_pairs.industry_code_3 is None and two_pairs.industry_name_3 is None
    one_pair = rows["38965019"]
    assert one_pair.industry_code_1 is None, "an absent pair is NULL, never an empty string"
    assert one_pair.address == "南投縣中寮鄉永平路371號", (
        "the REGISTERED address is stored as published — 13.7% of matched rows are outside 臺北市"
    )

    async with Session() as session:
        publication = (
            await session.execute(
                text(
                    "select id, file_stamp, scope, tax_rows, entry_name, payload_bytes "
                    "from business_tax_publication"
                )
            )
        ).fetchone()
    assert publication.file_stamp == date(2026, 8, 14), "row 2 is the file's own version signal"
    assert publication.scope == fia.SCOPE
    assert publication.tax_rows == 3
    assert publication.entry_name == "BGMOPEN1.csv"

    runs = await ledger(Session)
    assert [run.outcome for run in runs] == ["stored"], runs
    assert runs[0].business_tax_publication_id == publication.id, "the ledger's seventh key"
    assert runs[0].rows_written == 3
    assert runs[0].invoked_by == "test", "the invoker is carried rather than guessed"

    # 2 — the same bytes again. Nothing written, nothing parsed, and it is a success.
    again = cli(["--file", first_file], test_url)
    assert again.returncode == 0, again.stdout + again.stderr
    assert "no change" in again.stdout, again.stdout
    assert "was not parsed" in again.stdout, again.stdout
    runs = await ledger(Session)
    assert [run.outcome for run in runs] == ["stored", "no_change"], runs
    assert runs[1].business_tax_publication_id is None, "a no-op may attach no publication"
    assert runs[1].rows_written == 0

    # 3 — the same bytes with the short-circuit disabled, so what refuses the duplicate is the
    # primary key rather than this module's good behaviour.
    forced = cli(["--file", first_file, "--force-parse"], test_url)
    assert forced.returncode == 0, forced.stdout + forced.stderr
    assert "re-parsed into publication" in forced.stdout, forced.stdout
    assert len(await stored_rows(Session)) == 3, "a forced re-parse wrote duplicates"
    runs = await ledger(Session)
    assert [run.outcome for run in runs] == ["stored", "no_change", "no_change"], runs

    # 4 — content moved and the file's own stamp did not: exit 2, rows already written.
    disagreeing = cli(["--file", changed_file], test_url)
    assert disagreeing.returncode == 2, (
        "a stamp/hash disagreement must be exit 2, got {}\n{}".format(
            disagreeing.returncode, disagreeing.stdout + disagreeing.stderr
        )
    )
    assert "stored publication" in disagreeing.stdout, disagreeing.stdout
    assert "DISAGREEMENT" in disagreeing.stderr, disagreeing.stderr

    async with Session() as session:
        publications = (
            await session.execute(
                text("select id from business_tax_publication order by detected_at, id")
            )
        ).fetchall()
    assert len(publications) == 2, "changed content is a second publication"
    old_rows = await stored_rows(Session, publications[0].id)
    new_rows = await stored_rows(Session, publications[1].id)
    assert old_rows["38965019"].tax_name == "原味商行", "the earlier publication was rewritten"
    assert new_rows["38965019"].tax_name == "原味商行(更名)"
    assert set(new_rows) == set(MATCHED)

    runs = await ledger(Session)
    assert runs[3].outcome == "stored", "an alarm is not a failure"
    assert "DISAGREEMENT" in runs[3].detail, "the alarm belongs in the run row, not only on stderr"
    assert runs[3].business_tax_publication_id == publications[1].id

    for path in (first_file, changed_file):
        os.unlink(path)
    await engine.dispose()
    from upto.db import dispose_all  # noqa: PLC0415

    await dispose_all()
    print(
        "business-tax: only the latest place publication's 統編 are stored, the 行業 pairs keep "
        "their positions, a re-run is a silent no-change, a forced re-parse writes no duplicate, "
        "and a stamp that stood still while the content moved is exit 2 with the rows already in"
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
        for attempt in (1, 2):
            migrate = subprocess.run(
                ["alembic", "upgrade", "head"], cwd="/srv", env=environment, capture_output=True
            )
            if migrate.returncode != 0:
                print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
                return 2
            if attempt == 2:
                noise = migrate.stdout.decode("utf-8", "replace") + migrate.stderr.decode(
                    "utf-8", "replace"
                )
                assert "Running upgrade" not in noise, (
                    "the second `alembic upgrade head` ran a migration:\n" + noise
                )
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
