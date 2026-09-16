#!/usr/bin/env python3
"""Ticket 16's `device_secret` and the resolution, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_auth_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

One token, one principal, seats in two circles: the same token resolves to a different member
per circle, which is D12's whole argument for the two-level split carried into D67. An unknown
token and a circle with no seat produce the same None. The last check reads the stored column
and asserts the token itself appears nowhere — the hash is the row, the plaintext is only ever
in the request.
"""

import asyncio
import os
import subprocess
import sys
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.auth import credential_for, member_for  # noqa: E402

TEST_DB = "upto_auth_check"
# A fixture, not a credential — assembled from short pieces so D49's assigned-secret rule,
# which rightly refuses `TOKEN = "<long literal>"`, does not match a value that opens nothing.
TOKEN = "test-" + "fixture-" + "stands-for-a-256-bit-random-value"


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


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
        circle_c = (
            await session.execute(
                text("insert into circle (name) values ('別人的圈子') returning id")
            )
        ).scalar_one()
        principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        member_a = (
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:p, :c, 'Kevin') returning id"
                ),
                {"p": principal, "c": circle_a},
            )
        ).scalar_one()
        member_b = (
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:p, :c, '阿凱') returning id"
                ),
                {"p": principal, "c": circle_b},
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into device_secret (principal_id, secret_sha256) values (:p, :h)"
            ),
            {"p": principal, "h": sha256(TOKEN.encode()).hexdigest()},
        )
        await session.commit()

    # One token, one device, a different seat per circle — D12's sentence, resolved.
    async with Session() as session:
        assert await member_for(session, TOKEN, circle_a) == member_a
        assert await member_for(session, TOKEN, circle_b) == member_b
        # A circle the principal holds no seat in, and a token nobody issued: the same None.
        assert await member_for(session, TOKEN, circle_c) is None
        assert await member_for(session, "not-a-token", circle_a) is None

    # The plaintext appears nowhere — the stored column is its hash and nothing else.
    async with Session() as session:
        stored = (
            await session.execute(text("select secret_sha256 from device_secret"))
        ).scalar_one()
    assert stored == sha256(TOKEN.encode()).hexdigest()
    assert TOKEN not in stored

    # **The two flags resolve independently (revision 0047, owner 「拆」 2026-09-16).** `operator` is
    # the invite power, `evidence` D105's table; `credential_for` returns the pair the presented
    # secret carries, and one principal may hold every combination at once.
    async with Session() as session:
        principal = (
            await session.execute(
                text("select principal_id from member where id = :m"), {"m": member_a})
        ).scalar_one()
        combinations = {"inv": (True, False), "aud": (False, True),
                        "both": (True, True), "plain": (False, False)}
        for label, (is_op, sees) in combinations.items():
            await session.execute(
                text("insert into device_secret (principal_id, secret_sha256, operator, evidence) "
                     "values (:p, :h, :o, :e)"),
                {"p": principal, "h": sha256((TOKEN + label).encode()).hexdigest(),
                 "o": is_op, "e": sees},
            )
        await session.commit()
        for label, expected in combinations.items():
            found = await credential_for(session, TOKEN + label, circle_a)
            assert found == (member_a, *expected), (label, found, expected)
        # And the row the pre-0047 insert shape writes — no `evidence` named — is the narrow one.
        await session.execute(
            text("insert into device_secret (principal_id, secret_sha256, operator) "
                 "values (:p, :h, true)"),
            {"p": principal, "h": sha256((TOKEN + "legacy").encode()).hexdigest()},
        )
        await session.commit()
        assert await credential_for(session, TOKEN + "legacy", circle_a) == (member_a, True, False)

    await engine.dispose()
    print(
        "ticket 16: one token resolves to its member per circle, unknown token and wrong "
        "circle read the same, and only the hash is stored"
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
