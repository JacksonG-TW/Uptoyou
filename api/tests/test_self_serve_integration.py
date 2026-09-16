#!/usr/bin/env python3
"""A24 — the self-serve door, through a real uvicorn against a real PostgreSQL.

    docker compose run --rm tests python /srv/tests/test_self_serve_integration.py

*Candidate 21, from the self-serve sitting of 2026-09-13. It builds its own database and drops it.*

**It drives HTTP rather than the functions, because the refusals ARE the feature.** Four of the
things this candidate promises are status codes — a full circle, a replaced link, an unknown one,
and a member who is not the creator — and a status code is only real at a process boundary. Calling
the handlers directly would assert what `HTTPException` was constructed with, which is a different
claim from «a client gets 409».

**The shape it is most careful about: what a leaked ticket can do.** The ticket is one shared secret
pasted into a group chat, so the design assumes it leaks, and the bound is D110's cap — a **total,
not a rate**, because there is no leave and no seat reuse. The cap case below is therefore not a
tidy edge: it is the thing standing between a leaked link and an unbounded number of strangers.
"""

import asyncio
import json
import os
import subprocess
import sys
from hashlib import sha256

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_self_serve_check"
PORT = 8907
#: **No `/api` prefix, and that is not an oversight.** The proxy strips `/api/` before forwarding,
#: so the routers must not carry it (CLAUDE.md's one-roll walkthrough paragraph). A test driving
#: uvicorn directly therefore uses the bare path; the same call through 8080 is `/api/circles`.
BASE = f"http://127.0.0.1:{PORT}"

CHECKS = []


def check(label: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((label, condition, detail))
    print(("  ok   " if condition else "  FAIL ") + label + (f" — {detail}" if detail else ""))


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


def ticket_of(link: str) -> str:
    """The ticket out of the link, asserting on the way that it is in the FRAGMENT.

    A `?` would put it in the query, where it reaches the proxy's access log, this API and the next
    request's `Referer` — the same assertion `test_issue_integration` makes about a device key, for
    the same reason (A20).
    """
    before, _, fragment = link.partition("#")
    assert fragment, link
    assert "?" not in before, f"the ticket must not be in the query: {link}"
    return dict(part.split("=", 1) for part in fragment.split("&"))["t"]


async def scenario(test_url: str) -> None:
    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=20) as client:
        # ---- create: no credential, and that is the feature ----------------------------------
        made = await client.post(BASE + "/circles",
                                 json={"name": "週三午餐", "nickname": "小美"})
        check("a stranger with no credential can create a circle", made.status_code == 201,
              f"got {made.status_code}: {made.text[:120]}")
        body = made.json()
        circle = body["circle_id"]
        creator_key = body["key"]
        link = body["join_link"]
        check("and the response carries a key and a join link",
              bool(creator_key) and bool(link))
        check("the ticket rides in the fragment, never the query (A20)",
              "#" in link and "?" not in link.split("#")[0], link)
        ticket = ticket_of(link)

        # **Only the hash is stored** — the property that makes a database read useless.
        engine = create_async_engine(test_url, poolclass=None)
        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as session:
            stored = (
                await session.execute(text("select token_sha256 from join_ticket"))
            ).scalars().all()
        check("the ticket is stored as a hash and never as itself (D74)",
              len(stored) == 1 and ticket not in stored and len(stored[0]) == 64)

        # **D83's second exception, at a fixed clock** (owner 「台北」, 2026-09-14). The ceiling's
        # day starts at Taipei's midnight, which is 16:00 UTC the day before. Evaluated at instants,
        # never at now(), so the test means the same thing whatever hour it runs.
        from upto import circles as circles_module  # noqa: PLC0415
        async with Session() as session:
            for instant, expected in (
                ("2026-09-14 15:59:59+00", "2026-09-13 16:00:00+00"),  # 23:59:59 Taipei, 14th
                ("2026-09-14 16:00:00+00", "2026-09-14 16:00:00+00"),  # 00:00:00 Taipei, 15th
                ("2026-09-14 00:30:00+00", "2026-09-13 16:00:00+00"),  # 08:30 Taipei — UTC's new day
            ):
                start = (await session.execute(text(
                    "select (" + circles_module.TAIPEI_DAY_START.format(now="cast(cast(:t as text) as timestamptz)")
                    + ") = cast(cast(:e as text) as timestamptz)"), {"t": instant, "e": expected})).scalar_one()
                check("the ceiling's day at {} UTC starts at {} UTC (Taipei midnight, D83)".format(
                    instant, expected), start is True, start)

        # **The one flag that makes a circle sweepable, set by this door and no other** (revision
        # 0045; owner 2026-09-14). If it stayed false the nightly sweep would never take a stranger's
        # abandoned circle; `test_circle_sweep_integration` pins the false half for operator circles.
        async with Session() as session:
            self_serve = (
                await session.execute(text("select self_serve from circle where id = :c"),
                                      {"c": circle})
            ).scalar_one()
        check("a circle made through the self-serve door is marked self_serve (the sweep's mark)",
              self_serve is True, self_serve)

        # ---- join: a second seat, and a third with the SAME nickname --------------------------
        joined = await client.post(f"{BASE}/circles/{circle}/join",
                                   json={"ticket": ticket, "nickname": "小明"})
        check("a tap on the shared link grows a seat", joined.status_code == 201,
              f"got {joined.status_code}: {joined.text[:120]}")
        joiner_key = joined.json()["key"]
        check("and hands that device a key of its own", joiner_key != creator_key)

        twin = await client.post(f"{BASE}/circles/{circle}/join",
                                 json={"ticket": ticket, "nickname": "小明"})
        check("a duplicate nickname is legal and is not refused (§7)", twin.status_code == 201,
              f"got {twin.status_code}")

        # ---- the seat list -------------------------------------------------------------------
        seats = await client.get(f"{BASE}/circles/{circle}/members",
                                 headers={"Authorization": "Bearer " + joiner_key})
        check("any member of the circle can read the seats", seats.status_code == 200)
        payload = seats.json()
        check("the list is nicknames in join order, duplicates kept as the server holds them",
              [m["nickname"] for m in payload["members"]] == ["小美", "小明", "小明"],
              str(payload["members"]))
        check("and carries NO member id — §3.0, H3: an identifier a screen never needs",
              all(set(m) == {"nickname"} for m in payload["members"]), str(payload["members"]))
        check("the cap travels in the payload so no screen hard-codes ten",
              payload["cap"] == 10 and payload["seats"] == 3, str(payload))

        anonymous = await client.get(f"{BASE}/circles/{circle}/members")
        check("a circle's membership is not readable without a credential",
              anonymous.status_code == 401, f"got {anonymous.status_code}")

        # ---- re-issue: operator only ----------------------------------------------------------
        refused = await client.post(f"{BASE}/circles/{circle}/join-ticket",
                                    headers={"Authorization": "Bearer " + joiner_key})
        check("an ordinary member cannot replace the link (D105)", refused.status_code == 403,
              f"got {refused.status_code}")

        again = await client.post(f"{BASE}/circles/{circle}/join-ticket",
                                  headers={"Authorization": "Bearer " + creator_key})
        check("the creator can", again.status_code == 201, f"got {again.status_code}")
        fresh = ticket_of(again.json()["join_link"])
        check("and the new ticket is a different secret", fresh != ticket)

        # **0047 (owner 「拆」, 2026-09-16): the creator keeps the link and not the table.** The two
        # powers were one boolean until today, so the first person to tap 開一個圈子 could read
        # every stored factor and its contributor — which at a small table is whose preference moved
        # a place. The mint above proves the invite half; this proves the other half is gone.
        async with Session() as session:
            flags = (
                await session.execute(
                    text("select ds.operator, ds.evidence from device_secret ds "
                         "join member m on m.principal_id = ds.principal_id "
                         "where m.circle_id = :c and ds.secret_sha256 = :h"),
                    {"c": circle, "h": sha256(creator_key.encode()).hexdigest()},
                )
            ).one()
        check("the creator's credential carries the invite power", flags.operator is True, flags)
        check("and NOT the evidence table (0047)", flags.evidence is False, flags)

        dead = await client.post(f"{BASE}/circles/{circle}/join",
                                 json={"ticket": ticket, "nickname": "太慢"})
        check("the replaced link answers 410 and says it was replaced", dead.status_code == 410,
              f"got {dead.status_code}: {dead.text[:80]}")
        unknown = await client.post(f"{BASE}/circles/{circle}/join",
                                    json={"ticket": "nonsense", "nickname": "x"})
        check("a ticket nobody issued answers 404, which is a different sentence",
              unknown.status_code == 404 and unknown.text != dead.text)

        # **Re-issue does NOT eject.** Stated in the ticket and asserted here, because a screen's
        # wording will imply whichever this file proves.
        after = await client.get(f"{BASE}/circles/{circle}/members",
                                 headers={"Authorization": "Bearer " + creator_key})
        check("re-issuing removes nobody — the seats are exactly as they were",
              after.json()["seats"] == 3, str(after.json()))

        # ---- the cap: what actually bounds a leaked ticket -------------------------------------
        for n in range(4, 11):
            grown = await client.post(f"{BASE}/circles/{circle}/join",
                                      json={"ticket": fresh, "nickname": f"客{n}"})
            if grown.status_code != 201:
                check(f"seat {n} should have been allowed", False, grown.text[:120])
                break
        eleventh = await client.post(f"{BASE}/circles/{circle}/join",
                                     json={"ticket": fresh, "nickname": "第十一"})
        check("the eleventh seat is refused — D110 is what bounds a leaked link",
              eleventh.status_code == 409, f"got {eleventh.status_code}: {eleventh.text[:120]}")
        check("and the refusal names the number rather than restating it in prose",
              "10" in eleventh.text, eleventh.text[:120])

        # **Nothing was written by the refusal.** The count is the assertion: a refused join that
        # left a principal or a device_secret behind would be invisible from the outside.
        async with Session() as session:
            seats_now, principals, secrets_now = [
                (await session.execute(text(f"select count(*) from {t}"))).scalar_one()
                for t in ("member", "principal", "device_secret")
            ]
        check("the refused join wrote nothing — no seat, no principal, no secret",
              seats_now == 10 and principals == 10 and secrets_now == 10,
              f"member={seats_now} principal={principals} device_secret={secrets_now}")

        still = await client.get(f"{BASE}/circles/{circle}/members",
                                 headers={"Authorization": "Bearer " + creator_key})
        check("and the circle still reads ten seats against a cap of ten",
              still.json()["seats"] == 10 and still.json()["cap"] == 10)

        # ---- the cap under a RACE, which is what actually bounds a leaked ticket ---------------
        #
        # **The reviewer's find, 2026-09-13.** Counting seats and then inserting one is
        # check-then-act. Without a lock on the circle row, two callers at nine seats both count
        # nine, both pass, and both insert — **eleven seats in a circle D110 rules at ten.**
        # `uq_member_one_seat_per_circle` does not help: it is per principal, and the join path
        # mints a fresh one every time.
        #
        # **Driven at `grow_seat` with two real transactions, NOT with two HTTP requests** — and
        # that is the second finding here. The first version of this check fired two concurrent
        # POSTs and passed **with the lock removed**, because nothing forced the two reads to land
        # before either write: a check that cannot observe the effect it is controlling for (H92).
        # Two sessions that both read, then both write, is the race itself rather than a hope of it.
        from upto.issue import SeatRefused as _Refused  # noqa: PLC0415
        from upto.issue import grow_seat as _grow  # noqa: PLC0415

        raced = (await client.post(BASE + "/circles",
                                   json={"name": "賽跑", "nickname": "主辦"})).json()
        race_circle, race_ticket = raced["circle_id"], ticket_of(raced["join_link"])
        for n in range(2, 10):
            await client.post(f"{BASE}/circles/{race_circle}/join",
                              json={"ticket": race_ticket, "nickname": f"第{n}"})

        # **One engine per racer, and this line is the whole reason the check works.** Measured
        # 2026-09-13: with both tasks on one engine, task 2 did not read until **37 ms after task 1
        # had committed** — the connection pool serialised them, so the two never overlapped and
        # the check passed with the lock removed. With an engine each they read 0 and 0 within a
        # millisecond of each other, which is the race. *A concurrency test on a shared pool is
        # testing the pool.*
        racers = [async_sessionmaker(create_async_engine(test_url), expire_on_commit=False)
                  for _ in range(2)]

        async def one_seat(maker, label):
            async with maker() as own:
                try:
                    await _grow(own, race_circle, label)
                    await own.commit()
                    return "seated"
                except _Refused as refused:
                    await own.rollback()
                    return refused.reason

        outcome = sorted(await asyncio.gather(one_seat(racers[0], "同時1"),
                                              one_seat(racers[1], "同時2")))
        check("two transactions racing for seat ten: one seat, one refusal",
              outcome == ["full", "seated"], str(outcome))

        async with Session() as probe:
            held = (
                await probe.execute(text("select count(*) from member where circle_id = :c"),
                                    {"c": race_circle})
            ).scalar_one()
        check("and the circle holds exactly ten — the cap survives a race, not just a queue",
              held == 10, f"it holds {held}")

        # ---- blank input: a 422 the person can act on, never a 500 -----------------------------
        #
        # **Both of these were 500s until 2026-09-13, found by attacking this file's own subject
        # rather than by a gate.** `min_length=1` counts spaces, so three spaces passed Pydantic and
        # reached the database's own check constraint. The constraint was right and the answer was
        # wrong twice: a 500 says «we broke», and the person who typed spaces learns nothing.
        for field, payload in (("name", {"name": "   ", "nickname": "小美"}),
                               ("nickname", {"name": "宿舍", "nickname": "   "})):
            blank = await client.post(BASE + "/circles", json=payload)
            check(f"a {field} of only spaces is refused as the caller's mistake, not a 500",
                  blank.status_code == 422, f"got {blank.status_code}: {blank.text[:120]}")

        # **And the reason a blank nickname gave was a LIE, which is the worse half.** `grow_seat`
        # caught every `IntegrityError` and reported «seat-taken», so a blank nickname came back as
        # «that principal already holds a seat» — a sentence with no relation to what happened.
        # H88's shape in code: a claim in the grammar of a diagnosis, from something that did not
        # diagnose. The constraint name is read now, so this asserts the branch exists at all.
        from upto.issue import SeatRefused, grow_seat  # noqa: PLC0415

        async with Session() as probe:
            circle_for_blank = (
                await probe.execute(text("insert into circle (name) values ('空白') returning id"))
            ).scalar_one()
            try:
                await grow_seat(probe, circle_for_blank, "   ")
                check("a blank nickname reaches grow_seat and is refused", False, "it was allowed")
            except SeatRefused as refused:
                check("grow_seat names the constraint that actually broke, not the one it assumed",
                      refused.reason == "blank-nickname", f"reason was {refused.reason!r}")
            await probe.rollback()

        # ---- the one-hour life, owner-ruled 2026-09-13 ------------------------------------------
        #
        # **The clock is moved, not waited for.** A test that slept an hour would not be run, and
        # one that only checked «expires_at is not null» would pass on a ticket that never expires.
        # So the row's own timestamps are shifted and the REAL join path is driven across the
        # boundary — the enforcement is what is asserted, not the column.
        timed = (await client.post(BASE + "/circles",
                                   json={"name": "一頓飯", "nickname": "主人"})).json()
        timed_circle, timed_ticket = timed["circle_id"], ticket_of(timed["join_link"])

        async with Session() as probe:
            span = (
                await probe.execute(
                    text("select extract(epoch from (expires_at - created_at)) "
                         "from join_ticket where circle_id = :c and revoked_at is null"),
                    {"c": timed_circle},
                )
            ).scalar_one()
        check("minting sets the life to one hour from the row's own created_at",
              abs(float(span) - 3600) < 1, f"{span} seconds")

        async def shift(minutes):
            """Move this ticket's whole row back, so `now()` lands `minutes` after it was made."""
            async with Session() as probe:
                await probe.execute(
                    text("update join_ticket set created_at = now() - make_interval(mins => :m), "
                         "expires_at = now() - make_interval(mins => :m) + interval '1 hour' "
                         "where circle_id = :c and revoked_at is null"),
                    {"m": minutes, "c": timed_circle},
                )
                await probe.commit()

        await shift(59)
        early = await client.post(f"{BASE}/circles/{timed_circle}/join",
                                  json={"ticket": timed_ticket, "nickname": "準時"})
        check("a tap at +59 minutes still joins", early.status_code == 201,
              f"got {early.status_code}: {early.text[:120]}")

        await shift(61)
        late = await client.post(f"{BASE}/circles/{timed_circle}/join",
                                 json={"ticket": timed_ticket, "nickname": "太晚"})
        check("a tap at +61 minutes is refused with 410", late.status_code == 410,
              f"got {late.status_code}: {late.text[:120]}")
        check("and the expired sentence is its OWN, not the replaced-link one",
              "一小時" in late.text and late.text != dead.text, late.text[:120])

        # **Re-issue is the creator's fix for a late friend** — the whole reason it landed before
        # expiry did, and the reason the ruling costs a person nothing they cannot undo.
        renewed = await client.post(f"{BASE}/circles/{timed_circle}/join-ticket",
                                    headers={"Authorization": "Bearer " + timed["key"]})
        check("the creator can re-issue after the hour runs out", renewed.status_code == 201)
        second_chance = await client.post(
            f"{BASE}/circles/{timed_circle}/join",
            json={"ticket": ticket_of(renewed.json()["join_link"]), "nickname": "終於"})
        check("and the late friend joins on the new link", second_chance.status_code == 201,
              f"got {second_chance.status_code}: {second_chance.text[:120]}")

        async with Session() as probe:
            fresh_span = (
                await probe.execute(
                    text("select extract(epoch from (expires_at - created_at)) "
                         "from join_ticket where circle_id = :c and revoked_at is null"),
                    {"c": timed_circle},
                )
            ).scalar_one()
        check("a re-issued ticket gets its own full hour, not the remainder of the old one",
              abs(float(fresh_span) - 3600) < 1, f"{fresh_span} seconds")

        # ---- the creator's own screen: is the link live, without holding it ----------------------
        #
        # **The evaluator's correction of my first answer.** `…/check {ticket}` needs the ticket,
        # and **the creator does not have it** — it was shown once and is stored as a hash, which
        # is precisely why they are on a durable screen looking for it. A screen that must supply
        # the ticket to ask about the ticket cannot be used by the person who lost it.
        owner_view = await client.get(f"{BASE}/circles/{timed_circle}/join-ticket",
                                      headers={"Authorization": "Bearer " + timed["key"]})
        check("the creator can ask whether the link is live, holding nothing but their key",
              owner_view.status_code == 200 and owner_view.json()["active"] is True,
              owner_view.text[:140])
        check("and it carries NO link — the plaintext is not stored and never will be (D74)",
              "join_link" not in owner_view.text and "#c=" not in owner_view.text,
              owner_view.text[:140])

        stranger_view = await client.get(f"{BASE}/circles/{timed_circle}/join-ticket",
                                         headers={"Authorization": "Bearer " + joiner_key})
        check("an ordinary member cannot read the link's status",
              stranger_view.status_code in (401, 403), f"got {stranger_view.status_code}")

        # **«No live ticket» and «one that ran out» are different answers**, because the screen's
        # next sentence differs: «press re-issue» versus «press re-issue, and this is why the link
        # you sent stopped working».
        async with Session() as probe:
            await probe.execute(
                text("update join_ticket set expires_at = now() - interval '1 minute' "
                     "where circle_id = :c and revoked_at is null"), {"c": timed_circle})
            await probe.commit()
        run_out = await client.get(f"{BASE}/circles/{timed_circle}/join-ticket",
                                   headers={"Authorization": "Bearer " + timed["key"]})
        check("a link past its hour reads expired rather than merely inactive",
              run_out.json()["expired"] is True and run_out.json()["active"] is False,
              run_out.text[:140])

        # ---- is the link this device holds still good? -------------------------------------------
        #
        # **No endpoint can return a link, and that is the design working rather than a gap.** Only
        # `token_sha256` is stored, so the server cannot reconstruct a ticket it never held in
        # plaintext — which is what makes a database read, or the nightly dump in S3, useless to
        # whoever gets one. The device keeps the string; the server answers the question about it.
        async def status_of(tok, key, circle=None):
            answer = await client.post(
                f"{BASE}/circles/{circle or timed_circle}/join-ticket/check",
                json={"ticket": tok}, headers={"Authorization": "Bearer " + key})
            return answer.status_code, answer.json()

        checked = (await client.post(BASE + "/circles",
                                     json={"name": "查連結", "nickname": "主人"})).json()
        look_circle, look_key = checked["circle_id"], checked["key"]
        look_ticket = ticket_of(checked["join_link"])

        code, seen = await status_of(look_ticket, look_key, look_circle)
        check("a live ticket reads live and says when it ends",
              code == 200 and seen["status"] == "live" and seen["expires_at"], str(seen))

        # **Looking does not mint and does not revoke** — the failure frontend named: a creator
        # opening a durable screen to see the link they already shared would, by looking, kill it.
        again_code, again = await status_of(look_ticket, look_key, look_circle)
        check("looking twice changes nothing — reading a ticket never mints or revokes",
              again == seen, f"{seen} then {again}")

        replaced = await client.post(f"{BASE}/circles/{look_circle}/join-ticket",
                                     headers={"Authorization": "Bearer " + look_key})
        _, after_reissue = await status_of(look_ticket, look_key, look_circle)
        check("after a re-issue the OLD link reads revoked, not live",
              after_reissue["status"] == "revoked", str(after_reissue))
        _, new_status = await status_of(ticket_of(replaced.json()["join_link"]),
                                        look_key, look_circle)
        check("and the new one reads live", new_status["status"] == "live", str(new_status))

        _, nonsense = await status_of("nonsense", look_key, look_circle)
        check("a ticket nobody issued reads unknown rather than erroring",
              nonsense["status"] == "unknown", str(nonsense))

        not_mine = await client.post(
            f"{BASE}/circles/{look_circle}/join-ticket/check",
            json={"ticket": look_ticket}, headers={"Authorization": "Bearer " + joiner_key})
        check("an ordinary member cannot ask whether a seat-granting secret is live",
              not_mine.status_code in (401, 403), f"got {not_mine.status_code}")

        # ---- a ticket is for ONE circle ---------------------------------------------------------
        other = (await client.post(BASE + "/circles",
                                   json={"name": "宿舍", "nickname": "阿凱"})).json()
        crossed = await client.post(f"{BASE}/circles/{other['circle_id']}/join",
                                    json={"ticket": fresh, "nickname": "走錯"})
        check("a ticket presented against another circle is unknown, not a seat there",
              crossed.status_code == 404, f"got {crossed.status_code}")

        await engine.dispose()


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
        migrate = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv",
                                 env=environment, capture_output=True)
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2

        # A real server, because a status code is only real at a process boundary.
        server = subprocess.Popen(
            ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd="/srv/src", env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient() as probe:
            for _ in range(60):
                try:
                    if (await probe.get(f"http://127.0.0.1:{PORT}/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.2)
            else:
                print("the test server never came up", file=sys.stderr)
                return 2

        await scenario(test_url)
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

    failed = [label for label, ok, _ in CHECKS if not ok]
    print()
    print("A24: {} checks, {}".format(
        len(CHECKS), "all green" if not failed else "{} FAILED".format(len(failed))))
    if failed:
        print(json.dumps(failed, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
