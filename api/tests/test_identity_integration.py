#!/usr/bin/env python3
"""Ticket 01's identity tables, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_identity_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**Ticket 01 asks for "a test inserts one member, reads it back".** That is here and it is the
weakest thing in the file: it passes against a schema with no constraints at all, and it would
have passed against the two-table shape D12 does not describe. The four checks after it are the
ones that can fail, and each names the property it is standing in for:

- one principal, two circles — D12's load-bearing claim, the reason the second table exists
- one principal, same circle, twice — the returning user minted twice, which D12 calls the
  consequence easiest to get wrong precisely because **"nothing errors"**. After 0006 the
  database errors, and this is where that is asserted rather than assumed
- `principal` holds an id and a creation time and nothing else — read from the catalogue, so
  it fails the day a column carrying anything personal is added
- `member` is the only table with a foreign key to `principal` — **H19's mitigation, checked
  against `pg_constraint` rather than trusted.** This one is written to fail in the future: it
  is the test that catches a later migration pointing a domain table at `principal`, which is
  the leak H19 exists for and which is invisible inside a single circle.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import _tempdb  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_identity_check"

# Tables that are allowed to carry a foreign key to `principal` because they are
# authentication rather than product domain — D12 puts device secrets and account bindings
# there explicitly. It is a declaration rather than a list of exceptions: a domain table added
# here is H19 being stepped over, which is the whole thing the frozen set exists to make
# visible. `device_secret` is 0010, D67's table — the first name, added deliberately in the
# same commit that created it, which is exactly the act D12 designed this set to demand.
AUTHENTICATION_TABLES = frozenset({"device_secret"})


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        circles = {}
        for name in ("週三午餐", "宿舍"):
            result = await session.execute(
                text("insert into circle (name) values (:name) returning id"), {"name": name}
            )
            circles[name] = result.scalar_one()
        principal_id = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        await session.commit()

    # Ticket 01's own requirement: one member in, and read back.
    async with Session() as session:
        member_id = (
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:principal_id, :circle_id, :nickname) returning id"
                ),
                {"principal_id": principal_id, "circle_id": circles["週三午餐"], "nickname": "Kevin"},
            )
        ).scalar_one()
        await session.commit()

    async with Session() as session:
        row = (
            await session.execute(
                text(
                    "select m.nickname, m.principal_id, c.name as circle, m.joined_at "
                    "from member m join circle c on c.id = m.circle_id where m.id = :id"
                ),
                {"id": member_id},
            )
        ).one()
    assert row.nickname == "Kevin", row.nickname
    assert row.principal_id == principal_id
    assert row.circle == "週三午餐"
    # server_default now(): a row cannot exist without a stamp even inserted over raw SQL, which
    # is the insert above.
    assert row.joined_at is not None, "joined_at was not defaulted by the database"
    assert row.joined_at.tzinfo is not None, "joined_at came back without a zone (H17)"

    # D12's load-bearing claim: one principal, a seat in a second circle. If this fails, the
    # split between the two tables has bought nothing and the tables should be collapsed.
    async with Session() as session:
        await session.execute(
            text(
                "insert into member (principal_id, circle_id, nickname) "
                "values (:principal_id, :circle_id, :nickname)"
            ),
            {"principal_id": principal_id, "circle_id": circles["宿舍"], "nickname": "阿凱"},
        )
        await session.commit()

    async with Session() as session:
        seats = (
            await session.execute(
                text("select count(*) from member where principal_id = :id"), {"id": principal_id}
            )
        ).scalar_one()
    assert seats == 2, "one principal must hold a seat in each of two circles, found {}".format(seats)

    # And the nickname is per seat, so there is no global display name to correlate on.
    async with Session() as session:
        nicknames = set(
            (
                await session.execute(
                    text("select nickname from member where principal_id = :id"), {"id": principal_id}
                )
            )
            .scalars()
            .all()
        )
    assert nicknames == {"Kevin", "阿凱"}, nicknames

    # The returning user minted twice — D12 says nothing errors. Something errors now.
    async with Session() as session:
        try:
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:principal_id, :circle_id, :nickname)"
                ),
                {"principal_id": principal_id, "circle_id": circles["宿舍"], "nickname": "阿凱二號"},
            )
            await session.commit()
        except IntegrityError:
            pass
        else:
            raise AssertionError(
                "a second seat in the same circle was accepted — uq_member_one_seat_per_circle "
                "is not doing its work, and a returning user can silently become two principals"
            )

    # A blank nickname is a member with no name on screen, and the check constraint is what makes
    # that a database error rather than a rendering bug.
    async with Session() as session:
        try:
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:principal_id, :circle_id, '   ')"
                ),
                {"principal_id": principal_id, "circle_id": circles["宿舍"]},
            )
            await session.commit()
        except IntegrityError:
            pass
        else:
            raise AssertionError("a blank nickname was accepted")

    # `principal` holds no personal data at all (D12). Read from the catalogue so that adding a
    # column here fails a test rather than passing review.
    async with Session() as session:
        columns = set(
            (
                await session.execute(
                    text(
                        "select column_name from information_schema.columns "
                        "where table_schema = 'public' and table_name = 'principal'"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert columns == {"id", "created_at"}, (
        "principal must hold an id and a creation time and nothing else (D12); found {}".format(
            sorted(columns)
        )
    )

    # H19, checked rather than promised. The rule is narrower than "nothing references
    # principal", and the difference matters: H19 says no *domain* table may, while D12 says
    # "device secrets and account bindings hang off it" — authentication is the half that is
    # allowed to. So the check is an allowlist, empty today because neither table exists, and
    # adding a name to it is how a future migration declares "this is authentication, not
    # domain" — deliberately, in the same commit that would otherwise break this test.
    async with Session() as session:
        referencing = set(
            (
                await session.execute(
                    text(
                        "select conrelid::regclass::text from pg_constraint "
                        "where contype = 'f' and confrelid = 'principal'::regclass"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert "member" in referencing, "member must reference principal — it is the only link (D12)"
    unexpected = referencing - {"member"} - AUTHENTICATION_TABLES
    assert unexpected == set(), (
        "H19: the product domain must reach a person only through member. These tables carry a "
        "foreign key to principal and are not declared as authentication: {}".format(
            sorted(unexpected)
        )
    )

    await engine.dispose()
    print(
        "ticket 01: one principal holds a seat in two circles, a second seat in one circle is "
        "rejected, principal holds no personal data, and member is its only referent"
    )


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""

    async def run(test_url: str, environment: dict) -> None:
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, run)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
