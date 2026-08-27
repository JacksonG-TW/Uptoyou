#!/usr/bin/env python3
"""Ticket 15's load half, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_engine_load_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

Three places, three fates: a reference place in a township at 80% is nudged and pinned to the
exact reading; a reference place in a township at 30% produces nothing (D71's threshold); a
circle-local place produces nothing (D28's neutrality). Then the loaded records run end to end
— fold, draw weights, write_roll — so the load half is shown feeding the write half rather
than only returning plausible objects.
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
from upto.engine.store import write_roll  # noqa: E402

TEST_DB = "upto_engine_load_check"
TAIPEI = timezone(timedelta(hours=8))
MEAL = datetime(2026, 8, 13, 19, 0, tzinfo=TAIPEI)
SLOT = datetime(2026, 8, 13, 18, 0, tzinfo=TAIPEI)  # the 3-hourly slot covering 19:00


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # Ticket 06's table is seeded by the api entrypoint, not by a migration, so the fresh
        # test database needs the two townships this scenario stands in.
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

        # The FDA side: one publication, two places, one township each.
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
        for no, name, code in (
            ("A-11111111-00001-1", "雨中的店", "63000010"),
            ("A-22222222-00001-1", "晴天的店", "63000020"),
        ):
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, origin, name, "
                    "name_raw, address, address_raw, township_code, township_name) "
                    "values (:pub, :no, 'reference', :n, :n, 'x', 'x', :c, 'x')"
                ),
                {"pub": place_pub, "no": no, "n": name, "c": code},
            )

        # Our side: two reference places pinned to those numbers, one circle-local place.
        rainy, sunny = [
            (
                await session.execute(
                    text(
                        "insert into place (origin, registry_no) "
                        "values ('reference', :no) returning id"
                    ),
                    {"no": no},
                )
            ).scalar_one()
            for no in ("A-11111111-00001-1", "A-22222222-00001-1")
        ]
        local = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '巷口麵店') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()

        # The weather side: 80% over 松山區, 30% over 信義區, in the slot covering the meal.
        weather_pub = (
            await session.execute(
                text(
                    "insert into forecast_publication "
                    "(dataset_id, content_sha256, detected_at, payload_bytes) "
                    "values ('F-D0047-061', repeat('a', 64), now(), 1000) returning id"
                )
            )
        ).scalar_one()
        for code, probability in (("63000010", "80"), ("63000020", "30")):
            await session.execute(
                text(
                    "insert into forecast_reading (publication_id, township, township_code, "
                    "element, slot_start, slot_end, measure, value) "
                    "values (:pub, 'x', :c, '3小時降雨機率', :s, :e, "
                    "'ProbabilityOfPrecipitation', :v)"
                ),
                {
                    "pub": weather_pub,
                    "c": code,
                    "s": SLOT,
                    "e": SLOT + timedelta(hours=3),
                    "v": probability,
                },
            )

        round_id = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, :h, true) returning id"
                ),
                {"c": circle, "h": MEAL},
            )
        ).scalar_one()
        for place in (rainy, sunny, local):
            await session.execute(
                text(
                    "insert into proposal (round_id, place_id, member_id) "
                    "values (:r, :p, :m)"
                ),
                {"r": round_id, "p": place, "m": member},
            )
        await session.commit()

    # The load: exactly one record, on the rainy place, pinned to the 80% reading.
    #
    # **A12 / D71 as reopened 2026-08-27 — the numbers here are relative now.** 80% over 松山 and
    # 30% over 信義: the pool's lowest is 30, so 松山's gap is 50 and its factor is
    # `1 − 50/120 = 0.583`. 信義 IS the minimum, so it gets **no record at all** (D43) — which is
    # why one record is still the right count, for a different reason than before. Under the
    # retired step (≥70 → ×0.8) the same fixture gave ×0.8 and the 30% place was below a
    # threshold; now it is the baseline the other place is measured against.
    async with Session() as session:
        loaded = await load_contributions(session, round_id)
        pinned = loaded.contributions
    assert len(pinned) == 1, f"expected one record, got {len(pinned)}"
    record = pinned[0]
    assert record.contribution.place_id == rainy
    assert record.contribution.effect == Decimal("0.583"), record.contribution.effect
    assert record.contribution.reason == "這區降雨機率較高（80%）", record.contribution.reason
    assert record.pin.township_code == "63000010" and record.pin.slot_start == SLOT
    # **Every pin comes from one publication, which a relative rule needs and an absolute one did
    # not.** A gap assembled from two publications is partly an artifact of when each was ingested.
    assert len({p.pin.publication_id for p in pinned}) == 1, "pins span publications"
    # **The reading the whole round was measured against — 信義's 30% — is named (RR-8, revision
    # 0030).** It has no contribution to hang from: the place standing on it produces no record
    # (D43) and a contribution carries exactly one source pin. Before the baseline table it survived
    # only transitively, because its publication cannot be deleted while 松山's row pins a reading
    # in it — real protection, and not an answer to *which reading was the baseline*.
    assert loaded.forecast_baseline is not None, "the pool minimum's reading is not named"
    assert loaded.forecast_baseline.township_code == "63000020", loaded.forecast_baseline
    assert loaded.forecast_baseline.slot_start == SLOT
    assert loaded.forecast_baseline.publication_id == record.pin.publication_id, \
        "the baseline and the contributions must come from one publication"

    # End to end: the loaded records feed the fold and the write half lands whole.
    weights = {
        place: fold(
            place, [p.contribution for p in pinned if p.contribution.place_id == place]
        ).weight
        for place in (rainy, sunny, local)
    }
    assert weights == {rainy: Decimal("0.583"), sunny: Decimal("1"), local: Decimal("1")}
    async with Session() as session:
        await write_roll(session, round_id, pinned, weights, winning_place_id=sunny, dice=(2, 5),
                         forecast_baseline=loaded.forecast_baseline)
        await session.commit()
    async with Session() as session:
        baseline_row = (
            await session.execute(
                text(
                    "select township_code, publication_id, slot_start "
                    "from round_forecast_baseline where round_id = :r"
                ),
                {"r": round_id},
            )
        ).one_or_none()
        assert baseline_row is not None, "the round stored no baseline"
        assert baseline_row.township_code == "63000020", baseline_row
        stored = (
            await session.execute(
                text(
                    "select place_id, forecast_publication_id from weight_contribution "
                    "where round_id = :r"
                ),
                {"r": round_id},
            )
        ).all()
        status = (
            await session.execute(
                text("select status from round where id = :r"), {"r": round_id}
            )
        ).scalar_one()
    assert [(row.place_id, row.forecast_publication_id) for row in stored] == [
        (rainy, weather_pub)
    ]
    assert status == "closed"

    # --- A14 / D114: the place the circle went to last time is ×0.5 in the next round ---------
    #
    # **The signature is what makes a trip, not the roll.** The round above closed on 晴天的店 and
    # produced no trip, so at this point D114 must contribute **nothing** — a rolled-but-unsigned
    # round is not evidence about where the circle has been. That absence is asserted first,
    # because it is the half a filter could quietly relax; the presence after signing is the easy
    # half.
    async with Session() as session:
        second = (
            await session.execute(
                text("insert into round (circle_id, target_hour, target_hour_typed) "
                     "values (:c, :h, true) returning id"),
                {"c": circle, "h": MEAL},
            )
        ).scalar_one()
        for place in (rainy, sunny, local):
            await session.execute(
                text("insert into proposal (round_id, place_id, member_id) "
                     "values (:r, :p, :m)"),
                {"r": second, "p": place, "m": member},
            )
        await session.commit()
    async with Session() as session:
        before_signing = await load_contributions(session, second)
    assert not [
        p for p in before_signing.contributions if p.contribution.contributor == "last_trip"
    ], "an unsigned previous winner produced a D114 record — only a signature makes a trip"

    async with Session() as session:
        trip_id = (
            await session.execute(
                text("insert into trip (round_id, circle_id, member_id) "
                     "values (:r, :c, :m) returning id"),
                {"r": round_id, "c": circle, "m": member},
            )
        ).scalar_one()
        await session.commit()
    async with Session() as session:
        after_signing = await load_contributions(session, second)
    trips = [p for p in after_signing.contributions if p.contribution.contributor == "last_trip"]
    assert len(trips) == 1, [p.contribution for p in trips]
    record = trips[0]
    # The trip's place is the **signed round's stored winner** (D106), which is 晴天的店 — never the
    # place the trip row points at, because it points at no place.
    assert record.contribution.place_id == sunny, record.contribution
    assert record.contribution.effect == Decimal("0.500"), record.contribution
    assert record.contribution.channel == "contextual"
    assert record.contribution.reason.startswith("上次去過（"), record.contribution.reason
    assert record.pin.trip_id == trip_id, record.pin
    assert record.reason_visibility == "none"
    # And the pin lands in its own column, which is what revision 0031 exists for.
    async with Session() as session:
        weights_2 = {
            place: fold(
                place,
                [p.contribution for p in after_signing.contributions
                 if p.contribution.place_id == place],
            ).weight
            for place in (rainy, sunny, local)
        }
        await write_roll(session, second, after_signing.contributions, weights_2,
                         winning_place_id=local, dice=(3, 3),
                         forecast_baseline=after_signing.forecast_baseline)
        await session.commit()
    async with Session() as session:
        pinned_trip = (
            await session.execute(
                text("select place_id, trip_id from weight_contribution "
                     "where round_id = :r and contributor = 'last_trip'"),
                {"r": second},
            )
        ).all()
    assert [(r.place_id, r.trip_id) for r in pinned_trip] == [(sunny, trip_id)], pinned_trip

    await engine.dispose()
    print(
        "ticket 15: the loader nudges the rainy township only, pins the exact reading, "
        "leaves the dry and the local place neutral, and its output rolls end to end; "
        "A14: an unsigned winner contributes nothing and a signed trip's place carries ×0.5 "
        "pinned to the trip row"
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
