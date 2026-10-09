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
              f"got {made.status_code}")   # never the body: it holds a key (H101)
        body = made.json()
        circle = body["circle_id"]
        creator_key = body["key"]
        link = body["join_link"]
        check("and the response carries a key and a join link",
              bool(creator_key) and bool(link))
        check("the ticket rides in the fragment, never the query (A20)",
              "#" in link and "?" not in link.split("#")[0],
              link.split("#")[0] + "#…")   # the fragment holds the ticket: never printed (H101)
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
              f"got {joined.status_code}")   # never the body: it holds a key (H101)
        joiner_key = joined.json()["key"]
        check("and hands that device a key of its own", joiner_key != creator_key)

        twin = await client.post(f"{BASE}/circles/{circle}/join",
                                 json={"ticket": ticket, "nickname": "小明"})
        check("a duplicate nickname is legal and is not refused (§7)", twin.status_code == 201,
              f"got {twin.status_code}")

        # ---- over-length: a sentence, never pydantic's list ------------------------------------
        #
        # **The surface renders a string `detail` as is and falls back to the status for anything
        # else** (frontend's ask, 2026-10-09). Pydantic's own 422 carries a list, so a person who
        # typed too much read «開不了圈子（422）». The count is code points: `👨‍👩‍👧` is 5 of them.
        def is_sentence(reply, starts: str) -> bool:
            detail = reply.json().get("detail")
            return reply.status_code == 422 and isinstance(detail, str) and detail.startswith(starts)

        async with Session() as s:
            circles_before = (await s.execute(text("select count(*) from circle"))).scalar_one()
        long_name = await client.post(BASE + "/circles", json={"name": "名" * 81, "nickname": "小美"})
        check("a circle name over 80 answers 422 with a sentence", is_sentence(long_name, "圈子名稱"),
              long_name.text[:120])
        long_nick = await client.post(BASE + "/circles", json={"name": "週四", "nickname": "暱" * 41})
        check("a nickname over 40 at creation answers 422 with a sentence",
              is_sentence(long_nick, "暱稱"), long_nick.text[:120])
        async with Session() as s:
            circles_after = (await s.execute(text("select count(*) from circle"))).scalar_one()
        check("and neither refusal wrote a circle", circles_after == circles_before,
              f"{circles_before} -> {circles_after}")
        family = await client.post(f"{BASE}/circles/{circle}/join",
                                   json={"ticket": ticket, "nickname": "👨‍👩‍👧" * 9})
        check("nine family emoji (45 code points) at join answer 422 with a sentence",
              is_sentence(family, "暱稱"), family.text[:120])

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
        check("the circle's own name travels too, so the home can say which circle this is",
              payload["name"] == "週三午餐"
              and set(payload) == {"name", "members", "seats", "cap", "creator_nickname", "your_nickname"},
              str(payload))
        check("and the creator by nickname, so a member who did not create it knows who can invite",
              payload["creator_nickname"] == "小美", str(payload))
        check("and the reader's own seat, read from the credential, so a joiner knows which name is theirs",
              payload["your_nickname"] == "小明", str(payload))

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

        # ---- the join preview (UX items 1 and 2, 2026-10-07, frontend's terms) -----------------
        async def counts():
            got = []
            async with Session() as session:
                for q in ("select count(*) from member", "select count(*) from join_ticket",
                          "select count(*) from device_secret", "select count(*) from principal",
                          "select count(*) from circle"):
                    got.append((await session.execute(text(q))).scalar_one())
            return tuple(got)
        before = await counts()
        live = None
        for _ in range(5):
            live = await client.post(f"{BASE}/circles/{circle}/join/preview",
                                     json={"ticket": fresh})
        check("a live ticket's preview answers 200", live.status_code == 200,
              f"got {live.status_code}: {live.text[:120]}")
        check("and carries the circle's name and the creator's nickname, nothing else",
              live.json() == {"circle_name": "週三午餐", "creator_nickname": "小美"}, live.text)
        check("the preview is never cached", live.headers.get("cache-control") == "no-store",
              live.headers.get("cache-control"))
        check("five previews write nothing — every count unchanged", await counts() == before,
              f"{before} → {await counts()}")
        # The sentence is pinned here as text, like 「一個人最多提三家。」 in the rounds test: the
        # screen renders it verbatim, so a wording change must be a decision, not a drift.
        PREVIEW_DEAD = ("這條連結不能用了：可能已經過期（連結只有一小時）、被換掉，或沒有複製完整。"
                        "開圈子的人可以給一條新的。")
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

        # The over-length limit's accepting edge. **Here and not beside its refusals**, because it
        # creates a circle and the check above counts rows across the whole database.
        at_cap = await client.post(BASE + "/circles", json={"name": "名" * 80, "nickname": "暱" * 40})
        check("exactly 80 and 40 are still accepted", at_cap.status_code == 201,
              f"got {at_cap.status_code}")   # never the body: it holds a key (H101)

        # (Placed after the seat-cap section: it creates two circles, and that section counts
        # rows across the whole database.)
        # Two more circles, so the two cases the first version only claimed are driven (the
        # reviewer's catch, 2026-10-08): circle A's LIVE ticket presented at a real circle B, and
        # a ticket whose hour has run out.
        second = (await client.post(BASE + "/circles",
                                    json={"name": "另一圈", "nickname": "阿B"})).json()
        third = (await client.post(BASE + "/circles",
                                   json={"name": "過期圈", "nickname": "阿C"})).json()
        expired_ticket = ticket_of(third["join_link"])
        async with Session() as session:
            await session.execute(
                text("update join_ticket set expires_at = now() - interval '1 minute' "
                     "where circle_id = :c and revoked_at is null"), {"c": third["circle_id"]})
            await session.commit()
        check("the creator is named on the second circle too (its own creating transaction)",
              (await client.post(f"{BASE}/circles/{second['circle_id']}/join/preview",
                                 json={"ticket": ticket_of(second["join_link"])})).json()
              == {"circle_name": "另一圈", "creator_nickname": "阿B"})
        dead_cases = {
            "replaced": (circle, ticket),
            "unknown": (circle, "nonsense"),
            "circle A's live ticket at a real circle B": (second["circle_id"], fresh),
            "expired": (third["circle_id"], expired_ticket),
            "a circle that does not exist": (999999999, "nonsense"),
        }
        answers = {}
        for label, (c, tk) in dead_cases.items():
            got = await client.post(f"{BASE}/circles/{c}/join/preview", json={"ticket": tk})
            answers[label] = (got.status_code, got.content, got.headers.get("cache-control"))
        check("every dead case answers the same status and the same bytes, so c= cannot be walked",
              len(set(answers.values())) == 1, answers)
        status, content, cache = next(iter(answers.values()))
        check("that answer is 404 with frontend's sentence, verbatim, and no-store",
              status == 404 and json.loads(content)["detail"] == PREVIEW_DEAD and cache == "no-store",
              (status, content[:80], cache))

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
              f"got {early.status_code}")   # never the body: it holds a key (H101)

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
              f"got {second_chance.status_code}")   # never the body: it holds a key (H101)

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

        # ---- leaving a seat (0048, owner 「可以」 2026-10-08) -----------------------------------
        # Last in the scenario on purpose: the sections above count seats and rows.
        async def counts_of(tables):
            got = {}
            async with Session() as session:
                for name in tables:
                    got[name] = (await session.execute(text(f"select count(*) from {name}"))).scalar_one()
            return got

        everything = ("member", "principal", "device_secret", "round", "proposal", "join_ticket",
                      "preference", "member_roll", "trip", "circle")
        async def prefer(member_id, value):
            async with Session() as session:
                made = (await session.execute(
                    text("insert into preference (member_id, kind, value, stance, persist, valid_from) "
                         "values (:m, 'avoid_category', :v, 'avoid', true, now()) returning id"),
                    {"m": member_id, "v": value})).scalar_one()
                await session.commit()
            return made

        async def preference_exists(preference_id):
            async with Session() as session:
                return (await session.execute(text("select count(*) from preference where id = :i"),
                                              {"i": preference_id})).scalar_one() == 1

        async with Session() as session:
            creator_id = (await session.execute(
                text("select m.id from member m join device_secret d on d.principal_id = m.principal_id "
                     "where m.circle_id = :c and d.secret_sha256 = :h"),
                {"c": circle, "h": sha256(creator_key.encode()).hexdigest()})).scalar_one()
        before = await counts_of(everything)
        async with Session() as session:
            joiner_id = (await session.execute(
                text("select m.id from member m join device_secret d on d.principal_id = m.principal_id "
                     "where m.circle_id = :c and d.secret_sha256 = :h"),
                {"c": circle, "h": sha256(joiner_key.encode()).hexdigest()})).scalar_one()
        joiner_pref = await prefer(joiner_id, "火鍋")
        creator_pref = await prefer(creator_id, "火鍋")
        before = await counts_of(everything)
        left = await client.post(f"{BASE}/circles/{circle}/leave",
                                 headers={"Authorization": "Bearer " + joiner_key})
        check("leaving answers 204", left.status_code == 204 and left.content == b"",
              f"got {left.status_code}: {left.content[:60]!r}")
        after = await counts_of(everything)
        expected = dict(before, preference=before["preference"] - 1)
        check("and deletes only the seat's own unpinned preference — every other count unchanged",
              after == expected, f"{before} → {after}")
        check("the leaving seat's kept preference is gone (owner 「刪掉」)",
              not await preference_exists(joiner_pref))
        check("another member's preference is untouched", await preference_exists(creator_pref))
        async with Session() as session:
            flag = (await session.execute(text("select has_left from member where id = :m"),
                                          {"m": joiner_id})).scalar_one()
        check("the seat is marked left, and the row is still there", flag is True, flag)
        gone = await client.get(f"{BASE}/circles/{circle}/members",
                                headers={"Authorization": "Bearer " + joiner_key})
        check("the left key no longer opens this circle — the same 401 as an unknown token",
              gone.status_code == 401, f"got {gone.status_code}")
        listed = (await client.get(f"{BASE}/circles/{circle}/members",
                                   headers={"Authorization": "Bearer " + creator_key})).json()
        check("the seat list drops it and the count frees a seat", listed["seats"] == 9, listed)

        rejoined = await client.post(f"{BASE}/circles/{circle}/join",
                                     json={"ticket": fresh, "nickname": "回來的人"})
        check("a full circle takes a new seat once one was left (D110 counts seats taken)",
              rejoined.status_code == 201, f"got {rejoined.status_code}")   # never the body: it holds a key (H101)

        quiet = {
            "already left": {"Authorization": "Bearer " + joiner_key},
            "an unknown key": {"Authorization": "Bearer " + "x" * 43},
            "another circle's key": {"Authorization": "Bearer " + second["key"]},
            "no key at all": {},
        }
        before = await counts_of(everything)
        answers = {}
        for label, headers in quiet.items():
            got = await client.post(f"{BASE}/circles/{circle}/leave", headers=headers)
            answers[label] = (got.status_code, got.content)
        check("every other leave answers the same 204 and the same empty body",
              set(answers.values()) == {(204, b"")}, answers)
        check("and writes nothing", await counts_of(everything) == before)
        async with Session() as session:
            second_creator_left = (await session.execute(
                text("select has_left from member where circle_id = :c"),
                {"c": second["circle_id"]})).scalars().all()
        check("another circle's key leaving circle A leaves nothing in its own circle",
              second_creator_left == [False], second_creator_left)

        # A principal seated in two circles: leaving one leaves the other alone.
        async with Session() as session:
            principal = (await session.execute(text("select principal_id from member where id = :m"),
                                               {"m": joiner_id})).scalar_one()
            await session.execute(
                text("insert into member (principal_id, circle_id, nickname) values (:p, :c, '兩邊都在')"),
                {"p": principal, "c": second["circle_id"]})
            await session.commit()
        elsewhere = await client.get(f"{BASE}/circles/{second['circle_id']}/members",
                                     headers={"Authorization": "Bearer " + joiner_key})
        check("the same key still opens the principal's other circle — the secret was not revoked",
              elsewhere.status_code == 200, f"got {elsewhere.status_code}")
        check("a member who is not the creator reads that circle's own creator, not the first one's",
              elsewhere.json().get("creator_nickname") == "阿B", elsewhere.text)
        check("and its own seat there, not the one it left in the first circle",
              elsewhere.json().get("your_nickname") == "兩邊都在", elsewhere.text)

        # A round opened after leaving does not pin the left seat.
        opened = await client.post(f"{BASE}/circles/{circle}/rounds", json={},
                                   headers={"Authorization": "Bearer " + creator_key})
        async with Session() as session:
            seats = (await session.execute(text("select seat_ids from round where id = :r"),
                                           {"r": opened.json()["round_id"]})).scalar_one()
        check("a round opened after the leave pins ten seats and not the left one",
              opened.status_code == 201 and joiner_id not in seats and len(seats) == 10,
              f"{opened.status_code} {seats}")

        # A seat an OPEN round has pinned keeps its preferences when it leaves — its roll still reads them.
        async with Session() as session:
            back_id = (await session.execute(
                text("select m.id from member m join device_secret d on d.principal_id = m.principal_id "
                     "where m.circle_id = :c and d.secret_sha256 = :h"),
                {"c": circle, "h": sha256(rejoined.json()["key"].encode()).hexdigest()})).scalar_one()
        check("the open round pins the seat about to leave", back_id in seats, seats)
        back_pref = await prefer(back_id, "麵食")
        back_unused = await prefer(back_id, "火鍋")
        gone_too = await client.post(f"{BASE}/circles/{circle}/leave",
                                     headers={"Authorization": "Bearer " + rejoined.json()["key"]})
        check("that leave is a 204 like every other", gone_too.status_code == 204, gone_too.status_code)
        check("and its preference stays, because the open round that pinned the seat will read it",
              await preference_exists(back_pref))
        check("the creator's preference is still untouched", await preference_exists(creator_pref))

        # When that open round is rolled, it has read them — and the left seat keeps nothing after.
        auth = {"Authorization": "Bearer " + creator_key}
        for shop in ("巷口麵店", "轉角咖哩"):
            made = await client.post(f"{BASE}/circles/{circle}/places", json={"name": shop}, headers=auth)
            if shop == "巷口麵店":
                # A category the left seat avoids, so this roll pins that preference version.
                async with Session() as session:
                    await session.execute(
                        text("update place set category = '麵食', category_model = 'test-stub', "
                             "category_prompt_version = 'v-test', category_generated_at = now(), "
                             "category_input = '測試' where id = :p"), {"p": made.json()["place_id"]})
                    await session.commit()
            proposed = await client.post(f"{BASE}/rounds/{opened.json()['round_id']}/proposals",
                                         json={"place_id": made.json()["place_id"]}, headers=auth)
            check(f"{shop} goes into the pool", proposed.status_code == 201, proposed.status_code)
        # **Every other seat still here submits by row** (提交, 2026-10-09): the round waits for each
        # pinned seat that has not left, and these seats' keys are not held here. The creator's
        # submit then completes the set and closes the round.
        async with Session() as session:
            await session.execute(
                text("insert into member_roll (round_id, circle_id, member_id) "
                     "select r.id, r.circle_id, m.id from round r join member m on m.id = any(r.seat_ids) "
                     "where r.id = :r and not m.has_left and m.id <> "
                     "  (select m2.id from member m2 join device_secret d on d.principal_id = m2.principal_id "
                     "   where m2.circle_id = r.circle_id and d.secret_sha256 = :h)"),
                {"r": opened.json()["round_id"], "h": sha256(creator_key.encode()).hexdigest()})
            await session.commit()
        rolled = await client.post(f"{BASE}/rounds/{opened.json()['round_id']}/submit", headers=auth)
        check("the round that pinned the left seat rolls", rolled.status_code == 200
              and rolled.json().get("winning_place_id") is not None,
              f"got {rolled.status_code}: {rolled.text[:120]}")
        check("the left seat's preference this roll used is kept — its contribution pins it (D24/D25)",
              await preference_exists(back_pref))
        async with Session() as session:
            pinned_by = (await session.execute(
                text("select count(*) from weight_contribution where preference_id = :i"),
                {"i": back_pref})).scalar_one()
        check("and it is pinned by this roll's own contribution, written before the delete ran",
              pinned_by >= 1, pinned_by)
        check("the left seat's preference the roll did not use is gone once the roll has read it",
              not await preference_exists(back_unused))
        check("while a seated member's preference is still untouched", await preference_exists(creator_pref))

        # The creator may leave; the preview then names nobody.
        await client.post(f"{BASE}/circles/{second['circle_id']}/leave",
                          headers={"Authorization": "Bearer " + second["key"]})
        preview = await client.post(f"{BASE}/circles/{second['circle_id']}/join/preview",
                                    json={"ticket": ticket_of(second["join_link"])})
        check("after the creator leaves, the preview's creator is null (the screen says 有人)",
              preview.json() == {"circle_name": "另一圈", "creator_nickname": None}, preview.text)
        seats_after = await client.get(f"{BASE}/circles/{second['circle_id']}/members",
                                       headers={"Authorization": "Bearer " + joiner_key})
        check("and the member list agrees: one query, so the two readers cannot name different people",
              seats_after.json().get("creator_nickname") is None, seats_after.text)

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
