#!/usr/bin/env python3
"""D78's storefront source, against a real PostgreSQL and the real ASGI app.

Run inside the stack:
    docker compose exec api python /srv/tests/test_storefront_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

The precedence chain is what this file exists to hold: a site with a storefront sign shows
the sign even when the brand join also answers (D78 outranks D77), the sign is what splits a
multi-brand company's sites — the exact ambiguity D77 refused to guess at — and a site
neither source covers still reads as its registered name. Plus the ingest's own half: pairs
store once, the ledger's fifth foreign key says which run wrote them.
"""

import asyncio
import os
import secrets as pysecrets
import sys
from datetime import datetime, timezone
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
import _tempdb  # noqa: E402

TEST_DB = "upto_storefront_check"

BRAND_HEADER = "行政區域代碼,公司名稱,品牌名稱,產品名稱,原料名稱,原料品牌,每一份量,熱量大卡,相關資訊連結"
GRADE_HEADER = "行政區域代碼,業者名稱店名,食品業者登錄字號,地址,評核結果"

MULTI_COMPANY = "頂呱呱國際股份有限公司"


def brand_csv(pairs):
    lines = [BRAND_HEADER] + [
        "63000000,{},{},產品,原料,牌,100g,200,https://example.invalid".format(c, b)
        for c, b in pairs
    ]
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


def grade_csv(rows):
    lines = [GRADE_HEADER] + [
        "63000010,{},{},臺北市某路1號,優".format(name, registry) for name, registry in rows
    ]
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url

    import httpx  # noqa: PLC0415

    from upto.api_common import place_names  # noqa: PLC0415
    from upto.ingest.foodtracer import read_sheet  # noqa: PLC0415
    from upto.ingest.gradelist import SOURCE as GRADE_SOURCE  # noqa: PLC0415
    from upto.ingest.run_brands import ingest_once as ingest_brands  # noqa: PLC0415
    from upto.ingest.run_storefronts import ingest_once as ingest_storefronts  # noqa: PLC0415
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
        # Four sites of one multi-brand company, and one independent shop. The company's
        # brand join is ambiguous on purpose; two of its sites carry storefront signs.
        for registry_no, name in (
            ("A-1", MULTI_COMPANY),
            ("A-2", MULTI_COMPANY),
            ("A-3", MULTI_COMPANY),
            ("A-4", "啟祥早餐店"),
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
        for registry_no in ("A-1", "A-2", "A-3", "A-4"):
            places[registry_no] = (
                await session.execute(
                    text(
                        "insert into place (origin, registry_no) "
                        "values ('reference', :no) returning id"
                    ),
                    {"no": registry_no},
                )
            ).scalar_one()
        await session.commit()

    brands = await ingest_brands(
        sheet=read_sheet(
            brand_csv([(MULTI_COMPANY, "頂呱呱"), (MULTI_COMPANY, "東京油組")]),
            datetime.now(timezone.utc),
        ),
        url=test_url,
    )
    assert brands.stored, brands.line()

    first = await ingest_storefronts(
        sheet=read_sheet(
            grade_csv([("頂呱呱-南京店", "A-1"), ("東京油組-松山店", "A-2")]),
            datetime.now(timezone.utc),
            source=GRADE_SOURCE,
        ),
        url=test_url,
    )
    assert first.stored and first.names_held == 2, first.line()

    second = await ingest_storefronts(
        sheet=read_sheet(
            grade_csv([("頂呱呱-南京店", "A-1"), ("東京油組-松山店", "A-2")]),
            datetime.now(timezone.utc),
            source=GRADE_SOURCE,
        ),
        url=test_url,
    )
    assert not second.stored and not second.parsed, second.line()

    async with Session() as session:
        runs = (
            await session.execute(
                text(
                    "select outcome, storefront_publication_id from ingest_run "
                    "where source = :s order by id"
                ),
                {"s": GRADE_SOURCE},
            )
        ).all()
    assert [run.outcome for run in runs] == ["stored", "no_change"], runs
    assert runs[0].storefront_publication_id is not None
    assert runs[1].storefront_publication_id is None

    # --- The precedence chain, through the one function every screen uses. The sign splits
    # --- the multi-brand company's sites; the site without a sign keeps the registered name
    # --- (the brand join stays ambiguous); the independent shop reads as itself.
    async with Session() as session:
        names = await place_names(session, places.values())
    assert names[places["A-1"]] == "頂呱呱-南京店", names
    assert names[places["A-2"]] == "東京油組-松山店", names
    assert names[places["A-3"]] == MULTI_COMPANY, (
        "a signless site of an ambiguous company must keep the registered name"
    )
    assert names[places["A-4"]] == "啟祥早餐店", names

    # --- The typeahead matches the sign text and shows it.
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        by_sign = await client.get(
            "/circles/{}/places".format(circle), params={"q": "油組"}, headers=headers
        )
        assert by_sign.status_code == 200, by_sign.text
        rows = [c for c in by_sign.json()["candidates"] if c["kind"] == "reference"]
        assert [row["name"] for row in rows] == ["東京油組-松山店"], rows
        assert rows[0]["registry_no"] == "A-2"

    await engine.dispose()
    from upto.db import dispose_all  # noqa: PLC0415

    await dispose_all()
    print(
        "storefront: the sign outranks the brand and splits an ambiguous company's sites, "
        "a signless site keeps its registered name, and the ledger's fifth key says which "
        "run wrote the names"
    )


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""
    return await _tempdb.with_temporary_database(TEST_DB, lambda url, _environment: scenario(url))


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
