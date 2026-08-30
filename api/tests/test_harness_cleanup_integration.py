"""The harness-circle cleanup deletes a whole circle and touches no real one.

    docker compose run --rm -v "$(pwd)/../tools:/srv/tools:ro" tests \
        python /srv/tests/test_harness_cleanup_integration.py

Pins `tools/drop_harness_circles.py`, which the evaluator's load ladder needs after a run (owner
routed 2026-08-30: the ladder created 42 circles and ~200 fabricated members, and those rows are
counted by D22's breadth denominator, by every `categorised` figure and by A22's nightly dump).

**What is actually worth proving, and it is not "the delete ran".** Two things:

1. **The order survives `RESTRICT`.** `weight_contribution.preference_id` is `ON DELETE RESTRICT`
   (D24: a round pins the preference version it used) and so is `trip_id` (D114). A cleanup that
   deletes `preference` before `weight_contribution` does not delete less — it raises, half way,
   and the rollback is the only thing standing between that and a partly-erased circle. So the
   fixture pins a preference with a real contribution row, which is the case that refuses.

2. **A circle whose name does not carry the prefix is untouched.** This is the assertion that makes
   the tool safe to hand to somebody: the failure nobody would notice in a dry run is the predicate
   being wider than the prefix.

**The tool is mounted, not imported from the image.** It is private tooling and stays out of every
image (D47), so this test skips — loudly, naming what was absent — when the mount is missing. A
test that silently passes without its subject is H34's shape.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_harness_cleanup_test"
TOOL_PATH = "/srv/tools/drop_harness_circles.py"


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


def load_tool():
    spec = importlib.util.spec_from_file_location("_drop_harness", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check(what: str, ok: bool, detail=None) -> None:
    print(("ok   " if ok else "FAIL ") + what + ("" if ok or detail is None else " " + repr(detail)))
    if not ok:
        raise SystemExit(1)


async def scenario(test_url: str) -> None:
    tool = load_tool()
    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # One harness circle, one real one. Same shape, different names — the prefix is the only
        # thing telling them apart, which is exactly the tool's own claim.
        ids = {}
        for key, name in (("harness", tool.HARNESS_PREFIX + "ladder LD-B"), ("real", "週五晚餐")):
            ids[key] = (await session.execute(
                text("insert into circle (name) values (:n) returning id"), {"n": name}
            )).scalar_one()

        for key in ("harness", "real"):
            principal = (await session.execute(
                text("insert into principal default values returning id"))).scalar_one()
            ids[key + "_member"] = (await session.execute(
                text("insert into member (circle_id, principal_id, nickname) "
                     "values (:c, :p, 'A') returning id"),
                {"c": ids[key], "p": principal},
            )).scalar_one()
            ids[key + "_round"] = (await session.execute(
                # **No `seat_ids`, and the CHECK is why.** `ck_round_seats_with_seed` refuses a
                # round that pins its seats without the seed pair (D108/D110), and an open round
                # has neither. The cleanup does not read either column, so the simplest legal
                # round is the right fixture.
                text("insert into round (circle_id, target_hour, target_hour_typed) "
                     "values (:c, now() + interval '2 hours', false) returning id"),
                {"c": ids[key]},
            )).scalar_one()
            ids[key + "_place"] = (await session.execute(
                text("insert into place (origin, circle_id, name) "
                     "values ('circle-local', :c, 'somewhere') returning id"),
                {"c": ids[key]},
            )).scalar_one()
            ids[key + "_pref"] = (await session.execute(
                text("insert into preference (member_id, kind, value, stance, persist) "
                     "values (:m, 'avoid_category', '日式', 'avoid', false) returning id"),
                {"m": ids[key + "_member"]},
            )).scalar_one()
            # **A contribution may only be about a POOLED place** — `fk_contribution_pooled_place`
            # points at `(round_id, place_id)` in `proposal`, which is D14's rule in the schema.
            # The fixture learned this from the constraint rather than from a comment.
            await session.execute(
                text("insert into proposal (round_id, place_id, member_id) "
                     "values (:r, :p, :m)"),
                {"r": ids[key + "_round"], "p": ids[key + "_place"],
                 "m": ids[key + "_member"]},
            )
            # **The RESTRICT edge, and the reason this fixture exists.** Delete `preference`
            # before this row and the database refuses.
            await session.execute(
                text("insert into weight_contribution (round_id, place_id, channel, contributor, "
                     "effect, reason, reason_visibility, member_id, preference_id) values "
                     "(:r, :p, 'private', 'preference', 0.5, 'x', 'represented_member_panel', "
                     ":m, :pref)"),
                {"r": ids[key + "_round"], "p": ids[key + "_place"],
                 "m": ids[key + "_member"], "pref": ids[key + "_pref"]},
            )
        await session.commit()

    # The tool reads its own environment variable, so point it at the temporary database.
    was = os.environ["UPTO_DATABASE_URL"]
    os.environ["UPTO_DATABASE_URL"] = test_url
    try:
        code = await tool.run(apply=False)
        check("a dry run exits 0", code == 0)
        async with Session() as session:
            still = (await session.execute(
                text("select count(*) from circle"))).scalar_one()
        check("and deletes nothing — both circles are still there", still == 2, still)

        code = await tool.run(apply=True)
        check("the apply run exits 0 — the RESTRICT edges did not refuse it", code == 0)
    finally:
        os.environ["UPTO_DATABASE_URL"] = was

    async with Session() as session:
        names = [row[0] for row in (await session.execute(
            text("select name from circle order by id"))).all()]
        check("the harness circle is gone", not any(
            n.startswith(tool.HARNESS_PREFIX) for n in names), names)
        check("and the real one is untouched — the predicate is the prefix and nothing wider",
              names == ["週五晚餐"], names)

        for table, column, kept in (
            ("weight_contribution", "member_id", ids["real_member"]),
            ("preference", "member_id", ids["real_member"]),
            ("member", "circle_id", ids["real"]),
            ("place", "circle_id", ids["real"]),
            ("round", "circle_id", ids["real"]),
        ):
            rows = (await session.execute(
                text("select count(*) from {}".format(table)))).scalar_one()
            check("{} holds only the real circle's row".format(table), rows == 1, (table, rows))
            survivor = (await session.execute(
                text("select count(*) from {} where {} = :v".format(table, column)),
                {"v": kept})).scalar_one()
            check("  and it is the right one", survivor == 1, (table, survivor))

    await engine.dispose()
    print("\nA22/ladder: the cleanup deletes a harness circle whole — through two RESTRICT edges "
          "and in one transaction — and a circle whose name lacks the prefix is untouched")


async def with_temporary_database() -> int:
    admin_url, test_url = urls()
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text("drop database if exists {}".format(TEST_DB)))
        await connection.execute(text("create database {}".format(TEST_DB)))
    await admin.dispose()
    environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
    subprocess.run(["alembic", "upgrade", "head"], cwd="/srv", env=environment, check=True)
    try:
        await scenario(test_url)
        return 0
    finally:
        # **Terminate before dropping, and this is not tidiness.** The first version dropped
        # straight away; when `scenario` raised, its engine's pool was still open and the drop
        # failed with `ObjectInUseError` — which then became the traceback, **hiding the real
        # failure completely**. A teardown that can fail is a teardown that can impersonate the
        # bug it was cleaning up after.
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text("select pg_terminate_backend(pid) from pg_stat_activity "
                     "where datname = :d and pid <> pg_backend_pid()"),
                {"d": TEST_DB},
            )
            await connection.execute(text("drop database if exists {}".format(TEST_DB)))
        await admin.dispose()


if __name__ == "__main__":
    if not os.path.exists(TOOL_PATH):
        print("{} is not mounted, so nothing was checked. This test needs the tool bind-mounted:\n"
              "  docker compose run --rm -v \"$(pwd)/../tools:/srv/tools:ro\" tests \\\n"
              "      python /srv/tests/test_harness_cleanup_integration.py".format(TOOL_PATH))
        raise SystemExit(0)
    raise SystemExit(asyncio.run(with_temporary_database()))
