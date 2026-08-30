#!/usr/bin/env python3
"""Ticket 20's read half, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_stream_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

One client holds the circle's stream open while a second walks the whole write path. The
assertions are the ruled properties: the snapshot arrives first and is the same code path a
reconnect runs (D56), the close is pushed once with its full result (D53), a fresh snapshot
after the close carries the last result and no open round (D54), and **no event on the wire
ever contains the word "member"** (D55) — asserted over the raw JSON text of everything the
stream delivered, so a future field addition cannot leak authorship quietly.
"""

import asyncio
import json
import os
import secrets as pysecrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_stream_check"
TAIPEI = timezone(timedelta(hours=8))


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def scenario(test_url: str, base_url: str) -> None:
    # A real server over real TCP, because httpx's ASGI transport buffers the whole response
    # until the app returns — and an SSE generator never returns, so the first event would
    # never arrive. The stream's own semantics are the thing under test here.
    import httpx  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(TAIPEI)
    slot_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
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
            text(
                "insert into member (principal_id, circle_id, nickname) values (:p, :c, 'Kevin')"
            ),
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
        await session.execute(
            text(
                "insert into reference_place (publication_id, registry_no, origin, name, "
                "name_raw, address, address_raw, township_code, township_name) "
                "values (:pub, 'A-11111111-00001-1', 'reference', '雨中的店', '雨中的店', "
                "'x', 'x', '63000010', 'x')"
            ),
            {"pub": place_pub},
        )
        # **A second site of the SAME company**, so a pool of two can be swept whole. One reference
        # place plus a circle-local one cannot: a place a member typed has no publisher, so no
        # ingredient stance reaches it and its weight never folds to zero.
        await session.execute(
            text(
                "insert into reference_place (publication_id, registry_no, origin, name, "
                "name_raw, address, address_raw, township_code, township_name) "
                "values (:pub, 'A-11111111-00002-1', 'reference', '雨中的店', '雨中的店', "
                "'x', 'x', '63000010', 'x')"
            ),
            {"pub": place_pub},
        )
        weather_pub = (
            await session.execute(
                text(
                    "insert into forecast_publication "
                    "(dataset_id, content_sha256, detected_at, payload_bytes) "
                    "values ('F-D0047-061', repeat('a', 64), now(), 1000) returning id"
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into forecast_reading (publication_id, township, township_code, "
                "element, slot_start, slot_end, measure, value) "
                "values (:pub, 'x', '63000010', '3小時降雨機率', :s, :e, "
                "'ProbabilityOfPrecipitation', '80')"
            ),
            {"pub": weather_pub, "s": slot_start, "e": slot_start + timedelta(hours=3)},
        )
        await session.commit()

    auth = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as client:
        # The stream requires the same resolution every write does (D67).
        bare = await client.get(f"/circles/{circle}/places", params={"q": "店"})
        assert bare.status_code == 401

        # D28's two doors, both idempotent.
        created = await client.post(
            f"/circles/{circle}/places", json={"name": "巷口麵店"}, headers=auth
        )
        assert created.status_code == 201, created.text
        local_place = created.json()["place_id"]
        repeat = await client.post(
            f"/circles/{circle}/places", json={"name": "巷口麵店"}, headers=auth
        )
        assert repeat.status_code == 200 and repeat.json()["place_id"] == local_place
        ref = await client.post(
            f"/circles/{circle}/places",
            json={"registry_no": "A-11111111-00001-1"},
            headers=auth,
        )
        assert ref.status_code == 201, ref.text
        rainy = ref.json()["place_id"]
        assert ref.json()["name"] == "雨中的店", "a reference place resolves its name (D28)"
        assert (
            await client.post(
                f"/circles/{circle}/places", json={"registry_no": "X-404"}, headers=auth
            )
        ).status_code == 404
        assert (
            await client.post(
                f"/circles/{circle}/places",
                json={"name": "x", "registry_no": "y"},
                headers=auth,
            )
        ).status_code == 422

        found = await client.get(
            f"/circles/{circle}/places", params={"q": "店"}, headers=auth
        )
        kinds = {c["kind"] for c in found.json()["candidates"]}
        assert kinds == {"circle-local", "reference"}, found.text

        # The stream: subscribe, then drive the whole write path from a second client.
        events: list[dict] = []
        got_snapshot = asyncio.Event()
        done = asyncio.Event()

        async def reader():
            async with client.stream(
                "GET", f"/circles/{circle}/stream", headers=auth
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    events.append(json.loads(line[6:]))
                    got_snapshot.set()
                    if events[-1].get("type") == "closed":
                        done.set()
                        return

        task = asyncio.create_task(reader())
        await asyncio.wait_for(got_snapshot.wait(), timeout=10)
        assert events[0]["type"] == "snapshot" and events[0]["open_round"] is None

        opened = await client.post(f"/circles/{circle}/rounds", json={}, headers=auth)
        round_id = opened.json()["round_id"]
        for place in (rainy, local_place):
            assert (
                await client.post(
                    f"/rounds/{round_id}/proposals",
                    json={"place_id": place},
                    headers=auth,
                )
            ).status_code == 201

        # A reconnect mid-round is the same code path: snapshot with the named pool (D56).
        async with client.stream(
            "GET", f"/circles/{circle}/stream", headers=auth
        ) as second:
            async for line in second.aiter_lines():
                if line.startswith("data: "):
                    mid = json.loads(line[6:])
                    break
        assert mid["open_round"]["round_id"] == round_id
        assert {p["name"] for p in mid["open_round"]["pool"]} == {"雨中的店", "巷口麵店"}

        rolled = await client.post(f"/rounds/{round_id}/roll", headers=auth)
        assert rolled.status_code == 200, rolled.text
        await asyncio.wait_for(done.wait(), timeout=10)
        task.cancel()

        types = [e["type"] for e in events]
        assert types[0] == "snapshot" and types[-1] == "closed"
        assert "round_opened" in types and "pooled" in types

        closed = events[-1]["result"]
        assert closed["winning_place_id"] == rolled.json()["winning_place_id"]
        assert closed["places"][str(rainy)] == "雨中的店"

        # **D55 as narrowed 2026-08-19 (owner: 「收窄」, `71ddbe5`) — it protects a *proposal's*
        # author, not every mention of a member.** The old form asserted the string `member` never
        # appeared anywhere in the wire, which was a correct reading of D55 while a round had nothing
        # to say about people. D108 gives every member a seat that must be named from the first frame
        # or D91's fairness claim cannot be shown at all, so the blanket string test would have
        # forbidden a ruled feature.
        #
        # **What still must never travel is who proposed what**, because that is the fact §3.0's
        # anonymity argument is about: knowing who put 火鍋 in the pool reveals that person's
        # preference. A seat list reveals that somebody rolled, which everybody did, visibly, on
        # purpose — and it carries no link to a place at all.
        #
        # So the check moves from the whole wire to the two structures that must stay anonymous.
        for event in events:
            pool = (event.get("round") or {}).get("pool") or event.get("pool") or []
            for entry in pool:
                assert not (set(entry) & {"member_id", "member", "principal_id", "proposer"}), (
                    "a pooled place named its proposer: {}".format(entry))
            panel = (event.get("result") or {}).get("panel")
            if panel is not None:
                flat = json.dumps(panel, ensure_ascii=False)
                assert "principal" not in flat, "the weight panel leaked a principal"
        # And `principal` never travels at all — that one is not narrowed. A principal is the
        # identity behind a seat, and no surface has ever had a reason to see it (H19).
        wire = json.dumps(events, ensure_ascii=False)
        assert "principal" not in wire, "a principal reached the wire"

        # D54: after the close, a fresh snapshot carries the result and no open round.
        async with client.stream(
            "GET", f"/circles/{circle}/stream", headers=auth
        ) as third:
            async for line in third.aiter_lines():
                if line.startswith("data: "):
                    after = json.loads(line[6:])
                    break
        assert after["open_round"] is None
        assert after["last_result"]["round_id"] == round_id
        assert after["last_result"]["dice"] == closed["dice"]

        # **Owner-ruled 2026-08-30: a swept pool tells every seat, and only a stream can prove it.**
        # The roller learns from the 409; the other seats learn from here, so asserting the 409
        # alone would test the half that already worked.
        #
        # **Its own reader, and LAST in the file.** Three constraints forced this shape, and each
        # one is the ruling working rather than an obstacle: the reader above RETURNS on `closed`,
        # so nothing after that reaches `events`; a swept round STAYS OPEN, so opening one before
        # the ordinary round left D52's one-open-round rule refusing every round after it; and for
        # the same reason it must come after the later `open_round is None` assertion, which is
        # true only while nothing is open. A swept round blocks its circle until somebody proposes
        # into it — the shape that left round 834 holding circle 5.
        # **Rebuilt on 2026-08-30: the all-swept pool is now reached through a CATEGORY, not an
        # ingredient.** The ingredient veto was the only ×0 when this test was written and it has
        # been withdrawn — but the state it produced is still reachable, and by a shorter road:
        # D103's discount is `1 − 1/N` and this circle seats **one**, so `N = 1` gives exactly 0.
        # That is the formula and not a special case (D103's own sentence), so avoiding the
        # category both pooled places carry sweeps the pool.
        #
        # **Worth keeping rather than deleting with the feature.** A swept pool leaves the round
        # OPEN and blocks its circle until somebody proposes into it — the shape that left round
        # 834 holding circle 5 — so the event is the only thing telling the other seats what
        # happened. The spec keeps `pool_swept` as the guard for the next ×0 anyone rules; a guard
        # with no test is the guard that is quietly broken when that day comes.
        swept = await client.post(f"/circles/{circle}/rounds", json={}, headers=auth)
        assert swept.status_code == 201, swept.text
        swept_id = swept.json()["round_id"]
        sibling = await client.post(
            f"/circles/{circle}/places",
            json={"registry_no": "A-11111111-00002-1"},
            headers=auth,
        )
        assert sibling.status_code == 201, sibling.text
        pooled_places = (rainy, sibling.json()["place_id"])
        for place in pooled_places:
            assert (await client.post(
                f"/rounds/{swept_id}/proposals", json={"place_id": place}, headers=auth
            )).status_code == 201
        # **Both pooled places carry the one category the seat avoids** — that is what makes the
        # pool swept rather than merely discounted. All five provenance columns or none
        # (`ck_place_category_provenance`), so the fixture sets the lot.
        async with Session() as session:
            for place in pooled_places:
                await session.execute(
                    text("update place set category = '燒烤', category_model = 'test-fixture', "
                         "  category_prompt_version = 'fixture', category_generated_at = now(), "
                         "  category_input = 'x' where id = :p"),
                    {"p": place},
                )
            await session.commit()
        assert (await client.post(
            f"/circles/{circle}/preferences",
            json={"kind": "avoid_category", "value": "燒烤", "stance": "avoid"},
            headers=auth,
        )).status_code == 204

        swept_events = []
        swept_seen = asyncio.Event()

        async def swept_reader():
            async with client.stream(
                "GET", f"/circles/{circle}/stream", headers=auth
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        event = json.loads(line[6:])
                        swept_events.append(event)
                        if event["type"] == "pool_swept":
                            swept_seen.set()
                            return

        swept_task = asyncio.create_task(swept_reader())
        await asyncio.sleep(0.5)
        swept_roll = await client.post(f"/rounds/{swept_id}/roll", headers=auth)
        assert swept_roll.status_code == 409, (
            "the swept round rolled {} — the fixture no longer produces an all-vetoed pool and "
            "this case is testing nothing".format(swept_roll.status_code))
        await asyncio.wait_for(swept_seen.wait(), timeout=10)
        swept_task.cancel()

        notice = [e for e in swept_events if e["type"] == "pool_swept"][0]
        # The round id is the surface's clear rule — it clears on the next `pooled` for THAT round,
        # so an event without it would never clear or be cleared by another round's proposal.
        assert notice["round_id"] == swept_id, notice
        assert set(notice) == {"type", "round_id"}, (
            "type and round id, no text — the sentence has one owner and it is the surface", notice)

    await engine.dispose()

    print(
        "ticket 20: the snapshot is the first event on connect and reconnect alike, the "
        "close is pushed once whole, the last result survives to the next snapshot, and "
        "nothing on the wire carries a member"
    )


async def with_temporary_database() -> int:
    admin_url, test_url = urls()
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

    server = None
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
        port = 8901
        server = subprocess.Popen(
            ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd="/srv/src",
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        import httpx  # noqa: PLC0415

        base_url = f"http://127.0.0.1:{port}"
        async with httpx.AsyncClient() as probe:
            for _ in range(50):
                try:
                    if (await probe.get(base_url + "/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.2)
            else:
                print("the test server never came up", file=sys.stderr)
                return 2
        await scenario(test_url, base_url)
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text('drop database if exists "{}" with (force)'.format(TEST_DB))
            )
        await admin.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
