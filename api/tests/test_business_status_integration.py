#!/usr/bin/env python3
"""D81's registry-status source, against a real PostgreSQL and the real ASGI app.

Run inside the stack:
    docker compose exec api python /srv/tests/test_business_status_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

The read rule is what this file holds: a dead-only 統編 disappears from the reference
typeahead and from nowhere else — its `place` row still renders a name (a closed shop in an
old round's result must not lose its label), the circle-local door stays open, a
mixed-status 統編 stays visible (one live row anywhere wins, because number reuse is
measured real), and an unrecognised status defaults to visible.
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

TEST_DB = "upto_business_status_check"

HEADER = '"統一編號","商業名稱","商業地址","登記狀態","備註"'


def status_csv(rows):
    lines = [HEADER] + ['"{}","{}","x","{}",""'.format(no, name, st) for no, name, st in rows]
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url

    import httpx  # noqa: PLC0415

    from upto.api_common import place_names  # noqa: PLC0415
    from upto.ingest.foodtracer import read_sheet  # noqa: PLC0415
    from upto.ingest.gcis import SOURCE  # noqa: PLC0415
    from upto.ingest.run_business_status import ingest_once  # noqa: PLC0415
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
        # Four shops sharing one search fragment (麵). The registry will declare the first
        # dead, the second dead-but-reused, the third recognised-alive, the fourth unknown.
        for registry_no, name, business_no in (
            ("A-1", "平安麵店", "00000001"),
            ("A-2", "元氣麵館", "00000002"),
            ("A-3", "興隆麵鋪", "00000003"),
            ("A-4", "無名麵攤", None),
        ):
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, origin, name, "
                    "name_raw, address, address_raw, business_no, township_code, township_name) "
                    "values (:pub, :no, 'reference', :n, :n, 'x', 'x', :biz, '63000010', "
                    "'松山區')"
                ),
                {"pub": place_pub, "no": registry_no, "n": name, "biz": business_no},
            )
        dead_place = (
            await session.execute(
                text(
                    "insert into place (origin, registry_no) values ('reference', 'A-1') "
                    "returning id"
                )
            )
        ).scalar_one()
        await session.commit()

    raw = status_csv(
        [
            ("00000001", "平安麵店", "歇業／撤銷"),            # dead, no live row → hidden
            ("00000002", "元氣麵館", "停業"),                  # dead row …
            ("00000002", "祿記商號", "核准設立"),              # … but the number was reused → visible
            ("00000003", "興隆麵鋪", "核准設立"),              # alive → visible
            ("00000009", "別區的店", "申覆（辯）期"),          # unrecognised status → harmless
        ]
    )
    first = await ingest_once(
        sheet=read_sheet(raw, datetime.now(timezone.utc), source=SOURCE), url=test_url
    )
    assert first.stored and first.rows_held == 5, first.line()

    second = await ingest_once(
        sheet=read_sheet(raw, datetime.now(timezone.utc), source=SOURCE), url=test_url
    )
    assert not second.stored and not second.parsed, second.line()

    async with Session() as session:
        runs = (
            await session.execute(
                text(
                    "select outcome, business_status_publication_id from ingest_run "
                    "where source = :s order by id"
                ),
                {"s": SOURCE},
            )
        ).all()
    assert [run.outcome for run in runs] == ["stored", "no_change"], runs
    assert runs[0].business_status_publication_id is not None
    assert runs[1].business_status_publication_id is None

    # --- The filter, over HTTP: the dead-only shop is gone; the reused number, the alive
    # --- one and the one the roster does not know all stay.
    transport = httpx.ASGITransport(app=app)
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        found = await client.get(
            "/circles/{}/places".format(circle), params={"q": "麵"}, headers=headers
        )
        assert found.status_code == 200, found.text
        names = [c["name"] for c in found.json()["candidates"] if c["kind"] == "reference"]
        assert "平安麵店" not in names, "the dead shop is still in the typeahead: " + str(names)
        assert set(names) == {"元氣麵館", "興隆麵鋪", "無名麵攤"}, names

    # --- Hidden from search is not erased: the dead shop's place row still has its name,
    # --- because an old round's result must keep its label.
    async with Session() as session:
        labels = await place_names(session, [dead_place])
    assert labels[dead_place] == "平安麵店", labels

    await engine.dispose()
    from upto.db import dispose_all  # noqa: PLC0415

    await dispose_all()
    print(
        "business-status: a dead-only number leaves the typeahead and nothing else, one "
        "live row anywhere keeps a reused number visible, an unknown status stays harmless, "
        "and the ledger's sixth key says which run wrote the roster"
    )


async def with_temporary_database() -> int:
    async def served(test_url: str, environment: dict) -> None:
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, served)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
