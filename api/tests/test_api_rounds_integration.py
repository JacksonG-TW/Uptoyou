#!/usr/bin/env python3
"""Ticket 19's three endpoints, driven over HTTP shapes against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_api_rounds_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

The requests go through the ASGI app itself — status codes, bodies and headers are the real
contract, not the router functions. Every ruled response shape is asserted: 401 for both
halves of a failed resolution (D67), 409 carrying the winner (D68), the quiet 200 (D70), the
cap's 409 (§3.0), the closed round's stored result (D69), and the roll chain landing whole
with D14's erasure observed after it.
"""

import asyncio
import json
import os
import secrets as pysecrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_api_rounds_check"
TAIPEI = timezone(timedelta(hours=8))


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def scenario(test_url: str) -> None:
    # The app reads UPTO_DATABASE_URL lazily per session, so pointing the environment at the
    # test database before the first request is what routes every endpoint call there.
    os.environ["UPTO_DATABASE_URL"] = test_url

    import httpx  # noqa: PLC0415

    from hashlib import sha256  # noqa: PLC0415

    from upto.main import app  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(TAIPEI)
    slot_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    token = "t-" + pysecrets.token_urlsafe(24)

    async with Session() as session:
        for code, name in (("63000010", "松山區"), ("63000020", "信義區")):
            await session.execute(
                text(
                    "insert into township_station "
                    "(township_code, township_name, station_id, station_name, resolution) "
                    "values (:c, :n, 'C0A980', '測試站', 'town_code')"
                ),
                {"c": code, "n": name},
            )
        circle = (
            await session.execute(
                text("insert into circle (name) values ('週三午餐') returning id")
            )
        ).scalar_one()
        other_circle = (
            await session.execute(
                text("insert into circle (name) values ('別人的圈子') returning id")
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
            # **An operator's device, because this test asserts the evidence table (D105).** After
            # 0025 the reveal payload's shape is chosen by the credential: a member sees what
            # happened, an operator also sees how the odds got there. Asserting `weights` from a
            # member token would be asserting a leak. A second, ordinary token below checks the
            # other half — that the member shape really withholds it.
            text("insert into device_secret (principal_id, secret_sha256, operator) "
                 "values (:p, :h, true)"),
            {"p": principal, "h": sha256(token.encode()).hexdigest()},
        )
        plain_token = "t-plain-" + sha256(token.encode()).hexdigest()[:16]
        await session.execute(
            text("insert into device_secret (principal_id, secret_sha256, operator) "
                 "values (:p, :h, false)"),
            {"p": principal, "h": sha256(plain_token.encode()).hexdigest()},
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
        rainy = (
            await session.execute(
                text(
                    "insert into place (origin, registry_no) "
                    "values ('reference', 'A-11111111-00001-1') returning id"
                )
            )
        ).scalar_one()
        # **A second reference place, in a drier township — required since A12.** D71 is relative
        # now: a pool whose reference places all sit in one township has nothing to compare, every
        # gap is 0, and no rain record exists at all. With only 雨中的店 this test went on passing
        # while testing none of the weather path.
        await session.execute(
            text(
                "insert into reference_place (publication_id, registry_no, origin, name, "
                "name_raw, address, address_raw, township_code, township_name) "
                "values (:pub, 'A-22222222-00001-1', 'reference', '晴天的店', '晴天的店', "
                "'x', 'x', '63000020', 'x')"
            ),
            {"pub": place_pub},
        )
        dry = (
            await session.execute(
                text(
                    "insert into place (origin, registry_no) "
                    "values ('reference', 'A-22222222-00001-1') returning id"
                )
            )
        ).scalar_one()
        # **A16: two sign-less sites of ONE company, so D92 derives a bracket.** Without a pair
        # here nothing in this file ever gains one, and the headline defect of 2026-08-28 — the
        # shortening handed a composed name whose trailing `）` no token can match — was invisible
        # to every assertion in the repository. Only one of the two needs a `place` row; the
        # sibling exists so `compose_names` sees the collision.
        for registry, addr in (("A-33333333-00001-1", "臺北市大安區和平東路2段86號"),
                               ("A-33333333-00002-1", "臺北市信義區松高路11號")):
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, origin, name, "
                    "name_raw, address, address_raw, township_code, township_name) "
                    "values (:pub, :r, 'reference', '一階堂拉麵餐飲有限公司', "
                    "'一階堂拉麵餐飲有限公司', :a, :a, '63000010', 'x')"
                ),
                {"pub": place_pub, "r": registry, "a": addr},
            )
        # **Both siblings get a `place` row, and that is what makes the assertion deterministic.**
        # §3.0 refuses a one-place round (「一輪至少要兩家店」), so the pool needs two — and if the
        # second were an ordinary local, the winner would be a dice draw and the bracketed case
        # would be exercised only half the time. Two sites of the same company means *whichever*
        # wins carries a bracket. A fixture that tests the case on some runs is H50 again.
        # **A19: the chain's company publishes materials, so the loader's brand path actually
        # runs.** Without these rows every round in this file has an empty `product_material` join
        # and the ingredient pass never builds a `BrandPin` — which is exactly how
        # `class BrandPin:` shipped without `@dataclass` and 500'd every roll whose pool held one of
        # the 4,509 places whose company publishes (H50: the fixture that never reaches the branch).
        brand_pub_for_chain = (
            await session.execute(
                text("insert into brand_publication "
                     "  (source, content_sha256, detected_at, payload_bytes, scope) "
                     "values ('taipei-foodtracer', repeat('d', 64), now(), 1024, 'x') "
                     "returning id")
            )
        ).scalar_one()
        for product, material in (("拉麵", "雞蛋"), ("拉麵", "麵粉"), ("叉燒", "豬肉")):
            await session.execute(
                text("insert into product_material (publication_id, company_name, brand_name, "
                     "  product_name, material_name, material_name_raw) "
                     "values (:pub, '一階堂拉麵餐飲有限公司', '一階堂', :p, :m, :m)"),
                {"pub": brand_pub_for_chain, "p": product, "m": material},
            )
        chain_ids = []
        for registry_no in ("A-33333333-00001-1", "A-33333333-00002-1"):
            chain_ids.append(
                (await session.execute(
                    text("insert into place (origin, registry_no) "
                         "values ('reference', :r) returning id"), {"r": registry_no})
                 ).scalar_one()
            )
        chain, chain_sibling = chain_ids
        locals_ = []
        for name in ("巷口麵店", "小林拉麵", "阿宗麵線"):
            locals_.append(
                (
                    await session.execute(
                        text(
                            "insert into place (origin, circle_id, name) "
                            "values ('circle-local', :c, :n) returning id"
                        ),
                        {"c": circle, "n": name},
                    )
                ).scalar_one()
            )
        foreign_place = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '外圈的店') returning id"
                ),
                {"c": other_circle},
            )
        ).scalar_one()
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
        await session.execute(
            text(
                "insert into forecast_reading (publication_id, township, township_code, "
                "element, slot_start, slot_end, measure, value) "
                "values (:pub, 'x', '63000020', '3小時降雨機率', :s, :e, "
                "'ProbabilityOfPrecipitation', '30')"
            ),
            {"pub": weather_pub, "s": slot_start, "e": slot_start + timedelta(hours=3)},
        )
        await session.commit()

    auth = {"Authorization": f"Bearer {token}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # D67: no token and a wrong token read the same 401.
        assert (await client.post(f"/circles/{circle}/rounds", json={})).status_code == 401
        assert (
            await client.post(
                f"/circles/{circle}/rounds",
                json={},
                headers={"Authorization": "Bearer wrong"},
            )
        ).status_code == 401

        # The open, defaulted: the hour is the hour the opener stands in (D73).
        opened = await client.post(f"/circles/{circle}/rounds", json={}, headers=auth)
        assert opened.status_code == 201, opened.text
        round_id = opened.json()["round_id"]
        assert opened.json()["target_hour_typed"] is False

        # D68: the losing open gets 409 carrying the winner.
        lost = await client.post(f"/circles/{circle}/rounds", json={}, headers=auth)
        assert lost.status_code == 409
        assert lost.json()["detail"]["open_round"]["round_id"] == round_id

        # Proposals: 201 new, 200 repeat (D70), 404 for a place this circle cannot see,
        # 409 for the fourth by one member (§3.0).
        for place in (rainy, dry, locals_[0]):
            created = await client.post(
                f"/rounds/{round_id}/proposals", json={"place_id": place}, headers=auth
            )
            assert created.status_code == 201, created.text
        repeat = await client.post(
            f"/rounds/{round_id}/proposals", json={"place_id": rainy}, headers=auth
        )
        assert repeat.status_code == 200 and repeat.json()["pooled"] is True
        unseen = await client.post(
            f"/rounds/{round_id}/proposals",
            json={"place_id": foreign_place},
            headers=auth,
        )
        assert unseen.status_code == 404
        capped = await client.post(
            f"/rounds/{round_id}/proposals", json={"place_id": locals_[2]}, headers=auth
        )
        assert capped.status_code == 409
        # **The sentence, not just the status — added 2026-08-19 after it was wrong for weeks.**
        # The front end renders this `detail` verbatim and keeps no copy of its own, so this string
        # IS the surface: nothing else states the rule to a person at the moment they meet it.
        # It read 「一輪最多提三家。」 — *per round* — while revision 0008's trigger caps **per member
        # per round**, so it told a five-member round it holds three places when it holds fifteen.
        # Nothing caught it because the test asserted only the 409, and a status code cannot be
        # wrong about a rule.
        assert capped.json()["detail"] == "一個人最多提三家。", capped.json()
        # And the half that keeps it honest rather than merely pinned: the sentence must name the
        # person, because the constraint it reports is per-person. A future rewording is free to
        # change every other word.
        assert "一個人" in capped.json()["detail"]

        # The roll: the whole chain in one transaction.
        rolled = await client.post(f"/rounds/{round_id}/roll", headers=auth)
        assert rolled.status_code == 200, rolled.text
        result = rolled.json()
        assert result["status"] == "closed"
        d1, d2 = result["dice"]
        assert 1 <= d1 <= 6 and 1 <= d2 <= 6 and result["sum"] == d1 + d2
        # 80% over 松山 against 30% over 信義: gap 50, `1 − 50/120 = 0.583` (A12/D71). 晴天的店 IS
        # the pool minimum, so it carries no record and stays at 1 — D43, not an oversight.
        assert result["weights"] == {
            str(rainy): "0.583",
            str(dry): "1",
            str(locals_[0]): "1",
        }, result["weights"]
        assert sum(result["allocation"].values()) == 36
        assert result["allocation"][str(result["winning_place_id"])] > 0
        # The panel's evidence rides in the result: the rainy place carries its factor in
        # D46's order, and the weather sentence stays behind ('none' visibility, D13).
        #
        # **Every contributor is present whether it fired or not since candidate 16** (甲's
        # operator picture, `spec-weights-picture-2026-09-11.md` §5). The drawing has one row per
        # contributor always, because «上次去過 showing nothing is information» — it says this
        # place was not last week's — and reading that from an *absence* is an inference the
        # payload can answer instead. `fired` is what separates a padded row from a real ×1, which
        # this very fixture can produce: the pool's driest township measures a gap of 0.
        rainy_panel = result["panel"][str(rainy)]
        assert rainy_panel["base"] == "1", rainy_panel
        assert rainy_panel["factors"] == [
            {"channel": "private", "contributor": "preference",
             "effect": "1", "reason": None, "fired": False},
            {"channel": "contextual", "contributor": "last_trip",
             "effect": "1", "reason": None, "fired": False},
            {"channel": "contextual", "contributor": "weather",
             "effect": "0.583", "reason": None, "fired": True},
        ], rainy_panel
        assert rainy_panel["clamps"] == []

        # **The pad completes the drawing and changes no arithmetic**, which is the assertion that
        # keeps it honest: a place with no stored contribution at all still weighs exactly 1, and
        # its three rows are all un-fired. The driest township carries no weather row — D43, not an
        # oversight — and the payload now says so in a field instead of by saying nothing.
        for empty in (locals_[0], dry):
            panel_rows = result["panel"][str(empty)]["factors"]
            assert [r["contributor"] for r in panel_rows] == [
                "preference", "last_trip", "weather"], panel_rows
            assert all(r["fired"] is False for r in panel_rows), panel_rows
            assert all(r["effect"] == "1" for r in panel_rows), panel_rows
            assert result["weights"][str(empty)] == "1", result["weights"]

        # **A12 / RR-8 through the real endpoint: the round stored the reading its factors were
        # measured against.** 晴天的店's township is the pool minimum and produces no contribution,
        # so this row is the only thing in the schema that can name the number every gap was taken
        # from. Asserted here rather than only in the loader's own test because the ruling was about
        # what a round *stores*, and the endpoint is what stores it.
        async with Session() as session:
            baseline = (
                await session.execute(
                    text("select township_code, publication_id, slot_start "
                         "from round_forecast_baseline where round_id = :r"),
                    {"r": round_id},
                )
            ).one_or_none()
        assert baseline is not None, "the roll stored no rain baseline"
        assert baseline.township_code == "63000020", baseline
        assert baseline.publication_id == weather_pub, baseline

        # D69: the retry gets the stored result, dice and all, in the same shape.
        again = await client.post(f"/rounds/{round_id}/roll", headers=auth)
        assert again.status_code == 200
        assert again.json()["dice"] == result["dice"]
        assert again.json()["winning_place_id"] == result["winning_place_id"]
        assert again.json()["weights"] == result["weights"]

        # **The other half of D105: the same round, the same member, an ordinary device.** The role
        # is on the secret, so one person holding two devices sees two shapes — which is the whole
        # argument for putting it there rather than on the principal.
        as_member = await client.post(
            "/rounds/{}/roll".format(round_id),
            headers={"Authorization": "Bearer " + plain_token},
        )
        assert as_member.status_code == 200, as_member.text
        member_body = as_member.json()
        for withheld in ("weights", "allocation", "panel"):
            assert withheld not in member_body, (withheld, sorted(member_body))
        for kept in ("round_id", "status", "dice", "sum", "winning_place_id", "places"):
            assert kept in member_body, (kept, sorted(member_body))
        assert member_body["winning_place_id"] == result["winning_place_id"]
        # **D55 as narrowed (owner: 「收窄」, `71ddbe5`).** This asserted `member_id` appeared nowhere
        # in the member payload — right while nothing in a round named a person, and wrong once D108
        # gave every member a named seat. What the narrowed rule protects is a *proposal's* author, so
        # the check is now on `places`, which is the member's view of the pool: a place may carry a
        # name and never a proposer.
        for place_id, place_name in member_body["places"].items():
            assert isinstance(place_name, str), (place_id, place_name)
        assert "proposer" not in json.dumps(member_body, ensure_ascii=False)
        assert "principal" not in json.dumps(member_body, ensure_ascii=False)
        # The seat list is now expected to name people — asserted positively so that D108's own
        # requirement is a test rather than an absence, and so that removing it fails here.
        assert member_body["rolls"], "D108: the member shape must carry the seat list"
        assert member_body["deciding_member"]["nickname"], "D91: the decider must be named"
        # **A16 / D92 as amended: the headline is on both wires, and it is a separate string.**
        # `MEMBER_KEYS` is a whitelist, so a field that exists on the operator body and is missing
        # here is the silent half of D105's shape — asserted on both rather than on either.
        assert "winner_headline" in result, sorted(result)
        assert "winner_headline" in member_body, sorted(member_body)
        # This round's places are circle-local — a member's own words, which A16 never edits. So the
        # headline must equal the composed name here, and a run where it did not would mean the rung
        # boundary had come off. The shortening's own arithmetic is pinned host-side in
        # `test_headline.py`; what this asserts is that the rung reaches the wire intact.
        assert member_body["winner_headline"] == member_body["places"][
            str(member_body["winning_place_id"])
        ], (member_body["winner_headline"], member_body["places"])
        print("  A16: the winner headline is on both wires and leaves a circle-local name alone")

        # **Candidate 17: the member gets the board, and nothing countable with it** (owner-ruled
        # 2026-09-11 — the picture, not the figure). The rule that this board IS the draw is pinned
        # host-side in `test_board.py`; what is asserted here is the half only a real wire can show:
        # that the field survives `MEMBER_KEYS`, and that `allocation` still does not.
        cells = member_body["board"]
        assert len(cells) == 6 and all(len(row) == 6 for row in cells), cells
        assert all(isinstance(cell, int) for row in cells for cell in row), cells
        die1, die2 = member_body["dice"]
        # **The orientation, checked against a fact the payload states separately.** Reading the
        # board the way the client will cannot catch a transpose; reading it against
        # `winning_place_id` can. On a double this is vacuous by construction — the transposed cell
        # is the same cell — so the vacuous case is named rather than passed over in silence.
        assert cells[die1 - 1][die2 - 1] == member_body["winning_place_id"], (die1, die2, cells)
        if die1 == die2:
            print("  BD-3b vacuous: the deciding pair was a double, so orientation was not tested")
        # The place ids on the board are the pool's, and every cell is a place the member can name
        # from `places` — a cell naming something absent from the legend would render as a blank.
        assert {cell for row in cells for cell in row} <= {int(p) for p in member_body["places"]}
        # D105 as amended: the figure stays on the operator's side of the wire.
        assert "allocation" not in member_body, sorted(member_body)
        assert "weights" not in member_body and "panel" not in member_body, sorted(member_body)
        print("  candidate 17: the member's 6×6 board carries the draw and no count")
        print("  D105: the member shape withholds the arithmetic and keeps the outcome")
        assert again.json()["allocation"] == result["allocation"]

        # Proposing into a closed round is a 409, not a quiet anything.
        late = await client.post(
            f"/rounds/{round_id}/proposals", json={"place_id": locals_[2]}, headers=auth
        )
        assert late.status_code == 409

        # **A16, the half a circle-local pool cannot reach.** A second round whose pool is exactly
        # the chain site, so the winner is not a draw: its composed name carries D92's bracket, and
        # the headline must be the shortened base ALONE with the bracket in its own field. This is
        # the case the 2026-08-28 gate found and no test here could have.
        chain_round = await client.post(f"/circles/{circle}/rounds", json={}, headers=auth)
        assert chain_round.status_code == 201, chain_round.text
        chain_round_id = chain_round.json()["round_id"]
        for place in (chain, chain_sibling):
            assert (await client.post(
                f"/rounds/{chain_round_id}/proposals", json={"place_id": place}, headers=auth
            )).status_code == 201
        chain_rolled = await client.post(f"/rounds/{chain_round_id}/roll", headers=auth)
        assert chain_rolled.status_code == 200, (chain_rolled.status_code, chain_rolled.text)
        chain_result = chain_rolled.json()
        winner = chain_result["winning_place_id"]
        assert winner in (chain, chain_sibling), chain_result
        composed = chain_result["places"][str(winner)]
        # The list keeps the whole composed name — A16 changes no list.
        assert composed.startswith("一階堂拉麵餐飲有限公司（"), composed
        assert composed.endswith("）"), composed
        # The headline is the shortened base and never carries a bracket.
        assert chain_result["winner_headline"] == "一階堂拉麵", chain_result["winner_headline"]
        assert "（" not in chain_result["winner_headline"]
        # The qualifier is the bracket's CONTENT, without its parentheses, and it is what the
        # composed name actually used — not a re-derivation.
        qualifier = chain_result["winner_qualifier"]
        assert qualifier and "（" not in qualifier and "）" not in qualifier, qualifier
        assert composed == f"一階堂拉麵餐飲有限公司（{qualifier}）", (composed, qualifier)
        # Both fields reach a member, or the whitelist has silently dropped one (D105).
        # The member's copy comes back through D69's retry, the same door the operator's did —
        # so this also proves the retry carries both new fields, not just the first response.
        chain_member = (await client.post(
            f"/rounds/{chain_round_id}/roll",
            headers={"Authorization": "Bearer " + plain_token},
        )).json()
        assert chain_member["winner_headline"] == "一階堂拉麵"
        assert chain_member["winner_qualifier"] == qualifier
        print("  A16: a bracketed chain shortens to its base and carries the bracket apart")

        # --- A19's surface was withdrawn on 2026-08-30; what survives is asserted here ------
        #
        # **This block used to prove the ingredient veto end to end and now proves it is gone.**
        # The owner withdrew the kind (「覆蓋率太小了，沒有意義」 — 12.4% of the city declares
        # anything). The ingest, `product_material`, the brand publication and the 81 stored rows
        # all stay; what left is the read, the wire and the POST. The assertions below are the
        # after-shape of exactly what the deleted ones checked, in the same order, so the diff is
        # readable as a withdrawal rather than as a test that quietly stopped existing.
        assert chain_rolled.status_code == 200, ("a pool holding a declared brand must still roll",
                                                 chain_rolled.text)
        assert "ingredient_data" not in chain_result, sorted(chain_result)
        assert "my_reasons" not in chain_result, sorted(chain_result)

        # **The POST refuses the kind, and 422 rather than 400 is the assertion.** A client cannot
        # tell "you sent nonsense" from "that feature is gone" if the two share a code.
        refused = await client.post(
            f"/circles/{circle}/preferences",
            json={"kind": "avoid_ingredient", "value": "蛋", "stance": "avoid"},
            headers={"Authorization": "Bearer " + plain_token},
        )
        assert refused.status_code == 422, (refused.status_code, refused.text[:160])
        assert "avoid_ingredient" in refused.text, refused.text[:160]

        # **And the two fields are off all THREE wires, not only the result body** — frontend
        # found that gap in the warning: `Round.tsx` drew the pool's marks from the snapshot and
        # from `pooled`, so removing it from the reveal alone would have left 這一餐 showing
        # 原料未公開 for ever.
        snapshot = (await client.get(f"/circles/{circle}/state", headers=auth)).json()
        for row in (snapshot.get("open_round") or {}).get("pool", []):
            assert "ingredient_data" not in row, row
        print("  A19 withdrawn: the roll is unaffected, the kind is refused 422, and neither "
              "field rides the result body, the snapshot or the pooled event")
    # D14, observed through the endpoint path: the close erased authorship, kept the pool.
    async with Session() as session:
        authored = (
            await session.execute(
                text(
                    "select count(*) from proposal "
                    "where round_id = :r and member_id is not null"
                ),
                {"r": round_id},
            )
        ).scalar_one()
        pool_size = (
            await session.execute(
                text("select count(*) from proposal where round_id = :r"), {"r": round_id}
            )
        ).scalar_one()
    assert authored == 0 and pool_size == 3

    from upto.db import dispose_all  # noqa: PLC0415

    await dispose_all()
    await engine.dispose()
    print(
        "ticket 19: both 401 halves read the same, the losing open carries the winner, the "
        "pool rules answer in status codes, and the roll chain lands whole with the erasure"
    )


async def with_temporary_database() -> int:
    admin_url, test_url = urls()
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

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
