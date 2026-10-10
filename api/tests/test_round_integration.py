#!/usr/bin/env python3
"""Ticket 12's `round` and `proposal`, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_round_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**The close here is raw SQL on purpose — D14's own test shape.** A close through the API would
pass with the trigger absent, because the application would have been obeying the rule anyway.
The test acts as the writer who is not the application, which is H10's threat model and the
reason every rule in 0008 lives in the database.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
import _tempdb  # noqa: E402

TEST_DB = "upto_round_check"


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

    async with Session() as session:
        circle_a = (
            await session.execute(
                text("insert into circle (name) values ('週三午餐') returning id")
            )
        ).scalar_one()
        circle_b = (
            await session.execute(
                text("insert into circle (name) values ('宿舍') returning id")
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
                {"p": principal, "c": circle_a},
            )
        ).scalar_one()
        places = []
        for name in ("巷口麵店", "小林拉麵", "阿宗麵線", "鼎泰豐", "老王牛肉麵"):
            places.append(
                (
                    await session.execute(
                        text(
                            "insert into place (origin, circle_id, name) "
                            "values ('circle-local', :c, :n) returning id"
                        ),
                        {"c": circle_a, "n": name},
                    )
                ).scalar_one()
            )
        await session.commit()

    # A round opens with the meal's hour and how the hour was chosen (D16, D41).
    async with Session() as session:
        round_id = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, now() + interval '2 hours', false) returning id"
                ),
                {"c": circle_a},
            )
        ).scalar_one()
        await session.commit()

    # D52: a second open round in the same circle is a schema violation; another circle is not.
    await must_reject(
        Session,
        "a second open round in one circle (D52)",
        "insert into round (circle_id, target_hour, target_hour_typed) "
        "values (:c, now(), false)",
        {"c": circle_a},
    )
    async with Session() as session:
        other_round = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, now(), false) returning id"
                ),
                {"c": circle_b},
            )
        ).scalar_one()
        await session.commit()

    # An open round has no result and no close time; a close carries its time.
    await must_reject(
        Session,
        "an open round carrying a winner",
        "update round set winning_place_id = :p where id = :r",
        {"p": places[0], "r": round_id},
    )
    await must_reject(
        Session,
        "a close with no closed_at",
        "update round set status = 'closed' where id = :r",
        {"r": other_round},
    )

    # Proposals: authorship present while open, one entry per place (D70), three per member (§3.0).
    async with Session() as session:
        for place_id in places[:3]:
            await session.execute(
                text(
                    "insert into proposal (round_id, place_id, member_id) "
                    "values (:r, :p, :m)"
                ),
                {"r": round_id, "p": place_id, "m": member},
            )
        await session.commit()
    await must_reject(
        Session,
        "the same place proposed twice in one round (D70)",
        "insert into proposal (round_id, place_id, member_id) values (:r, :p, :m)",
        {"r": round_id, "p": places[0], "m": member},
    )
    await must_reject(
        Session,
        "a fourth proposal by one member in one round (§3.0)",
        "insert into proposal (round_id, place_id, member_id) values (:r, :p, :m)",
        {"r": round_id, "p": places[3], "m": member},
    )

    # D14: close over raw SQL — the writer who is not the application — and authorship is gone.
    async with Session() as session:
        await session.execute(
            text(
                "update round set status = 'closed', closed_at = now(), "
                "winning_place_id = :p where id = :r"
            ),
            {"p": places[1], "r": round_id},
        )
        await session.commit()
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
        pool = (
            await session.execute(
                text("select count(*) from proposal where round_id = :r"), {"r": round_id}
            )
        ).scalar_one()
    assert authored == 0, f"{authored} proposals kept their author after the close (D14)"
    assert pool == 3, "the erasure removed pool rows instead of authorship"

    # D52's other half: the circle can open its next round now that the last one is closed.
    async with Session() as session:
        await session.execute(
            text(
                "insert into round (circle_id, target_hour, target_hour_typed) "
                "values (:c, now() + interval '1 hour', true)"
            ),
            {"c": circle_a},
        )
        await session.commit()

    await engine.dispose()
    print(
        "ticket 12: one open round per circle, the cap and the pool rule hold, and a raw-SQL "
        "close erases authorship while keeping the pool"
    )


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""
    return await _tempdb.with_temporary_database(TEST_DB, lambda url, _environment: scenario(url))


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
