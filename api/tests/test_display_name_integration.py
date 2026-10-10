#!/usr/bin/env python3
"""D92's three-layer branch names, against a real PostgreSQL and the real ASGI app.

Run inside the stack:
    docker compose exec api python /srv/tests/test_display_name_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

What it holds (owner-ruled 2026-08-18: the name is composed in the API): a signed site reads
as its sign, untouched; a sign-less site whose brand is shared by other sign-less sites of the
company gains D92's bracket, `品牌（區＋路＋段）`; two such sites on the same road and section
gain the house number too; a company's lone sign-less site and an independent shop keep the
bare name; the search payload carries `name_source` and B6's `district`; and the pool
(`place_names`) reads exactly what the search read — one composition, three screens.
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

TEST_DB = "upto_display_name_check"

BRAND_HEADER = "行政區域代碼,公司名稱,品牌名稱,產品名稱,原料名稱,原料品牌,每一份量,熱量大卡,相關資訊連結"
GRADE_HEADER = "行政區域代碼,業者名稱店名,食品業者登錄字號,地址,評核結果"

CHAIN = "和德昌股份有限公司"
CHAIN_B = "鼎泰豐小吃店股份有限公司"


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

    sites = {
        # 和德昌 = 麥當勞 (single brand): one signed site, two sign-less on different roads,
        # two more sign-less on one road and section (layer three).
        "M-1": (CHAIN, "臺北市內湖區舊宗路1段120號"),
        "M-2": (CHAIN, "臺北市大安區信義路2段88號"),
        "M-3": (CHAIN, "臺北市松山區民生東路3段135號"),
        "M-4": (CHAIN, "臺北市松山區民生東路3段200號"),
        "M-5": (CHAIN, "臺北市中山區長春路100號"),
        # 鼎泰豐: no brand row, so the registered name is the base; a lone sign-less site
        # after its sibling gets a sign — no bracket for one.
        "D-1": (CHAIN_B, "臺北市大安區信義路2段194號"),
        "D-2": (CHAIN_B, "臺北市信義區市府路45號"),
        # An independent shop with a unique name.
        "I-1": ("啟祥早餐店", "臺北市松山區八德路4段1號"),
        # R-6 (owner-ruled 2026-08-18): a registry footnote at the head of the name is read
        # out; a name that is only a footnote stays as it is.
        "F-1": ("(無市招)52巷3姊妹麵攤", "臺北市大同區延平北路2段1號"),
        "F-2": ("(餐飲業)", "臺北市大同區延平北路2段2號"),
    }

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
        for registry_no, (name, address) in sites.items():
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, origin, name, "
                    "name_raw, address, address_raw, township_code, township_name) "
                    "values (:pub, :no, 'reference', :n, :n, :a, :a, '63000010', '松山區')"
                ),
                {"pub": place_pub, "no": registry_no, "n": name, "a": address},
            )
        places = {}
        for registry_no in sites:
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
                    "values ('circle-local', :c, '巷口麵攤') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        await session.commit()

    brands = await ingest_brands(
        sheet=read_sheet(brand_csv([(CHAIN, "麥當勞")]), datetime.now(timezone.utc)),
        url=test_url,
    )
    assert brands.stored, brands.line()
    signs = await ingest_storefronts(
        sheet=read_sheet(
            grade_csv([("麥當勞-長春", "M-5"), ("鼎泰豐-臺北101店", "D-2")]),
            datetime.now(timezone.utc),
            source=GRADE_SOURCE,
        ),
        url=test_url,
    )
    assert signs.stored and signs.names_held == 2, signs.line()

    expected = {
        "M-1": "麥當勞（內湖舊宗路1段）",
        "M-2": "麥當勞（大安信義路2段）",
        "M-3": "麥當勞（松山民生東路3段135號）",
        "M-4": "麥當勞（松山民生東路3段200號）",
        "M-5": "麥當勞-長春",
        "D-1": CHAIN_B,
        "D-2": "鼎泰豐-臺北101店",
        "I-1": "啟祥早餐店",
        "F-1": "52巷3姊妹麵攤",
        "F-2": "(餐飲業)",
    }

    # --- The pool reads the composed name — the one function every screen uses.
    async with Session() as session:
        names = await place_names(session, list(places.values()) + [local])
    for registry_no, want in expected.items():
        got = names[places[registry_no]]
        assert got == want, "pool {}: {!r} != {!r}".format(registry_no, got, want)
    assert names[local] == "巷口麵攤", names

    # --- The search reads the same names, and says where each came from.
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(
            "/circles/{}/places".format(circle), params={"q": "麥當勞"}, headers=headers
        )
        assert res.status_code == 200, res.text
        rows = {c["registry_no"]: c for c in res.json()["candidates"] if c["kind"] == "reference"}
        assert set(rows) == {"M-1", "M-2", "M-3", "M-4", "M-5"}, sorted(rows)
        for registry_no in ("M-1", "M-2", "M-3", "M-4", "M-5"):
            assert rows[registry_no]["name"] == expected[registry_no], rows[registry_no]
        assert rows["M-1"]["name_source"] == "brand", rows["M-1"]
        assert rows["M-5"]["name_source"] == "sign", rows["M-5"]
        assert rows["M-1"]["district"] == "內湖區舊宗路1段", rows["M-1"]
        assert rows["M-5"]["district"] == "中山區長春路", rows["M-5"]
        assert rows["M-3"]["district"] == "松山區民生東路3段", rows["M-3"]

        res = await client.get(
            "/circles/{}/places".format(circle), params={"q": "鼎泰豐"}, headers=headers
        )
        rows = {c["registry_no"]: c for c in res.json()["candidates"] if c["kind"] == "reference"}
        assert rows["D-1"]["name"] == CHAIN_B and rows["D-1"]["name_source"] == "registered", rows
        assert rows["D-2"]["name"] == "鼎泰豐-臺北101店" and rows["D-2"]["name_source"] == "sign", rows

        res = await client.get(
            "/circles/{}/places".format(circle), params={"q": "麵攤"}, headers=headers
        )
        rows = res.json()["candidates"]
        assert rows and rows[0]["kind"] == "circle-local", rows
        assert rows[0]["name"] == "巷口麵攤" and rows[0]["name_source"] == "circle-local", rows
        assert rows[0]["district"] is None, rows
        ref = [c for c in rows if c["kind"] == "reference"]
        assert [c["name"] for c in ref] == ["52巷3姊妹麵攤"], ref
        assert ref[0]["registry_no"] == "F-1" and ref[0]["district"] == "大同區延平北路2段", ref

    await engine.dispose()
    from upto.db import dispose_all  # noqa: PLC0415

    await dispose_all()
    print(
        "display name: D92's bracket lands only where a sign-less base name collides, the "
        "house number only where the road still collides, the sign and the lone site stay "
        "bare, and the pool reads what the search read"
    )


async def with_temporary_database() -> int:
    async def served(test_url: str, environment: dict) -> None:
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, served)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
