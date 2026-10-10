#!/usr/bin/env python3
"""Ticket 14's write half, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_engine_store_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

The happy path is one roll landing whole: contribution pinned to a real reading, weights on
the pool, round closed, authorship erased by 0008's trigger through this path too. The
failure paths are the point — a wrong weight, a zero-weight winner, a second roll — and each
must leave the database exactly as it found it, because D15's write is one transaction or none.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.engine.fold import Contribution  # noqa: E402
from upto.engine.store import (  # noqa: E402
    ForecastPin,
    PinnedContribution,
    ReconciliationError,
    write_roll,
)
import _tempdb  # noqa: E402

TEST_DB = "upto_engine_store_check"
TAIPEI = timezone(timedelta(hours=8))
SLOT = datetime(2026, 8, 13, 19, 0, tzinfo=TAIPEI)


async def open_round(Session, circle, places, member):
    async with Session() as session:
        round_id = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, now() + interval '2 hours', false) returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        for place in places:
            await session.execute(
                text(
                    "insert into proposal (round_id, place_id, member_id) "
                    "values (:r, :p, :m)"
                ),
                {"r": round_id, "p": place, "m": member},
            )
        await session.commit()
    return round_id


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

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
        p1, p2 = [
            (
                await session.execute(
                    text(
                        "insert into place (origin, circle_id, name) "
                        "values ('circle-local', :c, :n) returning id"
                    ),
                    {"c": circle, "n": name},
                )
            ).scalar_one()
            for name in ("小林拉麵", "阿宗麵線")
        ]
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

    pin = ForecastPin(
        publication_id=publication,
        township_code="63000010",
        element="降雨機率",
        measure="ProbabilityOfPrecipitation",
        slot_start=SLOT,
    )

    def rain_on(place_id):
        return PinnedContribution(
            contribution=Contribution(
                id=1,
                place_id=place_id,
                channel="contextual",
                contributor="weather",
                effect=Decimal("0.8"),
                reason="降雨機率80%，走路12分鐘",
            ),
            pin=pin,
            reason_visibility="none",
        )

    # The roll that lands whole.
    round_1 = await open_round(Session, circle, [p1, p2], member)
    async with Session() as session:
        await write_roll(
            session,
            round_1,
            [rain_on(p1)],
            {p1: Decimal("0.8"), p2: Decimal("1")},
            winning_place_id=p2,
            dice=(3, 4),
        )
        await session.commit()

    async with Session() as session:
        stored = (
            await session.execute(
                text(
                    "select channel, contributor, effect, reason_visibility, "
                    "forecast_publication_id from weight_contribution where round_id = :r"
                ),
                {"r": round_1},
            )
        ).all()
        weights = dict(
            (
                await session.execute(
                    text("select place_id, weight from proposal where round_id = :r"),
                    {"r": round_1},
                )
            ).all()
        )
        round_row = (
            await session.execute(
                text(
                    "select status, winning_place_id, closed_at, die1, die2 "
                    "from round where id = :r"
                ),
                {"r": round_1},
            )
        ).one()
        authored = (
            await session.execute(
                text(
                    "select count(*) from proposal "
                    "where round_id = :r and member_id is not null"
                ),
                {"r": round_1},
            )
        ).scalar_one()
    assert len(stored) == 1 and stored[0].forecast_publication_id == publication
    assert weights == {p1: Decimal("0.8"), p2: Decimal("1")}
    assert round_row.status == "closed" and round_row.winning_place_id == p2
    assert round_row.closed_at is not None
    assert (round_row.die1, round_row.die2) == (3, 4), "the dice are part of the result (0011)"
    assert authored == 0, "the close through write_roll did not fire the erasure (D14)"

    # A second roll on the closed round is refused.
    try:
        async with Session() as session:
            await write_roll(
                session, round_1, [], {p1: Decimal("1"), p2: Decimal("1")}, p1, dice=(1, 1)
            )
            await session.commit()
        raise AssertionError("a second roll on a closed round was accepted")
    except ReconciliationError:
        pass

    # The failure paths, each leaving no trace: wrong weight, zero-weight winner.
    round_2 = await open_round(Session, circle, [p1, p2], member)
    for why, weights_arg, winner in (
        ("a drawn weight the records do not fold to (D15)",
         {p1: Decimal("0.9"), p2: Decimal("1")}, p2),
        ("a zero-weight winner (D45)",
         {p1: Decimal("0.8"), p2: Decimal("1")}, p1),
    ):
        adjusted = dict(weights_arg)
        if winner == p1 and why.startswith("a zero-weight"):
            adjusted = {p1: Decimal("0"), p2: Decimal("1")}
        try:
            async with Session() as session:
                await write_roll(session, round_2, [rain_on(p1)], adjusted, winner, dice=(2, 6))
                await session.commit()
            raise AssertionError("accepted: " + why)
        except ReconciliationError:
            pass
    async with Session() as session:
        leftovers = (
            await session.execute(
                text("select count(*) from weight_contribution where round_id = :r"),
                {"r": round_2},
            )
        ).scalar_one()
        status = (
            await session.execute(
                text("select status from round where id = :r"), {"r": round_2}
            )
        ).scalar_one()
    assert leftovers == 0, "a refused roll left contribution rows behind"
    assert status == "open", "a refused roll closed the round"

    await engine.dispose()
    print(
        "ticket 14: one roll lands whole with the erasure fired; a wrong weight, a zero-weight "
        "winner and a second roll are each refused leaving no trace"
    )


async def with_temporary_database() -> int:
    async def served(test_url: str, environment: dict) -> None:
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, served)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
