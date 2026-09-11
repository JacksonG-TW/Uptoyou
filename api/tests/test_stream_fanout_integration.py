#!/usr/bin/env python3
"""Two API instances, one circle: an event published on A reaches a member listening on B.

*Written 2026-09-11 with candidate 15 (owner 「Notify」), and it is the only test that can fail for
the reason the change exists.* `test_stream_integration` starts **one** uvicorn and proves the
stream works; it passed unchanged before this change and after it, because a single instance hears
its own events either way — with the old in-process queues **and** with `pg_notify`. So it cannot
tell the two apart, and nothing else could either.

**What breaks without the change, concretely.** Five friends open the round; the load balancer puts
three on instance A and two on B. One proposes, A publishes, and only A's three see the pool move.
Worse at the reveal: A publishes `closed` and B's two sit watching a round that has already been
decided, until they reload. D56's snapshot is why that is recoverable rather than fatal — and
«recoverable by reloading» is not what the product promises.

**Two uvicorns on one database, which is the shape the ASG will have**, on ports 8902 and 8903 so
this never collides with `test_stream_integration`'s 8901 if both run. It also asserts the two
things the mechanism made possible and the two it made dangerous: the payload ceiling holds at
D110's ruled maximum, and a rolled-back transaction publishes nothing — the trap the module
docstring warns the next publisher about.

    docker compose run --rm tests python /srv/tests/test_stream_fanout_integration.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DB = "upto_fanout_check"
TAIPEI = timezone(timedelta(hours=8))
PORTS = (8902, 8903)

FAILURES: list[str] = []


def check(label: str, ok: bool, detail=None) -> None:
    print(("ok   " if ok else "FAIL ") + label + ("" if ok or detail is None else f" {detail!r}"))
    if not ok:
        FAILURES.append(label)


async def seat(session, circle_id: int, nickname: str):
    principal = await session.scalar(text("insert into principal default values returning id"))
    member = await session.scalar(
        text("insert into member (circle_id, principal_id, nickname) "
             "values (:c, :p, :n) returning id"),
        {"c": circle_id, "p": principal, "n": nickname})
    import secrets, hashlib  # noqa: PLC0415
    token = secrets.token_urlsafe(32)
    await session.execute(
        text("insert into device_secret (principal_id, secret_sha256) values (:p, :s)"),
        {"p": principal, "s": hashlib.sha256(token.encode()).hexdigest()})
    return member, token


async def scenario(test_url: str, a: str, b: str) -> None:
    import httpx  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        circle = await session.scalar(
            text("insert into circle (name) values ('fanout') returning id"))
        _kevin, k = await seat(session, circle, "Kevin")
        _amy, amy = await seat(session, circle, "Amy")
        place = await session.scalar(
            text("insert into place (origin, registry_no) values ('reference', 'FAN-1') "
                 "returning id"))
        place2 = await session.scalar(
            text("insert into place (origin, registry_no) values ('reference', 'FAN-2') "
                 "returning id"))
        await session.commit()

    K = {"Authorization": "Bearer " + k}
    A = {"Authorization": "Bearer " + amy}
    meal = (datetime.now(TAIPEI) + timedelta(hours=2)).replace(microsecond=0)

    # --- Amy listens on instance B; Kevin acts on instance A ---------------------------------
    heard: list[dict] = []
    async with httpx.AsyncClient(base_url=b, timeout=20) as watcher:
        async with watcher.stream("GET", f"/circles/{circle}/stream", headers=A) as live:
            check("a member's stream opens on instance B", live.status_code == 200,
                  live.status_code)

            async def collect():
                async for line in live.aiter_lines():
                    if line.startswith("data: "):
                        heard.append(json.loads(line[6:]))

            reader = asyncio.ensure_future(collect())
            for _ in range(50):
                if heard:
                    break
                await asyncio.sleep(0.1)
            # **The snapshot must arrive first or the silence below proves nothing** — H36's
            # family, and `test_trip_integration` learned it the expensive way.
            check("and its snapshot arrives, so a later silence would mean something",
                  len(heard) == 1 and heard[0].get("type") == "snapshot", heard)
            snapshot_count = len(heard)

            async with httpx.AsyncClient(base_url=a, timeout=20) as actor:
                opened = await actor.post(f"/circles/{circle}/rounds", headers=K,
                                          json={"target_hour": meal.isoformat()})
                check("Kevin opens a round on instance A", opened.status_code == 201,
                      opened.status_code)
                rid = opened.json()["round_id"]
                await actor.post(f"/rounds/{rid}/proposals", headers=K, json={"place_id": place})
                await actor.post(f"/rounds/{rid}/proposals", headers=K, json={"place_id": place2})
                rolled = await actor.post(f"/rounds/{rid}/roll", headers=K)
                check("and rolls it there", rolled.status_code == 200, rolled.status_code)

            for _ in range(60):
                if len(heard) > snapshot_count + 1:
                    break
                await asyncio.sleep(0.1)
            reader.cancel()

    crossed = [e.get("type") for e in heard[snapshot_count:]]
    # **This is the assertion the whole candidate exists for.** Before 2026-09-11 the broker was a
    # dict in one process: A published, B's subscriber never heard it, and this list was empty.
    check("events published on A reach a member listening on B (the point of this file)",
          "round_opened" in crossed and "pooled" in crossed and "closed" in crossed, crossed)
    closed = [e for e in heard[snapshot_count:] if e.get("type") == "closed"]
    check("and the close that crossed carries its result whole",
          bool(closed) and (closed[0].get("result") or {}).get("winning_place_id") is not None,
          closed[:1])
    check("while a member's crossed payload still carries no accounting (D105)",
          all(k not in json.dumps(e) for e in heard[snapshot_count:]
              for k in ("\"panel\"", "\"allocation\"", "\"weights\"")), crossed)

    # --- the two things the mechanism made dangerous ------------------------------------------
    from upto.stream import MAX_PAYLOAD, _envelope  # noqa: PLC0415

    seats = [{"member_id": 10_000 + i, "nickname": "十二字的暱稱恰好最長" + str(i),
              "die1": 6, "die2": 6, "counts": i == 0} for i in range(10)]
    biggest = {"type": "closed", "result": {
        "round_id": 999999, "dice": [6, 6], "sum": 12, "winning_place_id": 999999,
        "places": {str(900000 + i): "台北市中山區一家名字很長的餐飲有限公司（中山長春路）"
                   for i in range(30)},
        "rolls": seats, "deciding_member": {"id": 10_000, "nickname": "十二字的暱稱恰好最長0"},
        "seed_commit": "a" * 64, "revealed_seed": "b" * 64, "trip": None,
        "winner_headline": "一家名字很長的餐飲", "winner_qualifier": "中山長春路"}}
    size = len(_envelope(1, biggest).encode())
    # D110 caps a circle at ten seats and three places each, so thirty places is the ruled
    # maximum pool. If this ever approaches the ceiling the fallback is in the module docstring.
    check(f"a round at D110's ruled maximum fits the notification ceiling ({size} of {MAX_PAYLOAD})",
          size < MAX_PAYLOAD, size)

    async with Session() as session:
        from upto.stream import publish  # noqa: PLC0415
        try:
            await publish(session, circle, {"type": "never-sent"})
            await session.rollback()
        except Exception as failure:  # noqa: BLE001
            check("publishing inside a transaction does not raise", False, failure)
    await asyncio.sleep(0.5)
    check("a notification in a rolled-back transaction is never delivered (the module's trap)",
          "never-sent" not in [e.get("type") for e in heard], heard[-1:])

    await engine.dispose()
    from upto.db import dispose_all  # noqa: PLC0415
    await dispose_all()


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'drop database if exists "{TEST_DB}" with (force)'))
        await connection.execute(text(f'create database "{TEST_DB}"'))
    await admin.dispose()

    servers = []
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrate = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv",
                                 env=environment, capture_output=True)
        if migrate.returncode != 0:
            sys.stderr.write(migrate.stderr.decode("utf-8", "replace"))
            return 2
        import httpx  # noqa: PLC0415
        for port in PORTS:
            servers.append(subprocess.Popen(
                ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd="/srv/src", env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        urls = [f"http://127.0.0.1:{p}" for p in PORTS]
        async with httpx.AsyncClient() as probe:
            for url in urls:
                for _ in range(80):
                    try:
                        if (await probe.get(url + "/health")).status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.25)
                else:
                    print(f"FAIL {url} never became healthy", file=sys.stderr)
                    return 2
        await scenario(test_url, *urls)
    finally:
        for server in servers:
            server.terminate()
            server.wait(timeout=10)
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(text(f'drop database if exists "{TEST_DB}" with (force)'))
        await admin.dispose()

    if FAILURES:
        print(f"\n{len(FAILURES)} failing: " + ", ".join(FAILURES), file=sys.stderr)
        return 1
    print("\nthe stream crosses instances: an event published on one API process reaches a member "
          "listening on another, because the broker is the database and no longer a dict in one "
          "process; a round at D110's maximum fits the notification ceiling; and a notification "
          "in a rolled-back transaction is never delivered")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(with_temporary_database()))
