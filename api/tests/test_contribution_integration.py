#!/usr/bin/env python3
"""Ticket 13's `weight_contribution`, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_contribution_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

D13's rejection tests are re-enacted here against the real table: every CHECK the entry wrote
is shown refusing a row, and the one accepted row pins a real forecast reading through the
composite foreign key — then proves the pin is real by watching a deletion refuse.
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_contribution_check"

FORECAST_PIN = (
    "forecast_publication_id, forecast_township_code, forecast_element, "
    "forecast_measure, forecast_slot_start"
)

TAIPEI = timezone(timedelta(hours=8))
SLOT = datetime(2026, 8, 13, 19, 0, tzinfo=TAIPEI)


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def must_reject(Session, why: str, sql: str, params: dict) -> None:
    try:
        async with Session() as session:
            await session.execute(text(sql), params)
            await session.commit()
    except (IntegrityError, DBAPIError):
        return
    raise AssertionError("accepted a write it must refuse: " + why)


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # The scaffolding: a pooled place in an open round, and one real forecast reading.
    async with Session() as session:
        circle = (
            await session.execute(
                text("insert into circle (name) values ('週三午餐') returning id")
            )
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
        place = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '小林拉麵') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        unpooled_place = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '沒人提的店') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        round_id = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, now() + interval '2 hours', false) returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into proposal (round_id, place_id, member_id) values (:r, :p, :m)"
            ),
            {"r": round_id, "p": place, "m": member},
        )
        publication = (
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
                "insert into forecast_reading "
                "(publication_id, township, township_code, element, slot_start, measure, value) "
                "values (:pub, '松山區', '63000010', '降雨機率', :slot, "
                " 'ProbabilityOfPrecipitation', '80')"
            ),
            {"pub": publication, "slot": SLOT},
        )
        await session.commit()

    pin = {
        "pub": publication,
        "town": "63000010",
        "el": "降雨機率",
        "me": "ProbabilityOfPrecipitation",
        "slot": SLOT,
    }
    base = {"r": round_id, "p": place, **pin}

    # The one accepted shape: a contextual factor pinned to the reading it actually read.
    async with Session() as session:
        contribution_id = (
            await session.execute(
                text(
                    "insert into weight_contribution "
                    "(round_id, place_id, channel, contributor, effect, reason, "
                    f" reason_visibility, {FORECAST_PIN}) "
                    "values (:r, :p, 'contextual', 'weather', 0.8, "
                    " '降雨機率80%，走路12分鐘', 'none', :pub, :town, :el, :me, :slot) "
                    "returning id"
                ),
                base,
            )
        ).scalar_one()
        await session.commit()
    assert contribution_id is not None

    # D24's point, demonstrated rather than asserted: the pinned reading cannot be deleted.
    await must_reject(
        Session,
        "deleting a reading a contribution pins (D24)",
        "delete from forecast_reading where publication_id = :pub",
        {"pub": publication},
    )

    # D70/D15: a contribution for a place nobody proposed has nothing to land on.
    await must_reject(
        Session,
        "a contribution for an unpooled place",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        f"reason, reason_visibility, {FORECAST_PIN}) "
        "values (:r, :p, 'contextual', 'weather', 0.8, 'x', 'none', "
        " :pub, :town, :el, :me, :slot)",
        {**base, "p": unpooled_place},
    )

    # D45's ranges, one refusal per channel.
    for channel, effect, visibility, why in (
        ("private", "1.2", "none", "private may not lift (D45)"),
        ("contextual", "0.4", "none", "contextual may not reach zero (D45)"),
        ("commercial", "0.9", "table", "commercial may not suppress (D45)"),
    ):
        await must_reject(
            Session,
            why,
            "insert into weight_contribution (round_id, place_id, channel, contributor, "
            f"effect, reason, reason_visibility, member_id, {FORECAST_PIN}) "
            f"values (:r, :p, '{channel}', 'x', {effect}, 'x', '{visibility}', "
            f"{':m' if channel == 'private' else 'null'}, :pub, :town, :el, :me, :slot)",
            {**base, "m": member},
        )

    # D13's four CHECKs.
    await must_reject(
        Session,
        "a commercial reason hidden from the table (D13)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        f"reason, reason_visibility, {FORECAST_PIN}) "
        "values (:r, :p, 'commercial', 'coupon', 1.5, 'x', 'none', "
        " :pub, :town, :el, :me, :slot)",
        base,
    )
    await must_reject(
        Session,
        "a private reason shown to the table (D13)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        f"reason, reason_visibility, member_id, {FORECAST_PIN}) "
        "values (:r, :p, 'private', 'preference', 0.5, 'x', 'table', :m, "
        " :pub, :town, :el, :me, :slot)",
        {**base, "m": member},
    )
    await must_reject(
        Session,
        "a contextual factor tied to a member (D13)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        f"reason, reason_visibility, member_id, {FORECAST_PIN}) "
        "values (:r, :p, 'contextual', 'weather', 0.8, 'x', 'none', :m, "
        " :pub, :town, :el, :me, :slot)",
        {**base, "m": member},
    )

    # H8: no sentence, no effect — reason is NOT NULL, not merely conventional.
    await must_reject(
        Session,
        "a factor with no reason (H8)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        f"reason, reason_visibility, {FORECAST_PIN}) "
        "values (:r, :p, 'contextual', 'weather', 0.8, null, 'none', "
        " :pub, :town, :el, :me, :slot)",
        base,
    )

    # D24: a partial pin and a pinless row are both refused; private has no source table yet.
    await must_reject(
        Session,
        "a partial forecast pin (D24: all-or-nothing)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        "reason, reason_visibility, forecast_publication_id) "
        "values (:r, :p, 'contextual', 'weather', 0.8, 'x', 'none', :pub)",
        base,
    )
    await must_reject(
        Session,
        "a contribution with no source at all (D24)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        "reason, reason_visibility) values (:r, :p, 'contextual', 'weather', 0.8, 'x', 'none')",
        base,
    )
    # **A real brand publication, so the two-source refusal below is refused by the CHECK and not
    # by the foreign key.** A fixture that used a made-up id would pass while the CHECK was broken —
    # the constraint under test has to be the one that fires (H50).
    async with Session() as session:
        brand_pub = (
            await session.execute(
                text("insert into brand_publication "
                     "  (source, content_sha256, detected_at, payload_bytes, scope) "
                     "values ('taipei-foodtracer', repeat('e', 64), now(), 1024, 'x') "
                     "returning id")
            )
        ).scalar_one()
        await session.commit()

    # **A19's fifth source (revision 0036), and the count is what is being tested.** The rule has
    # not changed since three sources — `num_nonnulls(...) = 1` — but its arity has, twice, and each
    # widening is a chance for the CHECK to be recreated with a column left out. Two refusals pin
    # both directions: a row naming the new source AND an old one, and a row naming none.
    await must_reject(
        Session,
        "a contribution naming two sources, one of them the new brand pin (D24)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        "reason, reason_visibility, member_id, brand_publication_id, forecast_publication_id) "
        "values (:r, :p, 'private', 'ingredient', 0, 'x', 'represented_member', :m, :bp, :pub)",
        {**base, "m": member, "bp": brand_pub},
    )
    await must_reject(
        Session,
        "a brand pin that names no publication that exists (RESTRICT's other half)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        "reason, reason_visibility, member_id, brand_publication_id) "
        "values (:r, :p, 'private', 'ingredient', 0, 'x', 'represented_member', :m, 999999)",
        {**base, "m": member},
    )

    await must_reject(
        Session,
        "a private contribution before the preference table exists (ruled with 0009)",
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
        "reason, reason_visibility, member_id) "
        "values (:r, :p, 'private', 'preference', 0.5, 'x', 'represented_member', :m)",
        {**base, "m": member},
    )

    await engine.dispose()
    print(
        "ticket 13: one real contribution pins a real reading, the pinned reading refuses "
        "deletion, and every CHECK from D13, D24 and D45 rejects its row"
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
