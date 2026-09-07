#!/usr/bin/env python3
"""B2 / item 9 — the trip is named, the proposal never is. The ticket's Done line, end to end.

Run inside the stack:
    docker compose exec api python /srv/tests/test_trip_integration.py

Builds and drops its own database, and **starts its own uvicorn on 127.0.0.1:8902** — because two of
the things ruled about a trip are about the *stream*, and httpx's ASGI transport buffers a response
until the app returns, which an SSE generator never does. Zero events cannot be observed through a
buffer.

**What is under test is an asymmetry rather than a feature.** §3.0 says a proposal is anonymous and a
trip is named. Those two live in one database and must not be reachable from each other: a trip
carries who signed, D14's trigger has already erased who proposed, and no join may put them back
together. So the checks below are as much about what cannot be found as about what the endpoint
returns.
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

TEST_DB = "upto_trip_check"
TAIPEI = timezone(timedelta(hours=8))
FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   {}".format(name))
    else:
        FAILURES.append(name)
        print("FAIL {} {}".format(name, detail))


async def seat(session, circle, nickname):
    """A principal, a member of `circle`, and a device secret for it. Returns (member_id, token)."""
    token = "t-" + pysecrets.token_urlsafe(24)
    principal = (
        await session.execute(text("insert into principal default values returning id"))
    ).scalar_one()
    member = (
        await session.execute(
            text("insert into member (principal_id, circle_id, nickname) "
                 "values (:p, :c, :n) returning id"),
            {"p": principal, "c": circle, "n": nickname},
        )
    ).scalar_one()
    await session.execute(
        text("insert into device_secret (principal_id, secret_sha256) values (:p, :h)"),
        {"p": principal, "h": sha256(token.encode()).hexdigest()},
    )
    return member, token


async def scenario(test_url: str, base_url: str) -> None:
    import httpx  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        circle = (
            await session.execute(text("insert into circle (name) values ('週三午餐') returning id"))
        ).scalar_one()
        other_circle = (
            await session.execute(text("insert into circle (name) values ('別的圈') returning id"))
        ).scalar_one()
        kevin, kevin_token = await seat(session, circle, "Kevin")
        amy, amy_token = await seat(session, circle, "Amy")
        stranger, stranger_token = await seat(session, other_circle, "Stranger")
        places = [
            (
                await session.execute(
                    text("insert into place (origin, circle_id, name) "
                         "values ('circle-local', :c, :n) returning id"),
                    {"c": circle, "n": name},
                )
            ).scalar_one()
            for name in ("巷口麵店", "轉角咖啡")
        ]
        await session.commit()

    K = {"Authorization": "Bearer " + kevin_token}
    A = {"Authorization": "Bearer " + amy_token}
    meal = (datetime.now(TAIPEI) + timedelta(hours=2)).replace(microsecond=0)

    async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
        opened = await client.post(
            "/circles/{}/rounds".format(circle), headers=K,
            json={"target_hour": meal.isoformat()},
        )
        round_id = opened.json()["round_id"]
        # One place each: §3.0 caps a member at three proposals, and two proposers is closer to the
        # thing being tested — a winner whose proposer is erased.
        await client.post("/rounds/{}/proposals".format(round_id), headers=K,
                          json={"place_id": places[0]})
        await client.post("/rounds/{}/proposals".format(round_id), headers=A,
                          json={"place_id": places[1]})

        # A trip cannot be signed before there is anywhere to have gone.
        early = await client.post("/rounds/{}/trip".format(round_id), headers=K)
        check("an open round cannot be signed", early.status_code == 409, early.text)

        rolled = await client.post("/rounds/{}/roll".format(round_id), headers=K)
        check("the round rolls", rolled.status_code == 200, rolled.text)
        result = rolled.json()
        check("and its reveal carries `trip: null` before anyone signs",
              "trip" in result and result["trip"] is None, result.get("trip", "absent"))

        # ---- the three outcomes -----------------------------------------------------------
        first = await client.post("/rounds/{}/trip".format(round_id), headers=K)
        check("the first signature is a 201", first.status_code == 201, first.text)
        signed = first.json()["trip"]
        check("and it names the signer and the time",
              set(signed) == {"nickname", "signed_at"} and signed["nickname"] == "Kevin", signed)

        again = await client.post("/rounds/{}/trip".format(round_id), headers=K)
        check("the same member again is a 200, not a conflict (D69)", again.status_code == 200,
              again.status_code)
        check("and returns the same trip", again.json()["trip"] == signed, again.json())

        other = await client.post("/rounds/{}/trip".format(round_id), headers=A)
        check("another member is a 409 (D68)", other.status_code == 409, other.status_code)
        check("and the 409 carries who signed and when",
              "Kevin" in other.text and signed["signed_at"][:16] in other.text, other.text)

        # ---- what the payloads may not carry (H3, §3.0) -----------------------------------
        for label, payload in (("the signing response", first.json()),
                               ("the reveal payload", rolled.json())):
            flat = json.dumps(payload, ensure_ascii=False)
            check("{} carries no member_id".format(label), "member_id" not in flat)
            check("{} carries no proposer".format(label),
                  "proposer" not in flat and "proposed_by" not in flat)

        # ---- nothing on the stream at signing (D53) ---------------------------------------
        # A second round so there is a signing to watch while the stream is open.
        opened2 = await client.post(
            "/circles/{}/rounds".format(circle), headers=K,
            json={"target_hour": meal.isoformat()},
        )
        round2 = opened2.json()["round_id"]
        await client.post("/rounds/{}/proposals".format(round2), headers=K,
                          json={"place_id": places[0]})
        await client.post("/rounds/{}/roll".format(round2), headers=K)

        events = []
        async with httpx.AsyncClient(base_url=base_url, timeout=20) as watcher:
            async with watcher.stream("GET", "/circles/{}/stream".format(circle), headers=K) as live:
                async def collect():
                    async for line in live.aiter_lines():
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
                check("the stream is open before silence is claimed", live.status_code == 200,
                      live.status_code)
                reader = asyncio.ensure_future(collect())
                # The snapshot is the first event (D56); wait for it, then sign and watch.
                for _ in range(50):
                    if events:
                        break
                    await asyncio.sleep(0.1)
                # **This assertion is what stops the next one passing for the wrong reason, and it
                # is here because it already did.** The first version of this test used the wrong
                # path, got a 404, collected nothing — and "signing pushes nothing to the stream"
                # passed on an empty list. A silence check must first prove it could have heard
                # something. H36's family: a guard that passes by looking at nothing.
                check("and its snapshot arrived, so silence afterwards means something",
                      len(events) == 1 and events[0].get("type") == "snapshot", events)
                snapshot_count = len(events)
                signed_during = await client.post("/rounds/{}/trip".format(round2), headers=A)
                check("the signing under observation succeeded",
                      signed_during.status_code == 201, signed_during.status_code)
                await asyncio.sleep(3.2)
                reader.cancel()
        after = events[snapshot_count:]
        check("signing pushes nothing to the stream over 3.2 s (D53)", after == [], after)

        # ---- and the snapshot on reconnect carries it (D56) -------------------------------
        # **Read with a collector task and a poll, not with `break` inside `async for`.** The first
        # attempt here broke out of the iterator, and `fresh` came back empty — an SSE body is not
        # done when its first event arrives, so leaving the `async for` early races the transport's
        # own teardown and can yield nothing at all. The pattern above works and is reused.
        fresh = []
        async with httpx.AsyncClient(base_url=base_url, timeout=20) as watcher:
            async with watcher.stream("GET", "/circles/{}/stream".format(circle), headers=K) as live:
                check("the reconnect is accepted", live.status_code == 200, live.status_code)

                async def collect_fresh():
                    async for line in live.aiter_lines():
                        if line.startswith("data: "):
                            fresh.append(json.loads(line[6:]))
                reader = asyncio.ensure_future(collect_fresh())
                for _ in range(50):
                    if fresh:
                        break
                    await asyncio.sleep(0.1)
                reader.cancel()
        check("a reconnecting client receives a snapshot at all (D56)", bool(fresh), fresh)
        trip_in_snapshot = (fresh[0].get("last_result") or {}).get("trip") if fresh else None
        check("the snapshot carries the trip a reconnecting client never saw signed (D56)",
              trip_in_snapshot is not None and trip_in_snapshot["nickname"] == "Amy",
              trip_in_snapshot)

    # ---- the database refuses a signature from outside the circle ------------------------
    #
    # Raw SQL on purpose: the endpoint resolves the member against the round's circle and would
    # answer 401 long before an insert, so a request could never reach the constraint. The ticket
    # asks for this shown failing **at the database**, because that is what makes it true even if
    # this function is wrong.
    async with Session() as session:
        try:
            await session.execute(
                text("insert into trip (round_id, circle_id, member_id) values (:r, :c, :m)"),
                {"r": round_id, "c": circle, "m": stranger},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            check("a member of another circle cannot be stored as the signer "
                  "(fk_trip_member_in_circle)", True)
        else:
            check("a member of another circle cannot be stored as the signer", False,
                  "the insert was accepted")
        # And the mirror: this circle's member against another circle's round.
        try:
            await session.execute(
                text("insert into trip (round_id, circle_id, member_id) values (:r, :c, :m)"),
                {"r": round_id, "c": other_circle, "m": stranger},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            check("nor may a trip name a round of a different circle "
                  "(fk_trip_round_in_circle)", True)
        else:
            check("nor may a trip name a round of a different circle", False, "accepted")

    # ---- no column anywhere could give back who proposed the winner (D14) ----------------
    async with Session() as session:
        authors = (
            await session.execute(
                text("select count(*) from proposal where round_id = :r and member_id is not null"),
                {"r": round_id},
            )
        ).scalar()
        check("the closed round's proposals carry no author at all (D14's trigger)",
              authors == 0, authors)
        columns = (
            await session.execute(
                text("select table_name || '.' || column_name from information_schema.columns "
                     "where table_schema = 'public' and table_name in ('trip','round','proposal') "
                     "order by 1")
            )
        ).scalars().all()
        # `trip.member_id` is the one member column that survives, and it is the *signer*. What must
        # not exist is a second one: a place on the trip, or an author on the proposal, either of
        # which would let a join name the person who put the winner forward.
        check("`trip` carries no place — the winner is derived from the round (D28/D57)",
              "trip.place_id" not in columns, [c for c in columns if c.startswith("trip.")])
        check("the only member column across the three tables are the proposal's erased one and "
              "the trip's signer",
              sorted(c for c in columns if c.endswith("member_id"))
              == ["proposal.member_id", "trip.member_id"],
              [c for c in columns if c.endswith("member_id")])

    await engine.dispose()
    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        raise SystemExit(1)
    print("\nB2: a trip is signed once and named, a retry is not a conflict, a second signer is told "
          "who was first, the database refuses a signer from another circle, nothing reaches the "
          "stream and the snapshot carries it anyway, and no column across trip/round/proposal "
          "could name who proposed the winner")


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

    server = None
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrate = subprocess.run(
            ["alembic", "upgrade", "head"], cwd="/srv", env=environment, capture_output=True
        )
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2
        port = 8902
        server = subprocess.Popen(
            ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd="/srv/src", env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import httpx  # noqa: PLC0415

        base_url = "http://127.0.0.1:{}".format(port)
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
    raise SystemExit(asyncio.run(with_temporary_database()))
