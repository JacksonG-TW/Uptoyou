#!/usr/bin/env python3
"""A1's owed half — the loader's preference pass in the **plural**, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_preference_load_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**Why this file exists at all, since `test_preference_integration` already passed.** That test
drove the whole surface and rolled twenty times, and it proved the pass works for *one* member
avoiding *one* category. The pass's actual claim is one record per **(member, place)** — five
people avoiding the same category produce five records on one place, each pinned to its own
member's own preference version — and nothing tested that. A pass that collapsed to one record
per place, or that leaked one member's `preference_id` onto another member's row, would have gone
green. D13's channel rule is *who may see the reason*, and one shared record cannot answer it, so
the plural case is the case the design is for.

**No weather anywhere in this scenario, on purpose.** There is no `forecast_publication` and no
reading, so the weather pass returns nothing and every record in the result came from the
preference pass. Mixing the two would have made a count assertion ambiguous about which pass was
short.

Four members, and each one is a different way the pass can be wrong:

- **Kevin** avoids 火鍋 — the ordinary case.
- **Amy** avoids 火鍋 *and* 麵食 — same category as Kevin (so one place must carry two records,
  with two `member_id`s and two `preference_id`s), plus a second category of her own (so a
  per-member set with more than one element is exercised, not just a set of size one).
- **Ben** has no preference row at all — produces nothing, which is D43's no-record-no-effect.
- **Dana** avoided 火鍋 and then appended `allow` — produces nothing. **This is the member a
  per-member bug hides behind:** the loader's `distinct on (member_id, value)` takes the latest
  row and only then filters `stance = 'avoid'`, so a query that filtered before deduplicating, or
  that deduplicated on `value` alone across members, would resurrect Dana's avoidance and hand it
  to somebody. `valid_from` is written explicitly rather than left to `now()`, because `now()` is
  transaction-scoped — two rows for one member and one value in a single transaction share an
  instant and collide on `uq_preference_category_version`, which is that index doing its job.

Four places, so the two guards inside `avoid_contribution` are both exercised: a categorised place
somebody avoids, a categorised place *nobody* avoids, and a place with no category at all.
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.engine.fold import fold  # noqa: E402
from upto.engine.load import load_contributions  # noqa: E402
from upto.engine.store import PreferencePin, write_roll  # noqa: E402

TEST_DB = "upto_preference_load_check"
TAIPEI = timezone(timedelta(hours=8))
MEAL = datetime(2026, 8, 19, 19, 0, tzinfo=TAIPEI)

# Explicit and ordered, so "the latest row wins" is a fact of the data rather than of the clock.
EARLIER = datetime(2026, 8, 1, 12, 0, tzinfo=TAIPEI)
LATER = datetime(2026, 8, 10, 12, 0, tzinfo=TAIPEI)

REGISTRY = {
    "hotpot": "A-11111111-00001-1",
    "noodle": "A-22222222-00001-1",
    "sushi": "A-33333333-00001-1",
}


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def seed(session):
    """The whole scenario; returns the ids the assertions need."""
    await session.execute(
        text(
            "insert into township_station "
            "(township_code, township_name, station_id, station_name, resolution) "
            "values ('63000010', '松山區', 'C0A980', '測試站', 'town_code')"
        )
    )
    circle = (
        await session.execute(text("insert into circle (name) values ('週三午餐') returning id"))
    ).scalar_one()

    members = {}
    for nickname in ("Kevin", "Amy", "Ben", "Dana"):
        principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        members[nickname] = (
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:p, :c, :n) returning id"
                ),
                {"p": principal, "c": circle, "n": nickname},
            )
        ).scalar_one()

    # The FDA side: one publication, three registered places, all in one township. The township
    # matters only to the weather pass, which produces nothing here — it is seeded so the places
    # are shaped like real ones rather than like the minimum this test needs.
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
    for key, name in (("hotpot", "麻辣鍋店"), ("noodle", "拉麵店"), ("sushi", "壽司店")):
        await session.execute(
            text(
                "insert into reference_place (publication_id, registry_no, origin, name, "
                "name_raw, address, address_raw, township_code, township_name) "
                "values (:pub, :no, 'reference', :n, :n, 'x', 'x', '63000010', '松山區')"
            ),
            {"pub": place_pub, "no": REGISTRY[key], "n": name},
        )

    # Our side. D39's provenance travels with the category or the category does not exist, so
    # every categorised row carries all five columns — the test cannot state a category the
    # product would refuse to store.
    places = {}
    for key, category in (("hotpot", "火鍋"), ("noodle", "麵食"), ("sushi", "日式")):
        places[key] = (
            await session.execute(
                text(
                    "insert into place (origin, registry_no, category, category_model, "
                    "category_prompt_version, category_generated_at, category_input) "
                    "values ('reference', :no, :cat, 'test-stub', 'v-test', now(), :inp) "
                    "returning id"
                ),
                {"no": REGISTRY[key], "cat": category, "inp": "測試"},
            )
        ).scalar_one()
    places["local"] = (
        await session.execute(
            text(
                "insert into place (origin, circle_id, name) "
                "values ('circle-local', :c, '巷口麵店') returning id"
            ),
            {"c": circle},
        )
    ).scalar_one()

    async def prefer(nickname, value, stance, valid_from):
        return (
            await session.execute(
                text(
                    "insert into preference (member_id, kind, value, stance, persist, valid_from) "
                    "values (:m, 'avoid_category', :v, :s, false, :t) returning id"
                ),
                {"m": members[nickname], "v": value, "s": stance, "t": valid_from},
            )
        ).scalar_one()

    preferences = {
        ("Kevin", "火鍋"): await prefer("Kevin", "火鍋", "avoid", EARLIER),
        ("Amy", "火鍋"): await prefer("Amy", "火鍋", "avoid", EARLIER),
        ("Amy", "麵食"): await prefer("Amy", "麵食", "avoid", LATER),
    }
    # Dana's round trip. Both rows are real history; only the later one is in force.
    await prefer("Dana", "火鍋", "avoid", EARLIER)
    await prefer("Dana", "火鍋", "allow", LATER)

    # `persist` is false on every row above, deliberately: D17 says such a row is used for the
    # round in force and erased afterwards, so the avoided-set query must not filter on it. If it
    # ever did, this whole test would return nothing and say so loudly.

    round_id = (
        await session.execute(
            text(
                "insert into round (circle_id, target_hour, target_hour_typed) "
                "values (:c, :h, true) returning id"
            ),
            {"c": circle, "h": MEAL},
        )
    ).scalar_one()
    # **One place each, because §3.0 caps a member at three proposals in a round** — four places
    # all proposed by one person is refused by the trigger, which is the cap doing its job. Who
    # proposed what is irrelevant to the preference pass (D70: the pool is what was proposed), so
    # the assignment is free — and it is spent deliberately: **Kevin proposes the very place his
    # own avoidance zeroes.** Proposing a place does not exempt it, and that is the reading of
    # D17 the product needs, because a person may put something forward for the group and still
    # not want it themselves.
    for nickname, key in (
        ("Kevin", "hotpot"), ("Amy", "noodle"), ("Ben", "sushi"), ("Dana", "local")
    ):
        await session.execute(
            text("insert into proposal (round_id, place_id, member_id) values (:r, :p, :m)"),
            {"r": round_id, "p": places[key], "m": members[nickname]},
        )
    await session.commit()
    return circle, members, places, preferences, round_id, place_pub


def the_plural_check_can_fail() -> None:
    """The two distinct-count assertions below, run against a collapsed pair (the check checks itself).

    Pure, so it runs before the database is built and a failure here is not a scenario failure.
    Without it the plural assertions could pass by never being reachable — the shape H34 keeps
    finding, where a gate that cannot fail reads exactly like a gate that passed.
    """
    collapsed = [(7, 7), (7, 7)]  # two records, one member, one version — the defect
    assert len({member for member, _ in collapsed}) != 2, "the member check cannot fail"
    assert len({version for _, version in collapsed}) != 2, "the version check cannot fail"


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    the_plural_check_can_fail()

    async with Session() as session:
        circle, members, places, preferences, round_id, place_pub = await seed(session)

    async with Session() as session:
        loaded = await load_contributions(session, round_id)
        pinned = loaded.contributions

    # Every record is a preference record: there is no weather in this database.
    assert all(p.contribution.channel == "private" for p in pinned), (
        "a non-private record appeared in a scenario with no forecast publication: "
        + repr([p.contribution.channel for p in pinned])
    )
    assert all(isinstance(p.pin, PreferencePin) for p in pinned)

    # The claim, as a set of triples: (place, member, preference version).
    got = {
        (p.contribution.place_id, p.member_id, p.pin.preference_id) for p in pinned
    }
    want = {
        (places["hotpot"], members["Kevin"], preferences[("Kevin", "火鍋")]),
        (places["hotpot"], members["Amy"], preferences[("Amy", "火鍋")]),
        (places["noodle"], members["Amy"], preferences[("Amy", "麵食")]),
    }
    assert got == want, "records\n  got  {}\n  want {}".format(sorted(got), sorted(want))
    assert len(pinned) == 3, f"expected exactly three records, got {len(pinned)}"

    # The plural case, stated as its own assertion so a failure names the actual defect rather
    # than only disagreeing about a set: one place, two records, two members, two versions.
    on_hotpot = [p for p in pinned if p.contribution.place_id == places["hotpot"]]
    assert len(on_hotpot) == 2, (
        "one place avoided by two members must carry two records, not "
        f"{len(on_hotpot)} — a per-place pass would collapse them into one"
    )
    assert len({p.member_id for p in on_hotpot}) == 2, "both records name the same member"
    assert len({p.pin.preference_id for p in on_hotpot}) == 2, (
        "both records pinned the same preference version — one member's row was handed to "
        "another member, which is the leak D13's channel rule exists to prevent"
    )

    # Nobody produced a record for the places their preferences said nothing about.
    assert not [p for p in pinned if p.contribution.place_id == places["sushi"]], (
        "壽司店 is categorised 日式 and nobody avoids it: a record here means the category "
        "guard compares the wrong thing"
    )
    assert not [p for p in pinned if p.contribution.place_id == places["local"]], (
        "the circle-local place has no category, and D28 rules that neutrality rather than a "
        "penalty"
    )
    assert members["Ben"] not in {p.member_id for p in pinned}, "Ben has no preference row"
    assert members["Dana"] not in {p.member_id for p in pinned}, (
        "Dana's latest row is `allow`, so she avoids nothing — the loader deduplicated or "
        "filtered in the wrong order"
    )

    # Every record is the absorbing zero, and the reason names the category for its owner alone.
    for p in pinned:
        assert p.contribution.effect == Decimal("0"), p.contribution
        assert p.reason_visibility == "represented_member", p.reason_visibility
    assert {p.contribution.reason for p in on_hotpot} == {"避開的類型：火鍋"}, (
        "two members avoiding one category read the same sentence, because the sentence is "
        "about the category and not about the member"
    )

    # Two zeros on one place is still zero — the fold is idempotent under an absorbing factor, so
    # the plural pass cannot make a place *more* avoided than one member already made it.
    weights = {
        place_id: fold(
            place_id, [p.contribution for p in pinned if p.contribution.place_id == place_id]
        ).weight
        for place_id in places.values()
    }
    assert weights == {
        places["hotpot"]: Decimal("0"),
        places["noodle"]: Decimal("0"),
        places["sushi"]: Decimal("1"),
        places["local"]: Decimal("1"),
    }, weights

    # And it lands: three private rows, each with its own member and its own pinned version.
    # The winner is 壽司店 because a zero-weight winner is refused by D45 — which is itself the
    # avoidance working, so the choice of winner here is not an accident of the fixture.
    async with Session() as session:
        await write_roll(
            session, round_id, pinned, weights, winning_place_id=places["sushi"], dice=(3, 4)
        )
        await session.commit()
    async with Session() as session:
        stored = (
            await session.execute(
                text(
                    "select place_id, member_id, preference_id, channel, reason_visibility, "
                    "forecast_publication_id, observation_publication_id "
                    "from weight_contribution where round_id = :r "
                    "order by place_id, member_id"
                ),
                {"r": round_id},
            )
        ).all()
    assert len(stored) == 3, f"expected three stored rows, got {len(stored)}"
    assert {(r.place_id, r.member_id, r.preference_id) for r in stored} == want
    for row in stored:
        assert row.channel == "private" and row.reason_visibility == "represented_member"
        # The pin went in the right column. This is the assertion that would have caught the bare
        # `else` in `write_roll` writing a preference id into `observation_publication_id`.
        assert row.forecast_publication_id is None, row
        assert row.observation_publication_id is None, row

    # The version a round used cannot be erased: the FK is ON DELETE RESTRICT, and this is the
    # plural case of it — two rows pinned from one place must both hold.
    async with Session() as session:
        for key, preference_id in preferences.items():
            try:
                await session.execute(
                    text("delete from preference where id = :i"), {"i": preference_id}
                )
                await session.commit()
            except Exception:
                await session.rollback()
            else:
                raise AssertionError(
                    f"{key}'s pinned preference version was deleted; the round's story is now "
                    "unreadable and fk_contribution_preference did not refuse"
                )

    await engine.dispose()
    print(
        "A1's loader pass: one place avoided by two members carries two records with two "
        "members and two pinned versions; a member with two avoidances produces one record "
        "each; no row, an `allow`, an unavoided category and no category all produce nothing; "
        "two zeros fold to zero; the three rows land in the private channel and their pinned "
        "versions refuse deletion"
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
