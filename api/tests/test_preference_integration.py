#!/usr/bin/env python3
"""A1 / item 4 — the preference table, its endpoints and the promises around them.

Run inside the stack:
    docker compose exec api python /srv/tests/test_preference_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**The assertion that matters most is an absence: nothing reaches the circle's stream when a
preference is written.** Every other write in this application announces itself, and §3.0's rule is
that a preference is *silent* rather than merely anonymous — at five people the timing of an event
is one guess from a name. A future reader adding a `publish(...)` "for consistency" would undo the
rule, and only a test that watches the stream catches it.

The other three worth reading: a change **appends** and the older row is untouched (D25, and D24's
reason — a pinned row must not shift underneath a contribution); an `allow` row **removes** a
category from what is in force without deleting anything; and a version some round pinned **cannot
be erased**, which the database refuses on its own (`ON DELETE RESTRICT`) rather than the job
remembering.
"""

import asyncio
import ast
import inspect
import os
import secrets as pysecrets
import subprocess
import sys
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_preference_check"

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   {}".format(name))
    else:
        FAILURES.append(name)
        print("FAIL {} {}".format(name, detail))


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url

    import httpx  # noqa: PLC0415

    from upto import stream  # noqa: PLC0415
    from upto.main import app  # noqa: PLC0415
    from upto.preferences import BUDGET_BANDS, CATEGORIES  # noqa: PLC0415
    from upto.privacy import erase  # noqa: PLC0415

    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    token = "t-" + pysecrets.token_urlsafe(24)
    categorised: dict = {}

    async with Session() as session:
        circle = (
            await session.execute(text("insert into circle (name) values ('週三') returning id"))
        ).scalar_one()
        principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        member = (
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:p, :c, 'Kevin') returning id"
                ),
                {"p": principal, "c": circle},
            )
        ).scalar_one()
        await session.execute(
            # **An operator's device (D105), because this test asserts D72's allocation table.** The
            # reveal payload's shape follows the credential since revision 0025: a member sees what
            # happened, an operator also sees how the odds got there. Asserting the allocation from a
            # member token would be asserting a leak — and the allocation is *the* statement this
            # test needs, since D72's table is the truth of the draw and a zero-weight place holding
            # 0 of 36 outcomes is a property rather than luck.
            text("insert into device_secret (principal_id, secret_sha256, operator) "
                 "values (:p, :h, true)"),
            {"p": principal, "h": sha256(token.encode()).hexdigest()},
        )
        for code, name in (("63000020", "信義區"),):
            await session.execute(
                text(
                    "insert into township_station "
                    "(township_code, township_name, station_id, station_name, resolution) "
                    "values (:c, :n, 'C0A980', '測試站', 'town_code')"
                ),
                {"c": code, "n": name},
            )
        # A proposable set with two categorised places, so D22's breadth is exercised on real rows
        # rather than asserted against an empty pool: avoiding 火鍋 must remove exactly one of two.
        publication = (
            await session.execute(
                text(
                    "insert into place_publication (source, content_sha256, detected_at, "
                    "payload_bytes, entry_name, entry_bytes, scope) "
                    "values ('fda-97', repeat('c', 64), now(), 1000, 'x.csv', 1000, "
                    "'餐飲場所 / 臺北市') returning id"
                )
            )
        ).scalar_one()
        for registry, name, category in (
            ("A-1", "小林火鍋", "火鍋"),
            ("A-2", "西家牛排", "西式"),
        ):
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, name, name_raw, "
                    "address, address_raw, township_code, township_name, origin) "
                    "values (:pub, :r, :n, :n, '臺北市信義區一號', '臺北市信義區一號', "
                    "'63000020', '信義區', 'reference')"
                ),
                {"pub": publication, "r": registry, "n": name},
            )
            place_id = (
                await session.execute(
                    # **No `name` on a reference place** — `ck_place_reference_shape` refuses it,
                    # because D28 rules that a reference place carries only its 登錄字號 and the
                    # display name comes from the latest publication at read time rather than from
                    # a copy that would drift.
                    text(
                        "insert into place (origin, registry_no, category, category_model, "
                        "category_prompt_version, category_generated_at, category_input) "
                        "values ('reference', :r, :c, 'test', 'v-test', now(), :n) "
                        "returning id"
                    ),
                    {"r": registry, "n": name, "c": category},
                )
            ).scalar_one()
            categorised[category] = place_id
        await session.commit()

    auth = {"Authorization": "Bearer {}".format(token)}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        path = "/circles/{}/preferences".format(circle)

        # --- D67: one 401 for both halves --------------------------------------------
        answer = await client.post(path, json={"kind": "budget", "value": "tight"})
        check("no token is 401", answer.status_code == 401, answer.status_code)
        answer = await client.get(path)
        check("the read needs a token too", answer.status_code == 401, answer.status_code)

        # --- the closed lists, refused and never coerced (D38, D39) -------------------
        for body, why in (
            ({"kind": "mood", "value": "tight"}, "an unknown kind"),
            ({"kind": "budget", "value": "500元"}, "a typed budget"),
            ({"kind": "budget", "value": "tight", "stance": "avoid"}, "a budget with a stance"),
            ({"kind": "avoid_category", "value": "拉麵"}, "a category outside D38's ten"),
            ({"kind": "avoid_category", "value": "火鍋"}, "a category with no stance"),
        ):
            answer = await client.post(path, json=body, headers=auth)
            check("{} is refused with 400".format(why), answer.status_code == 400,
                  "{} {}".format(answer.status_code, answer.text[:120]))

        # --- the write is silent: 204, empty, and nothing on the stream ---------------
        published = []
        original_publish = stream.publish
        stream.publish = lambda *args, **kwargs: published.append((args, kwargs))
        try:
            answer = await client.post(
                path, json={"kind": "budget", "value": "tight"}, headers=auth
            )
        finally:
            stream.publish = original_publish
        check("a write answers 204", answer.status_code == 204, answer.status_code)
        check("with an empty body", answer.content == b"", repr(answer.content[:60]))
        check("and publishes NOTHING to the circle's stream (§3.0)", published == [],
              repr(published))

        # **The runtime check above passes trivially today and that is why this one exists.**
        # `preferences.py` does not import `publish` at all, so patching it proves only that
        # nothing indirect called it. What has to be guarded is the *future* reader adding a
        # publish "for consistency" with every other write in the application.
        #
        # **Parsed, not grepped — and the first version was grepped and failed on its own
        # prose.** The module's docstring says "the absence of a `publish(...)` call is
        # load-bearing", so a string scan finds `publish(` in the sentence forbidding it. That is
        # `test_web_surface`'s trap exactly: a file that quotes the thing it forbids cannot be
        # scanned as text. Walking the AST asks the precise question — is there a *call* to
        # something named `publish` — and prose cannot answer it.
        import ast as python_ast  # noqa: PLC0415
        import inspect  # noqa: PLC0415

        from upto import preferences as preferences_module  # noqa: PLC0415

        tree = python_ast.parse(inspect.getsource(preferences_module))
        calls = [
            node.func.id if isinstance(node.func, python_ast.Name) else node.func.attr
            for node in python_ast.walk(tree)
            if isinstance(node, python_ast.Call)
            and isinstance(node.func, (python_ast.Name, python_ast.Attribute))
        ]
        check("and the module calls `publish` nowhere at all — the absence is load-bearing",
              "publish" not in calls, [c for c in calls if "publish" in c])

        # --- persist defaults to false (D17) -----------------------------------------
        async with Session() as session:
            row = (
                await session.execute(
                    text("select persist, expires_on, stance from preference where kind='budget'")
                )
            ).one()
        check("persist defaults to false — the default is not to keep", row.persist is False,
              row.persist)
        check("a budget carries the month's end (D25)", row.expires_on is not None)
        check("and no stance", row.stance is None)

        # --- a change appends; the older row is untouched (D25, D24) ------------------
        answer = await client.post(
            path, json={"kind": "budget", "value": "easy", "persist": True}, headers=auth
        )
        check("the second write is not a conflict — no 409", answer.status_code == 204,
              answer.status_code)
        async with Session() as session:
            rows = (
                await session.execute(
                    text(
                        "select value, persist from preference where kind='budget' "
                        "order by valid_from, id"
                    )
                )
            ).all()
        check("both versions exist — nothing was edited", len(rows) == 2, rows)
        check("and the first still says what it said", rows[0].value == "tight", rows[0])

        answer = await client.get(path, headers=auth)
        body = answer.json()
        check("the read resolves the value in force server-side",
              body["budget"]["value"] == "easy", body["budget"])
        check("and hands over no history", "versions" not in body and "rows" not in body,
              sorted(body))
        check("the month is stated so a screen need not re-derive it",
              body["budget"]["expires_on"] is not None)
        check("and it is not expired today", body["budget"]["expired"] is False,
              body["budget"])

        # **A2-G13c: the payload states the server's month so no client derives one.** The
        # assertion that matters is not the format — it is that `month` and `expires_on` come from
        # the same boundary. A field that merely looks like a month can be derived from a second
        # clock and agree with the first one for every day but the last of a month, which is the
        # only day anybody would notice. So this compares them.
        check("the payload states the server's own month (A2-G13c)",
              len(body.get("month", "")) == 7 and body["month"][4] == "-", body.get("month"))
        check("and it is the same boundary `expires_on` was computed against, not a second clock",
              body["budget"]["expires_on"][:7] == body["month"],
              (body.get("month"), body["budget"]["expires_on"]))

        # --- a set of avoided categories, and un-avoiding one ------------------------
        for value in ("火鍋", "燒烤"):
            answer = await client.post(
                path,
                json={"kind": "avoid_category", "value": value, "stance": "avoid"},
                headers=auth,
            )
            check("avoiding {} is accepted".format(value), answer.status_code == 204,
                  answer.status_code)
        body = (await client.get(path, headers=auth)).json()
        check("a member may avoid MORE THAN ONE category",
              [r["value"] for r in body["avoid_categories"]] == ["火鍋", "燒烤"],
              body["avoid_categories"])
        check("and D22's breadth counts what those settings actually zero — 1 of 2",
              (body["breadth"]["zeroed"], body["breadth"]["proposable"]) == (1, 2),
              body["breadth"])

        answer = await client.post(
            path, json={"kind": "avoid_category", "value": "火鍋", "stance": "allow"},
            headers=auth,
        )
        check("un-avoiding is accepted", answer.status_code == 204, answer.status_code)
        body = (await client.get(path, headers=auth)).json()
        check("an `allow` removes it from what is in force",
              [r["value"] for r in body["avoid_categories"]] == ["燒烤"],
              body["avoid_categories"])
        async with Session() as session:
            kept = (
                await session.execute(
                    text("select count(*) from preference where kind='avoid_category'")
                )
            ).scalar()
        check("without deleting anything — three rows for two categories", kept == 3, kept)

        # --- nothing about anyone else, and the coverage number (H3, §3.0) -----------
        check("the payload names no other member",
              "members" not in body and "circle" not in body, sorted(body))
        check("it states what an avoid can currently reach",
              body["category_coverage"]["reference_rows"] >= 0
              and 0.0 <= body["category_coverage"]["share"] <= 1.0,
              body["category_coverage"])

        # D22's breadth, and the assertion is as much about the *denominator* as the number:
        # the evaluator refuses an unstated denominator at the gate, because the same share means
        # three different things over three candidate pools.
        breadth = body["breadth"]
        check("D22's breadth counts the proposable set and says what it counted",
              breadth["proposable"] == 2 and "proposable set" in breadth["denominator"],
              breadth)
        check("and 燒烤 alone removes none of the two categorised places",
              breadth["zeroed"] == 0, breadth)
        # **The name is asserted, because the name was the defect.** `removed` taught a mechanism the
        # product does not have — an avoidance zeroes a place's weight (D103/D45) and never takes it
        # out of the proposable set — and a session writing a spec against this payload wrote 「拿掉」
        # from reading the old field. A field name is a claim about behaviour; this pins the claim.
        check("breadth reports `zeroed` and not `removed`",
              "zeroed" in breadth and "removed" not in breadth, sorted(breadth))
        # And the denominator still travels with it (D22): a share whose base is unstated means three
        # different things over three candidate pools.
        check("breadth still names its denominator", bool(breadth.get("denominator")), breadth)
        # **D22's threshold, and the invariant that decides whether it can ever fire.**
        check("breadth carries the ruled threshold", breadth.get("threshold") == 0.5, breadth)
        # `crossed` is decided server-side, never by the browser — same argument as `counts` on A6's
        # seat list: a surface that computes it can compute it wrong.
        check("breadth states whether the line was crossed rather than leaving it to the client",
              isinstance(breadth.get("crossed"), bool), breadth)
        # **The ceiling: an uncategorised place can never be zeroed by a category avoidance**, so
        # `breadth.share` can never exceed the categorised share. Measured 2026-08-19 by avoiding all
        # ten of D38's categories at once: 15,555 of 36,499 = 0.4262, exactly `category_coverage.share`.
        # **That is why threshold 0.5 cannot be crossed until the classifier passes 50% coverage**, and
        # it is asserted here so the relationship is a property rather than an observation somebody made
        # once. If this ever fails, either an uncategorised place is being zeroed or the two figures have
        # stopped sharing a denominator.
        check("breadth.share cannot exceed the categorised share",
              breadth["share"] <= body["category_coverage"]["share"] + 1e-9,
              (breadth["share"], body["category_coverage"]["share"]))
        # **This asserted `threshold is None` until 2026-08-19, and it was right until it wasn't.**
        # D22 named no line, so the payload refused to invent one and a screen could state the share
        # but never say *crossed*. The owner then ruled 0.5 (`f51aec0`) and this assertion became a
        # test requiring the absence of something the ruling requires to be present — the fourth time
        # today that a decision moved and a statement of the decision stayed behind. Replaced by the
        # threshold and `crossed` checks above; kept as a comment because the *reason* the field was
        # null is still the rule for any future figure D22 has not named.
        #
        # **What is still true and now measurable: the warning cannot fire yet.** `breadth.share` is
        # capped by the categorised share (asserted above), so 0.5 is unreachable until the classifier
        # passes 50% coverage — 42.62% on the day it was ruled. The precondition is a number now
        # rather than "when a threshold exists", which is a better `n/a` than the evaluator had.
        check("crossed is false while nothing is avoided",
              breadth["crossed"] is False, breadth)

        # --- the API's lists and the database's CHECKs agree -------------------------
        # **One transaction per row, and the reason is a property worth knowing.** PostgreSQL's
        # `now()` is the *transaction* timestamp, so two versions of the same key written inside
        # one transaction share a `valid_from` and `uq_preference_budget_version` refuses the
        # second. That is the index doing exactly its job — two versions at the same instant is a
        # contradiction, since neither could be said to be in force — and the endpoint never hits
        # it, because one request is one transaction. The first draft of this test did hit it, and
        # the refusal was right.
        for value in CATEGORIES:
            async with Session() as session:
                await session.execute(
                    text(
                        "insert into preference (member_id, kind, value, stance, persist) "
                        "values (:m, 'avoid_category', :v, 'allow', false)"
                    ),
                    {"m": member, "v": value},
                )
                await session.commit()
        for band in BUDGET_BANDS:
            async with Session() as session:
                await session.execute(
                    text(
                        "insert into preference (member_id, kind, value, persist, expires_on) "
                        "values (:m, 'budget', :v, false, current_date)"
                    ),
                    {"m": member, "v": band},
                )
                await session.commit()
        check("every value the API allows, the database allows too", True)

        collided = None
        try:
            async with Session() as session:
                for band in BUDGET_BANDS:
                    await session.execute(
                        text(
                            "insert into preference (member_id, kind, value, persist, expires_on) "
                            "values (:m, 'budget', :v, false, current_date)"
                        ),
                        {"m": member, "v": band},
                    )
                await session.commit()
        except Exception as failure:  # noqa: BLE001 — the refusal is the measurement
            collided = type(failure).__name__
        check("two versions of one key at the same instant are refused (the in-force guarantee)",
              collided is not None, collided)

        # --- A1's Done condition, as a probe over real rolls (owner-ruled 2026-08-18) ----
        #
        # **Not "tests green": a measurable, user-visible outcome.** One member avoids 火鍋; the
        # circle rolls repeatedly with a 火鍋 place and a 西式 place both in the pool; the 火鍋
        # place must win **zero** times, because D45's absorbing zero gives it zero of the 36
        # outcomes rather than merely fewer. The numbers are printed so the claim is a measurement
        # and not a test name.
        #
        # **火鍋 is re-avoided here, and the first draft of this probe forgot to.** The test
        # un-avoided 火鍋 a few lines up to prove `allow` works, so at this point the member avoids
        # only 燒烤 — and neither seeded place is 燒烤, so the probe measured a circle with no
        # applicable preference and reported 12 wins out of 20. The failure was correct and the
        # probe was wrong. Re-avoiding also proves the round trip `avoid → allow → avoid`, which no
        # other assertion covers.
        answer = await client.post(
            path, json={"kind": "avoid_category", "value": "火鍋", "stance": "avoid"},
            headers=auth,
        )
        check("re-avoiding after an allow is accepted", answer.status_code == 204,
              answer.status_code)
        body = (await client.get(path, headers=auth)).json()
        # **Only 火鍋** — and the reason is worth stating, because the first draft expected 燒烤 too.
        # The lists-agree block above inserted an `allow` row for *every* category to prove the
        # database accepts each one, and those rows are later than the 燒烤 avoid, so 燒烤 is now
        # allowed. Latest-wins did exactly what it says; the expectation was wrong.
        check("and it is back in what is in force",
              [r["value"] for r in body["avoid_categories"]] == ["火鍋"],
              body["avoid_categories"])

        rolls = 20
        winners: dict = {}
        for _ in range(rolls):
            opened = await client.post(
                "/circles/{}/rounds".format(circle), json={}, headers=auth
            )
            round_id = opened.json()["round_id"]
            for place_id in categorised.values():
                await client.post(
                    "/rounds/{}/proposals".format(round_id),
                    json={"place_id": place_id},
                    headers=auth,
                )
            rolled = await client.post("/rounds/{}/roll".format(round_id), headers=auth)
            if rolled.status_code != 200:
                check("the roll succeeded", False,
                      "{} {}".format(rolled.status_code, rolled.text[:200]))
                break
            answer_body = rolled.json()
            winner = answer_body["winning_place_id"]
            winners[winner] = winners.get(winner, 0) + 1
            # D72's table is the truth of the draw, so the allocation is the stronger statement:
            # an avoided place holds **zero of the 36 outcomes**, not merely fewer, which is why
            # zero wins is a property rather than twenty lucky rolls.
            allocation = answer_body["allocation"]

        hot_pot = categorised["火鍋"]
        western = categorised["西式"]
        print(
            "\n  probe over {} rolls: 火鍋 place won {} time(s), 西式 place won {} time(s)".format(
                rolls, winners.get(hot_pot, 0), winners.get(western, 0)
            )
        )
        check("D22/A1 Done: an avoided category wins ZERO rolls out of {}".format(rolls),
              winners.get(hot_pot, 0) == 0, winners)
        check("and the place nobody avoided won all of them",
              winners.get(western, 0) == rolls, winners)
        check("D72's table gives the avoided place 0 of the 36 outcomes — a property, not luck",
              allocation.get(str(hot_pot), 0) == 0, allocation)
        check("and the other place all 36",
              allocation.get(str(western), 0) == 36, allocation)

        async with Session() as session:
            pinned_rows = (
                await session.execute(
                    text(
                        "select count(*) from weight_contribution "
                        "where contributor = 'preference' and preference_id is not null "
                        "and channel = 'private' and effect = 0"
                    )
                )
            ).scalar()
            zero_weights = (
                await session.execute(
                    text(
                        "select count(*) from proposal where place_id = :p and weight = 0"
                    ),
                    {"p": hot_pot},
                )
            ).scalar()
        print("  {} preference contribution(s) written, each pinning its version; "
              "{} of {} rounds recorded the 火鍋 place at weight 0".format(
                  pinned_rows, zero_weights, rolls))
        check("every roll pinned the preference version it read (D24/D25)",
              pinned_rows == rolls, pinned_rows)
        check("and stored the avoided place at weight zero",
              zero_weights == rolls, zero_weights)

    # --- a version a round pinned cannot be erased (D24, D25) ------------------------
    async with Session() as session:
        pinned = (
            await session.execute(
                text(
                    "insert into preference (member_id, kind, value, stance, persist) "
                    "values (:m, 'avoid_category', '日式', 'avoid', false) returning id"
                ),
                {"m": member},
            )
        ).scalar_one()
        round_id = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, date_trunc('hour', now()), false) returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        place_id = (
            await session.execute(
                text(
                    "insert into place (circle_id, origin, name) "
                    "values (:c, 'circle-local', '巷口麵店') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        # A contribution may only be about a **pooled** place — `fk_contribution_pooled_place`
        # points at `(round_id, place_id)` in `proposal`, which is D70's rule in the schema: no
        # place enters the pool that a member did not put there (D37's surviving line).
        await session.execute(
            text(
                "insert into proposal (round_id, place_id, member_id) values (:r, :p, :m)"
            ),
            {"r": round_id, "p": place_id, "m": member},
        )
        await session.execute(
            text(
                "insert into weight_contribution (round_id, place_id, channel, contributor, "
                "effect, reason, reason_visibility, member_id, preference_id) "
                "values (:r, :p, 'private', 'preference', 0, '避開的類型：日式', "
                "'represented_member', :m, :pref)"
            ),
            {"r": round_id, "p": place_id, "m": member, "pref": pinned},
        )
        await session.commit()

    # The private channel may not put its reason on the table (0022's CHECK).
    leaked = None
    try:
        async with Session() as session:
            await session.execute(
                text(
                    "insert into weight_contribution (round_id, place_id, channel, contributor, "
                    "effect, reason, reason_visibility) "
                    "values (:r, :p, 'private', 'preference', 0, 'x', 'table')"
                ),
                {"r": round_id, "p": place_id},
            )
            await session.commit()
    except Exception as failure:  # noqa: BLE001 — the refusal is the measurement
        leaked = type(failure).__name__
    check("a private reason may never be public (H3, enforced by the database)",
          leaked is not None, leaked)

    # The erasure job leaves the pinned row alone rather than failing on it.
    os.environ["UPTO_DATABASE_URL"] = test_url
    await erase.run(dry_run=False)
    async with Session() as session:
        survived = (
            await session.execute(
                text("select count(*) from preference where id = :i"), {"i": pinned}
            )
        ).scalar()
        # **The property, not a count.** Every not-kept row still present must be one a round
        # pinned — counting survivors would make this assertion depend on how many rows the rest
        # of the test happened to create, which is how a test starts asserting its own history.
        unpinned_left = (
            await session.execute(
                text(
                    "select count(*) from preference p where p.persist = false and not exists ("
                    "  select 1 from weight_contribution wc where wc.preference_id = p.id)"
                )
            )
        ).scalar()
    check("the erasure job left the pinned version alone", survived == 1, survived)
    check("and left nothing else behind — every survivor is pinned by a round",
          unpinned_left == 0, unpinned_left)

    # ---- D103's third kind: 「不吃 X」, recorded as a choice and never as a condition -----------
    #
    # **The list is 衛福部's eleven food-label allergen groups and the word 過敏 appears nowhere.**
    # The API records what a person does not eat; *why* is health information about an identified
    # person, and this product does not hold it. That rule binds the copy rather than the schema, so
    # it is asserted against the modules' own text — a CHECK cannot enforce it.
    from upto import preferences as preference_module  # noqa: PLC0415
    from upto.engine import load as loader_module  # noqa: PLC0415

    # **The rule is about user-facing strings, and the first version of this check got that wrong.**
    # It scanned the whole module and failed — because the comment *stating* the rule names the word
    # it forbids. That is the third time this repository has built a guard that fires on its own
    # documentation (the font derivation demanding a `═` from a CSS comment; a string scan for
    # `publish(` tripping on its own docstring), and the fix is the same one: walk the AST and look
    # at what actually reaches a person. Comments are not in the AST at all, and docstrings are
    # excluded by name.
    #
    # **Scope, stated so it is not mistaken for more than it is:** this covers the API's own strings —
    # the 400 details and the payload's prose. The *screen's* copy lives in `app/web` and is the
    # frontend session's to hold; no check here can reach it.
    module_ast = ast.parse(inspect.getsource(preference_module))
    docstrings = set()
    for node in ast.walk(module_ast):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    spoken = [n.value for n in ast.walk(module_ast)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and id(n) not in docstrings]
    check("no string the API can utter contains 過敏 (D103)",
          not [s for s in spoken if "過敏" in s],
          [s for s in spoken if "過敏" in s])
    check("and the check is looking at real strings rather than nothing",
          any("must be one of" in s for s in spoken), len(spoken))
    check("the eleven groups are the closed list", len(preference_module.INGREDIENTS) == 11,
          preference_module.INGREDIENTS)

    # **The loader's category pass names its kind, rather than taking every stance-bearing row.**
    # This is the defect this ticket was escalated over: an ingredient compared against
    # `place.category` matches nothing, which is the right answer by *type confusion*. Asserted in
    # source because the failure has no runtime symptom until a source of ingredient data exists.
    loader_source = inspect.getsource(loader_module)
    check("the loader filters kind = 'avoid_category' explicitly",
          "kind = 'avoid_category'" in loader_source)
    check("and has its own ingredient pass rather than letting them fall through",
          "kind = 'avoid_ingredient'" in loader_source)

    async with Session() as session:
        second_principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        second_member = (
            await session.execute(
                text("insert into member (principal_id, circle_id, nickname) "
                     "values (:p, :c, 'Amy') returning id"),
                {"p": second_principal, "c": circle},
            )
        ).scalar_one()
        # Two members avoiding the same ingredient, and one of them avoiding two — the same
        # per-(member, value) uniqueness the categories have, so a person may avoid 花生 and 甲殼類
        # both rather than exactly one of the eleven.
        for who, value in ((member, "花生"), (member, "甲殼類"), (second_member, "花生")):
            await session.execute(
                text("insert into preference (member_id, kind, value, stance, persist) "
                     "values (:m, 'avoid_ingredient', :v, 'avoid', false)"),
                {"m": who, "v": value},
            )
        await session.commit()
    check("two members may avoid the same ingredient and one member two of them", True)

    # The schema's three refusals, each its own transaction so a failure names which rule held.
    for label, sql in (
        ("a value outside the eleven is refused",
         "insert into preference (member_id, kind, value, stance, persist) "
         "values (:m, 'avoid_ingredient', '腰果', 'avoid', false)"),
        ("an ingredient without a stance is refused",
         "insert into preference (member_id, kind, value, persist) "
         "values (:m, 'avoid_ingredient', '蛋', false)"),
        ("an ingredient may not carry an expiry — it does not lapse, the screen asks again",
         "insert into preference (member_id, kind, value, stance, persist, expires_on) "
         "values (:m, 'avoid_ingredient', '蛋', 'avoid', false, current_date)"),
    ):
        async with Session() as session:
            try:
                await session.execute(text(sql), {"m": member})
                await session.commit()
            except Exception:
                await session.rollback()
                check(label, True)
            else:
                check(label, False, "the insert was accepted")

    # Reversible exactly as a category is: append `allow`, and it leaves the in-force set.
    async with Session() as session:
        await session.execute(
            text("insert into preference (member_id, kind, value, stance, persist, valid_from) "
                 "values (:m, 'avoid_ingredient', '甲殼類', 'allow', false, "
                 "now() + interval '1 second')"),
            {"m": member},
        )
        await session.commit()
    async with Session() as session:
        in_force = (
            await session.execute(
                text(preference_module.IN_FORCE_AVOID),
                {"member_id": member, "kind": "avoid_ingredient"},
            )
        ).all()
    check("an ingredient un-avoided by an `allow` leaves the in-force set",
          [row.value for row in in_force] == ["花生"], [row.value for row in in_force])

    # And the in-force query does not leak across kinds — the same query, the other kind, must not
    # return an ingredient. Both lists are closed and disjoint, so a wrong-kind value would reach a
    # screen before anything else noticed.
    async with Session() as session:
        categories_in_force = (
            await session.execute(
                text(preference_module.IN_FORCE_AVOID),
                {"member_id": member, "kind": "avoid_category"},
            )
        ).all()
    check("the category query returns no ingredient",
          all(row.value in preference_module.CATEGORIES for row in categories_in_force),
          [row.value for row in categories_in_force])

    # ---- A2's aged budget row (G9–G11): the expired state the product cannot reach ----------
    #
    # `expires_on` is computed from `now()` at write time (D25), so **no sequence of API calls can
    # produce an expired band** — the state A2's gate lines are about is unreachable through the
    # product. `upto.fixture` writes it, and this asserts it **through the endpoint**: what the
    # evaluator opens is the screen, and a fixture checked only by the query that wrote it proves
    # nothing about what the screen shows.
    from upto import fixture  # noqa: PLC0415

    amy_token = "t-" + pysecrets.token_urlsafe(24)
    async with Session() as session:
        await session.execute(
            text("insert into device_secret (principal_id, secret_sha256) values (:p, :h)"),
            {"p": second_principal, "h": sha256(amy_token.encode()).hexdigest()},
        )
        await session.commit()

    check("the fixture writes an aged band",
          await fixture.expired_budget(second_member, "tight", 1) == 0)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as amy:
        body = (
            await amy.get(path, headers={"Authorization": "Bearer {}".format(amy_token)})
        ).json()
    check("and the member's own screen reads it as in force",
          body.get("budget", {}).get("value") == "tight", body.get("budget"))
    check("flagged expired (D25's re-affirmation prompt has something to show)",
          body.get("budget", {}).get("expired") is True, body.get("budget"))
    # **`persist` is forced true and this is why.** `upto.privacy.erase` deletes every
    # `persist = false` row nightly, so a `false` fixture would be correct when written and gone by
    # morning — the gate state would erase itself with nothing to say it had.
    check("and persisted, so the nightly erasure does not take it away overnight",
          body.get("budget", {}).get("persist") is True, body.get("budget"))

    # Re-running is safe: `valid_from` is deterministic, so 0022's unique index refuses the second
    # write and the fixture reports the row already there rather than failing.
    check("a second run writes nothing and does not fail",
          await fixture.expired_budget(second_member, "tight", 1) == 0)
    # An older row would never be in force, so the fixture refuses instead of writing something
    # invisible — the absence is given a shape (D112) rather than reading as success.
    check("and an even older one is refused rather than written unseen",
          await fixture.expired_budget(second_member, "tight", 2) == 1)
    # Outside the retention window the erasure job would delete it, so the argument is refused
    # rather than the fixture being written with a deletion date.
    check("a row outside the retention window is refused",
          await fixture.expired_budget(second_member, "tight", 13) == 1)
    async with Session() as session:
        budget_rows = (
            await session.execute(
                text("select count(*) from preference where member_id = :m and kind = 'budget'"),
                {"m": second_member},
            )
        ).scalar()
    check("exactly one budget row exists after all four calls — every refusal rolled back",
          budget_rows == 1, budget_rows)

    await engine.dispose()

    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        raise SystemExit(1)
    print(
        "\nA1: a preference is written silently and appears on no stream, a change appends and the "
        "older row is untouched, an `allow` removes a category from what is in force without "
        "deleting anything, a member may avoid more than one, the value in force is resolved "
        "server-side with the month stated, a private reason can never be made public, and the "
        "erasure job erases what nobody agreed to keep while leaving what a round pinned"
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
        migrate = subprocess.run(
            ["alembic", "upgrade", "head"], cwd="/srv", env=environment, capture_output=True
        )
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2
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
