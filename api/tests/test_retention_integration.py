"""D42's ninety-day window — what goes, what stays, and what a round's pin protects.

    docker compose run --rm tests python /srv/tests/test_retention_integration.py

Builds and drops its own database, so it never touches the stack's data.

**Three readings of the same age drive the whole thing**, because an assertion about a rule has to
be able to fail for the right reason: if one row survives and another does not, and both were 120
days old, the difference is the pin and cannot be anything else. A test that aged one row and kept
another young would pass under a job that simply deleted everything.

**The boundary row is the fourth.** 89 days is inside the window by one day, and it is the case a
comparison written `<=` instead of `<` — or a window computed in the wrong direction — gets wrong
while every other assertion here still passes.

**Age is the publication's `detected_at`, not the reading's own stamp**, and the fixture keeps those
deliberately far apart: the forecast rows describe an hour in 2026 whatever their publication's age.
A job that aged rows by `slot_start` would delete tomorrow's forecast and keep last winter's.
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto import retention  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))
TEST_DB = "upto_retention_check"
SLOT = datetime(2026, 8, 11, 19, 0, tzinfo=TAIPEI)

FAILURES = []


def check(name, condition, detail=""):
    print("{}   {}{}".format("ok  " if condition else "FAIL", name,
                             "" if condition else "  — {}".format(detail)))
    if not condition:
        FAILURES.append(name)


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def forecast_publication(session, sha: str, age_days: int) -> int:
    return (
        await session.execute(
            text("insert into forecast_publication "
                 "  (dataset_id, content_sha256, detected_at, payload_bytes) "
                 "values ('F-D0047-061', :sha, now() - make_interval(days => :d), 1024) "
                 "returning id"),
            {"sha": sha, "d": age_days},
        )
    ).scalar_one()


async def forecast_reading(session, publication_id: int, township: str) -> None:
    await session.execute(
        text("insert into forecast_reading "
             "  (publication_id, township_code, township, element, measure, slot_start, value) "
             "values (:p, :tc, '中山區', '3小時降雨機率', '3小時降雨機率', :s, '70')"),
        {"p": publication_id, "tc": township, "s": SLOT},
    )


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # Three publications of the same age, one young one. Same age is the point: the only
        # difference between the first two is the pin.
        pinned_pub = await forecast_publication(session, "a" * 64, 120)
        doomed_pub = await forecast_publication(session, "b" * 64, 120)
        # 89 days: inside the window by one day, and the case an off-by-one gets wrong.
        boundary_pub = await forecast_publication(session, "c" * 64, 89)
        await forecast_reading(session, pinned_pub, "63000040")
        await forecast_reading(session, doomed_pub, "63000040")
        await forecast_reading(session, boundary_pub, "63000040")

        # The pin: a round's baseline names one reading (A12/D71, revision 0030). A circle, a
        # round and the baseline row — the smallest chain that makes a reading undeletable.
        #
        # **The round is left `open`, deliberately.** A closed one needs `closed_at` and the rest of
        # `ck_round_closed_has_time`'s chain, and none of it is what this test is about: the FK from
        # `round_forecast_baseline` names a reading whatever the round's status is, so the pin — the
        # only thing under test — is identical either way. A fixture that satisfies constraints it
        # is not testing is a fixture nobody can read.
        circle = (
            await session.execute(
                text("insert into circle (name) values ('保留測試') returning id"))
        ).scalar_one()
        round_id = (
            await session.execute(
                # No seed at all: `ck_round_seed_pair_whole` says `outcome_seed` and
                # `seed_commit` are null together or present together (D108's commitment is a pair
                # or it is nothing), and this fixture needs neither.
                text("insert into round (circle_id, status, target_hour, target_hour_typed) "
                     "values (:c, 'open', :h, false) returning id"),
                {"c": circle, "h": SLOT},
            )
        ).scalar_one()
        await session.execute(
            text("insert into round_forecast_baseline "
                 "  (round_id, publication_id, township_code, element, measure, slot_start) "
                 "values (:r, :p, '63000040', '3小時降雨機率', '3小時降雨機率', :s)"),
            {"r": round_id, "p": pinned_pub, "s": SLOT},
        )
        await session.commit()

    os.environ["UPTO_DATABASE_URL"] = test_url
    await retention.run()

    async with Session() as session:
        surviving = set(
            row.publication_id
            for row in (
                await session.execute(text("select publication_id from forecast_reading"))
            ).all()
        )
        publications = (
            await session.execute(text("select count(*) from forecast_publication"))
        ).scalar()

    check("a reading a round pinned survives the window (D24, RESTRICT never raised)",
          pinned_pub in surviving, surviving)
    check("an unpinned reading of the SAME age is deleted — the pin is the only difference",
          doomed_pub not in surviving, surviving)
    check("a reading at 89 days stays — the boundary is inside the window",
          boundary_pub in surviving, surviving)
    check("every publication row stays — they are the ledger and M2 reads them",
          publications == 3, publications)

    await engine.dispose()

    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        raise SystemExit(1)
    print("\nD42's window: ninety days deletes what nothing pinned, keeps what a round leaned on, "
          "keeps the day before the boundary, and leaves every publication row standing")


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
                text('drop database if exists "{}" with (force)'.format(TEST_DB)))
        await admin.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
