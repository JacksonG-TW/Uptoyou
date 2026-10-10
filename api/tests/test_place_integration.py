#!/usr/bin/env python3
"""Ticket 11's `place` table, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_place_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

The inserts that must fail are the test: every CHECK in 0007 was ruled somewhere (D28's two
shapes, the 2026-08-13 partner exclusion, D39's all-or-nothing provenance), and a constraint
that cannot be shown rejecting a row is a comment, not a constraint. The one health-affirming
scenario — a circle-local place and a reference place inserted and read back — exists so the
rejections below cannot pass by the table being unusable.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
import _tempdb  # noqa: E402

TEST_DB = "upto_place_check"


async def must_reject(Session, why: str, sql: str, params: dict) -> None:
    try:
        async with Session() as session:
            await session.execute(text(sql), params)
            await session.commit()
    except (IntegrityError, DBAPIError):
        return
    raise AssertionError("accepted a row it must refuse: " + why)


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
        await session.commit()

    # The two legal shapes, in and read back.
    async with Session() as session:
        local_id = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '巷口麵店') returning id"
                ),
                {"c": circle_a},
            )
        ).scalar_one()
        ref_id = (
            await session.execute(
                text(
                    "insert into place (origin, registry_no) "
                    "values ('reference', 'A-196433950-00001-5') returning id"
                ),
            )
        ).scalar_one()
        await session.commit()

    async with Session() as session:
        row = (
            await session.execute(
                text("select origin, name, created_at from place where id = :id"),
                {"id": local_id},
            )
        ).one()
    assert row.origin == "circle-local" and row.name == "巷口麵店"
    assert row.created_at is not None and row.created_at.tzinfo is not None, "H17"

    # D28's scoping is per circle, so the same typed name in a second circle is a second row.
    async with Session() as session:
        await session.execute(
            text(
                "insert into place (origin, circle_id, name) "
                "values ('circle-local', :c, '巷口麵店')"
            ),
            {"c": circle_b},
        )
        await session.commit()

    # Ruled 2026-08-13: partner arrives with its own table, not before.
    await must_reject(
        Session,
        "origin 'partner' before the partner migration widens the CHECK",
        "insert into place (origin, registry_no) values ('partner', 'X-1')",
        {},
    )
    await must_reject(
        Session,
        "an unknown origin",
        "insert into place (origin, registry_no) values ('editorial', 'X-2')",
        {},
    )

    # D28's circle-local shape: a name, a circle, and nothing else.
    await must_reject(
        Session,
        "circle-local with no circle",
        "insert into place (origin, name) values ('circle-local', '無主麵店')",
        {},
    )
    await must_reject(
        Session,
        "circle-local carrying a registry_no",
        "insert into place (origin, circle_id, name, registry_no) "
        "values ('circle-local', :c, '假接源', 'A-000')",
        {"c": circle_a},
    )

    # D28's reference shape: the pin, and nothing a publication already answers for.
    await must_reject(
        Session,
        "reference with no registry_no",
        "insert into place (origin) values ('reference')",
        {},
    )
    await must_reject(
        Session,
        "reference carrying a name copy",
        "insert into place (origin, registry_no, name) values ('reference', 'A-001', '鼎泰豐')",
        {},
    )
    await must_reject(
        Session,
        "reference scoped to a circle",
        "insert into place (origin, registry_no, circle_id) values ('reference', 'A-002', :c)",
        {"c": circle_a},
    )

    # One row to accumulate against, both origins.
    await must_reject(
        Session,
        "the same registry_no entering twice",
        "insert into place (origin, registry_no) values ('reference', 'A-196433950-00001-5')",
        {},
    )
    await must_reject(
        Session,
        "the same typed name twice in one circle",
        "insert into place (origin, circle_id, name) values ('circle-local', :c, '巷口麵店')",
        {"c": circle_a},
    )

    # D39: the provenance travels with the value or the value does not exist.
    await must_reject(
        Session,
        "a category with no provenance",
        "update place set category = '拉麵' where id = :id",
        {"id": ref_id},
    )
    async with Session() as session:
        await session.execute(
            text(
                "update place set category = '拉麵', category_model = 'claude-sonnet-5', "
                "category_prompt_version = 'p1', category_generated_at = now(), "
                # 0015 widened DECIDED: the asked string is provenance too (D80), so the
                # complete-provenance example must carry it or it shows an outdated rule.
                "category_input = '拉麵店' where id = :id"
            ),
            {"id": ref_id},
        )
        await session.commit()

    # H19: nothing here may reference principal, checked in the catalogue rather than trusted.
    async with Session() as session:
        offenders = (
            await session.execute(
                text(
                    "select conrelid::regclass::text from pg_constraint "
                    "where contype = 'f' and confrelid = 'principal'::regclass "
                    "and conrelid::regclass::text not in ('member', 'device_secret')"
                )
            )
        ).scalars().all()
    assert offenders == [], f"tables referencing principal beside member: {offenders} (H19)"

    # No coordinate column exists on place (H23, D27) — asserted so a later convenience
    # column fails a test instead of slipping in as harmless.
    async with Session() as session:
        columns = (
            await session.execute(
                text(
                    "select column_name from information_schema.columns "
                    "where table_name = 'place'"
                )
            )
        ).scalars().all()
    for forbidden in ("lat", "lon", "latitude", "longitude", "geom"):
        assert forbidden not in columns, f"place carries a coordinate column {forbidden!r}"

    await engine.dispose()
    print(
        "ticket 11: both origins insert and read back, partner and every ruled-out shape are "
        "rejected, provenance is all-or-nothing, and H19 still holds"
    )


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""
    return await _tempdb.with_temporary_database(TEST_DB, lambda url, _environment: scenario(url))


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
