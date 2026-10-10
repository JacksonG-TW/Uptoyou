#!/usr/bin/env python3
"""D77's brand source, against a real PostgreSQL and the real ASGI app.

Run inside the stack:
    docker compose exec api python /srv/tests/test_brand_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

What is under test, in order: the ingest stores the pairs once and no-ops on the same bytes
(H14, with the run ledger saying which was which); the display name follows D77's read rule —
a single-brand company shows its brand, a multi-brand company keeps its registered name,
because nothing in either source says which of its brands a given site is; the typeahead
finds a row by its brand text over HTTP; and a newer publication's pairs win, because the
read path asks the latest publication rather than a copy (D28's ruling, one source over).
"""

import asyncio
import os
import secrets as pysecrets
import sys
from datetime import datetime, timezone
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402

import _tempdb  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_brand_check"

HEADER = "行政區域代碼,公司名稱,品牌名稱,產品名稱,原料名稱,原料品牌,每一份量,熱量大卡,相關資訊連結"

MOS_COMPANY = "安心食品服務股份有限公司"
MULTI_COMPANY = "頂呱呱國際股份有限公司"


def csv_bytes(pairs):
    lines = [HEADER]
    for company, brand in pairs:
        lines.append(
            "63000000,{},{},產品,原料,牌,100g,200,https://example.invalid".format(company, brand)
        )
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url

    import httpx  # noqa: PLC0415

    from upto.api_common import place_names  # noqa: PLC0415
    from upto.ingest.foodtracer import read_sheet  # noqa: PLC0415
    from upto.ingest.run_brands import ingest_once  # noqa: PLC0415
    from upto.main import app  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    token = "t-" + pysecrets.token_urlsafe(24)

    async with Session() as session:
        await session.execute(
            text(
                "insert into township_station "
                "(township_code, township_name, station_id, station_name, resolution) "
                "values ('63000010', '松山區', 'C0A980', '測試站', 'town_code')"
            )
        )
        circle = (
            await session.execute(
                text("insert into circle (name) values ('週三午餐') returning id")
            )
        ).scalar_one()
        principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        await session.execute(
            text("insert into member (principal_id, circle_id, nickname) values (:p, :c, 'K')"),
            {"p": principal, "c": circle},
        )
        await session.execute(
            text("insert into device_secret (principal_id, secret_sha256) values (:p, :h)"),
            {"p": principal, "h": sha256(token.encode()).hexdigest()},
        )
        place_pub = (
            await session.execute(
                text(
                    "insert into place_publication (source, content_sha256, detected_at, "
                    "payload_bytes, entry_name, entry_bytes, scope) "
                    "values ('fda-97', repeat('b', 64), now(), 1000, 'x.csv', 1000, "
                    "'餐飲場所 / 臺北市') returning id"
                )
            )
        ).scalar_one()
        for registry_no, name in (
            ("A-1", MOS_COMPANY),
            ("A-2", MULTI_COMPANY),
            ("A-3", "啟祥早餐店"),
        ):
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, origin, name, "
                    "name_raw, address, address_raw, township_code, township_name) "
                    "values (:pub, :no, 'reference', :n, :n, 'x', 'x', '63000010', '松山區')"
                ),
                {"pub": place_pub, "no": registry_no, "n": name},
            )
        places = {}
        for registry_no in ("A-1", "A-2", "A-3"):
            places[registry_no] = (
                await session.execute(
                    text(
                        "insert into place (origin, registry_no) "
                        "values ('reference', :no) returning id"
                    ),
                    {"no": registry_no},
                )
            ).scalar_one()
        local = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '巷口麵店') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        await session.commit()

    # --- The ingest stores the pairs once, and the ledger says so. The pair for MOS repeats
    # --- (the file is product-level) and one company is absent from the FDA rows on purpose:
    # --- a pair with nothing to join is stored anyway, because the join is the read's business.
    raw = csv_bytes(
        [
            (MOS_COMPANY, "摩斯漢堡"),
            (MOS_COMPANY, "摩斯漢堡"),
            (MULTI_COMPANY, "頂呱呱"),
            (MULTI_COMPANY, "東京油組"),
            ("不在名冊的公司", "隱形牌"),
        ]
    )
    first = await ingest_once(
        sheet=read_sheet(raw, datetime.now(timezone.utc)), url=test_url
    )
    assert first.stored and first.pairs_held == 4, first.line()

    second = await ingest_once(
        sheet=read_sheet(raw, datetime.now(timezone.utc)), url=test_url
    )
    assert not second.stored and not second.parsed, second.line()

    async with Session() as session:
        runs = (
            await session.execute(
                text(
                    "select outcome, rows_written, brand_publication_id from ingest_run "
                    "where source = 'taipei-foodtracer' order by id"
                )
            )
        ).all()
        publications = (
            await session.execute(text("select count(*) from brand_publication"))
        ).scalar_one()
    assert publications == 1, "the same bytes minted a second publication"
    assert [run.outcome for run in runs] == ["stored", "no_change"], runs
    assert runs[0].brand_publication_id is not None, "a stored run must name its publication"
    assert runs[1].brand_publication_id is None, "a no-op attached a publication"
    assert runs[1].rows_written == 0

    # --- D77's read rule, through the same function every screen uses.
    async with Session() as session:
        names = await place_names(session, list(places.values()) + [local])
    assert names[places["A-1"]] == "摩斯漢堡", names
    assert names[places["A-2"]] == MULTI_COMPANY, "a multi-brand company must keep its name"
    assert names[places["A-3"]] == "啟祥早餐店", names
    assert names[local] == "巷口麵店", "the patch touched a circle-local name"

    # --- The typeahead, over HTTP: found by brand text, shown as the brand; the registered
    # --- name still matches too, and the ambiguous company still reads as itself.
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        by_brand = await client.get(
            "/circles/{}/places".format(circle), params={"q": "摩斯"}, headers=headers
        )
        assert by_brand.status_code == 200, by_brand.text
        rows = [c for c in by_brand.json()["candidates"] if c["kind"] == "reference"]
        assert [row["name"] for row in rows] == ["摩斯漢堡"], rows
        assert rows[0]["registry_no"] == "A-1"

        by_company = await client.get(
            "/circles/{}/places".format(circle), params={"q": "安心食品"}, headers=headers
        )
        rows = [c for c in by_company.json()["candidates"] if c["kind"] == "reference"]
        assert [row["name"] for row in rows] == ["摩斯漢堡"], rows

        ambiguous = await client.get(
            "/circles/{}/places".format(circle), params={"q": "頂呱呱"}, headers=headers
        )
        rows = [c for c in ambiguous.json()["candidates"] if c["kind"] == "reference"]
        assert [row["name"] for row in rows] == [MULTI_COMPANY], rows

    # --- A newer publication's pairs win: the platform renames the brand, the screen follows.
    renamed = csv_bytes([(MOS_COMPANY, "摩斯漢堡 MOS BURGER")])
    third = await ingest_once(
        sheet=read_sheet(renamed, datetime.now(timezone.utc)), url=test_url
    )
    assert third.stored, third.line()
    async with Session() as session:
        names = await place_names(session, [places["A-1"], places["A-2"]])
    assert names[places["A-1"]] == "摩斯漢堡 MOS BURGER", names
    assert names[places["A-2"]] == MULTI_COMPANY, (
        "the newer publication dropped the pair, so the company reads as itself again"
    )

    await engine.dispose()
    from upto.db import dispose_all  # noqa: PLC0415

    await dispose_all()
    print(
        "brand: the pairs store once and the ledger says which run wrote them, a single-brand "
        "company reads as its brand everywhere, an ambiguous one keeps its name, and the "
        "latest publication wins"
    )


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""
    return await _tempdb.with_temporary_database(TEST_DB, lambda url, _environment: scenario(url))


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
