"""A24 item 4 — the circle sweep: which circles it may take, that it takes them whole, and when it must not.

    docker compose run --rm tests python /srv/tests/test_circle_sweep_integration.py

Builds and drops its own database. Pins revision 0045 (`circle_sweep_candidates`, `sweep_circle`)
and `upto.sweep`, under the owner's three rulings of 2026-09-14 (decision-log rows «The sweep's
deletion right», «The sweep's mechanism re-ruled», «Which circles the sweep may touch»), D24's pins
as the cross-circle backstop, and H98.

**What is worth proving, in the order a mistake would cost most.**

1. **It never takes a circle it may not.** A circle an operator made, one with a signed trip, one
   touched inside thirty days — each refused by the function itself, called as the sweep's own role,
   and each write that counts as a touch moves the date on its own.
2. **It takes a circle whole, through D24's RESTRICT pin**, including the pinned preference, and a
   principal who sits in another circle keeps their seat and their device secret there.
3. **The order is written, not the triggers'** (H98): the same sweep succeeds after every foreign key
   in the schema is dropped and re-created in reverse order, which is what a `pg_dump` restore does
   to trigger names.
4. **A member acting while it runs is never swept with the circle** (the reviewer's pre-reads): an
   in-flight insert makes the sweep time out and refuse; an insert arriving after its locks waits.
5. **The skipped/failed split in `upto.sweep` reads the SQLSTATEs the function really raises.**

**Everything that matters is called as `upto_erasure`** (`set role`), because a definer function
called as the owner proves the body and not the grant.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import asyncpg  # noqa: E402

from upto import roles, sweep  # noqa: E402

TEST_DB = "upto_circle_sweep_test"
FAILURES = []
OLD = timedelta(days=40)  # asyncpg binds an interval from a timedelta, never a string


def check(name, condition, detail=""):
    print("{}   {}{}".format("ok  " if condition else "FAIL", name,
                             "" if condition else "  — {!r}".format(detail)))
    if not condition:
        FAILURES.append(name)


def urls():
    live = os.environ["UPTO_DATABASE_URL"].replace("+asyncpg", "")
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


async def make_circle(con, name, *, self_serve=True, round_=True, pin=True, trip=False,
                      principal=None):
    """A circle aged forty days in every column the candidate rule reads.

    With `round_` it has a closed round, a proposal, a roll and a contribution pinning a preference
    (D24's RESTRICT edge), which is the shape a used, never-signed circle has.
    """
    ids = {}
    ids["circle"] = await con.fetchval(
        "insert into circle (name, self_serve, created_at) values ($1, $2, now() - $3::interval) "
        "returning id", name, self_serve, OLD)
    ids["principal"] = principal or await con.fetchval(
        "insert into principal (created_at) values (now() - $1::interval) returning id", OLD)
    if principal is None:
        await con.execute(
            "insert into device_secret (principal_id, secret_sha256) values ($1, $2)",
            ids["principal"], "{:064d}".format(ids["principal"]))
    ids["member"] = await con.fetchval(
        "insert into member (circle_id, principal_id, nickname, joined_at) "
        "values ($1, $2, 'A', now() - $3::interval) returning id",
        ids["circle"], ids["principal"], OLD)
    ids["pref"] = await con.fetchval(
        "insert into preference (member_id, kind, value, stance, persist, valid_from, recorded_at) "
        "values ($1, 'avoid_category', '日式', 'avoid', true, now() - $2::interval, "
        "now() - $2::interval) returning id", ids["member"], OLD)
    await con.execute(
        "insert into join_ticket (circle_id, token_sha256, created_at) "
        "values ($1, $2, now() - $3::interval)", ids["circle"], "{:064d}".format(ids["circle"]), OLD)
    if round_:
        ids["place"] = await con.fetchval(
            "insert into place (origin, circle_id, name, created_at) "
            "values ('circle-local', $1, 'x', now() - $2::interval) returning id", ids["circle"], OLD)
        ids["round"] = await con.fetchval(
            "insert into round (circle_id, target_hour, target_hour_typed, status, opened_at, "
            "closed_at) values ($1, now() - $2::interval, false, 'closed', now() - $2::interval, "
            "now() - $2::interval) returning id", ids["circle"], OLD)
        await con.execute(
            "insert into proposal (round_id, place_id, member_id, proposed_at) "
            "values ($1, $2, $3, now() - $4::interval)",
            ids["round"], ids["place"], ids["member"], OLD)
        await con.execute(
            "insert into member_roll (round_id, circle_id, member_id, rolled_at) "
            "values ($1, $2, $3, now() - $4::interval)",
            ids["round"], ids["circle"], ids["member"], OLD)
        if pin:
            await con.execute(
                "insert into weight_contribution (round_id, place_id, channel, contributor, effect, "
                "reason, reason_visibility, member_id, preference_id, recorded_at) values "
                "($1, $2, 'private', 'preference', 0.5, 'x', 'represented_member_panel', $3, $4, "
                "now() - $5::interval)",
                ids["round"], ids["place"], ids["member"], ids["pref"], OLD)
        if trip:
            await con.execute(
                "insert into trip (round_id, circle_id, member_id, signed_at) "
                "values ($1, $2, $3, now() - $4::interval)",
                ids["round"], ids["circle"], ids["member"], OLD)
    return ids


async def candidates(con):
    return {row["circle_id"] for row in await con.fetch(
        "select circle_id from circle_sweep_candidates()")}


async def as_erasure(con, statement, *args):
    """Run one statement as the sweep's role, the way the DAG connects."""
    async with con.transaction():
        await con.execute('set local role "{}"'.format(roles.ERASURE))
        return await con.fetch(statement, *args)


async def sqlstate_of(coroutine):
    try:
        await coroutine
    except asyncpg.PostgresError as error:
        return error.sqlstate
    return None


async def rows_left(con, ids):
    """Every row that could still belong to the circle, by table."""
    c = ids["circle"]
    return {
        "circle": await con.fetchval("select count(*) from circle where id = $1", c),
        "member": await con.fetchval("select count(*) from member where circle_id = $1", c),
        "round": await con.fetchval("select count(*) from round where circle_id = $1", c),
        "proposal": await con.fetchval(
            "select count(*) from proposal where member_id = $1", ids["member"]),
        "member_roll": await con.fetchval("select count(*) from member_roll where circle_id = $1", c),
        "weight_contribution": await con.fetchval(
            "select count(*) from weight_contribution where member_id = $1", ids["member"]),
        "preference": await con.fetchval("select count(*) from preference where id = $1", ids["pref"]),
        "join_ticket": await con.fetchval("select count(*) from join_ticket where circle_id = $1", c),
        "place": await con.fetchval("select count(*) from place where circle_id = $1", c),
        "principal": await con.fetchval("select count(*) from principal where id = $1",
                                        ids["principal"]),
        "device_secret": await con.fetchval(
            "select count(*) from device_secret where principal_id = $1", ids["principal"]),
    }


async def scenario(url: str) -> None:
    con = await asyncpg.connect(url)

    # --- 1. which circles ------------------------------------------------------------------
    used = await make_circle(con, "used, never signed")
    cli = await make_circle(con, "made by an operator", self_serve=False)
    signed = await make_circle(con, "signed a trip", trip=True)
    bare = await make_circle(con, "never rolled", round_=False)
    young = await make_circle(con, "young")
    await con.execute("update circle set created_at = now() where id = $1", young["circle"])

    found = await as_erasure(con, "select circle_id from circle_sweep_candidates()")
    found = {row["circle_id"] for row in found}
    check("the sweep's role can list candidates without any grant on circle", bool(found), found)
    check("a used, never-signed self-serve circle is a candidate", used["circle"] in found)
    check("a self-serve circle that never rolled is a candidate", bare["circle"] in found)
    check("a circle an operator made is NEVER a candidate (self_serve = false)",
          cli["circle"] not in found)
    check("a circle with a signed trip is never a candidate", signed["circle"] not in found)
    check("a circle created today is not a candidate", young["circle"] not in found)

    # Each write that counts as a touch moves the date on its own: one fresh old circle per write.
    touches = {
        "a seat joined": "update member set joined_at = now() where id = $member",
        "a round opened": "update round set opened_at = now() where id = $round",
        "a round closed": "update round set closed_at = now() where id = $round",
        "a proposal": "update proposal set proposed_at = now() where member_id = $member",
        "a roll": "update member_roll set rolled_at = now() where member_id = $member",
        "a preference": "update preference set recorded_at = now() where id = $pref",
        "a place named": "update place set created_at = now() where circle_id = $circle",
        "a link minted": "update join_ticket set created_at = now() where circle_id = $circle",
        "a link replaced": "update join_ticket set revoked_at = now() where circle_id = $circle",
    }
    for label, statement in touches.items():
        ids = await make_circle(con, "touched: " + label)
        before = ids["circle"] in await candidates(con)
        for key in ("member", "round", "pref", "circle"):
            statement = statement.replace("$" + key, str(ids[key]))
        await con.execute(statement)
        check("{} moves «untouched» (candidate before, not after)".format(label),
              before and ids["circle"] not in await candidates(con))

    # --- grants, as the role ---------------------------------------------------------------
    check("upto_erasure cannot delete from circle directly — its reach is the function (42501)",
          await sqlstate_of(as_erasure(con, "delete from circle where id = $1", used["circle"]))
          == "42501")
    async with con.transaction():
        await con.execute('set local role "{}"'.format(roles.API))
        state = await sqlstate_of(con.fetch("select * from sweep_circle($1, true)", used["circle"]))
        check("upto_api cannot execute sweep_circle (EXECUTE revoked from PUBLIC)", state == "42501",
              state)

    # --- refusals, with the SQLSTATEs upto.sweep reads ---------------------------------------
    for label, ids in (("an operator's circle", cli), ("a signed circle", signed),
                       ("a young circle", young)):
        state = await sqlstate_of(as_erasure(con, "select * from sweep_circle($1)", ids["circle"]))
        check("{} is refused with 55000 and loses nothing".format(label),
              state == "55000" and all((await rows_left(con, ids)).values()), state)
    state = await sqlstate_of(as_erasure(con, "select * from sweep_circle($1)", 999999))
    check("a circle that does not exist is refused with P0002", state == "P0002", state)
    check("both refusals are «skipped» in upto.sweep, not failures",
          {"55000", "P0002", "55P03"} == set(sweep.SKIPPED_SQLSTATES), sweep.SKIPPED_SQLSTATES)

    # --- 2. whole, dry run first -----------------------------------------------------------
    dry = {row["step"]: row["rows_affected"] for row in
           await as_erasure(con, "select * from sweep_circle($1, true)", used["circle"])}
    left = await rows_left(con, used)
    check("a dry run deletes nothing", all(left.values()), left)
    check("and counts every step, including the pinned contribution and the principal",
          dry.get("weight_contribution") == 1 and dry.get("preference") == 1
          and dry.get("principal") == 1 and dry.get("device_secret") == 1 and dry.get("circle") == 1,
          dry)
    real = {row["step"]: row["rows_affected"] for row in
            await as_erasure(con, "select * from sweep_circle($1)", used["circle"])}
    left = await rows_left(con, used)
    check("the real run matches the dry run's counts", real == dry, (real, dry))
    check("and the circle is gone whole — through D24's RESTRICT pin, pinned preference included",
          not any(left.values()), left)

    # A principal who sits in another circle keeps that seat and their device secret.
    elsewhere = await make_circle(con, "the other circle")
    await con.execute("update circle set created_at = now() where id = $1", elsewhere["circle"])
    shared = await make_circle(con, "shares a principal", principal=elsewhere["principal"])
    await as_erasure(con, "select * from sweep_circle($1)", shared["circle"])
    check("a principal seated elsewhere is kept, with its device secret",
          await con.fetchval("select count(*) from principal where id = $1", elsewhere["principal"])
          == 1 and await con.fetchval(
              "select count(*) from device_secret where principal_id = $1", elsewhere["principal"])
          == 1)
    check("and its seat in the other circle is untouched",
          await con.fetchval("select count(*) from member where id = $1", elsewhere["member"]) == 1)
    check("while the swept circle's own seat is gone",
          await con.fetchval("select count(*) from member where id = $1", shared["member"]) == 0)

    # --- D24 as the cross-circle backstop -----------------------------------------------------
    victim = await make_circle(con, "pinned from outside")
    await con.execute(
        "insert into weight_contribution (round_id, place_id, channel, contributor, effect, reason, "
        "reason_visibility, member_id, preference_id) values ($1, $2, 'private', 'preference', 0.5, "
        "'x', 'represented_member_panel', $3, $4)",
        elsewhere["round"], elsewhere["place"], elsewhere["member"], victim["pref"])
    state = await sqlstate_of(as_erasure(con, "select * from sweep_circle($1)", victim["circle"]))
    check("a preference pinned by ANOTHER circle's round stops the sweep (23503) — D24's backstop",
          state == "23503", state)
    check("and the call deleted nothing at all", all((await rows_left(con, victim)).values()))

    # --- 5a. upto.sweep reads a real SQLSTATE: a circle touched after the listing is SKIPPED ----
    #
    # The listing is pointed at a circle the function will refuse (an operator's), which is exactly
    # what a friend joining between the listing and the call produces. The job must count it as
    # skipped and exit 0 — and it can only do that if it reads 55000 off the error, because a None
    # read would land in «failed» and exit 1 (the reviewer's note: the 23503 case below passes
    # either way, so it cannot prove the read).
    os.environ["UPTO_DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://")
    listing = sweep.CANDIDATES
    sweep.CANDIDATES = "select id as circle_id, created_at as last_touch from circle where id = {}".format(
        cli["circle"])
    try:
        code = await sweep.run()
    finally:
        sweep.CANDIDATES = listing
    check("upto.sweep counts a refused (touched) circle as skipped and exits 0 — the SQLSTATE is read",
          code == 0 and all((await rows_left(con, cli)).values()), code)

    # --- 5. upto.sweep over the lot: a failure exits 1 and the rest still go ------------------
    await con.execute("update circle set self_serve = false where id <> $1", victim["circle"])
    for_job = await make_circle(con, "for the job")
    os.environ["UPTO_DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://")
    # **A dry run counts; it cannot foresee a refusal.** The pin from outside only fires when the
    # preference is really deleted, so the dry run reports both circles as sweepable. Measured on
    # the first run of this test, where the expectation was «exit 1» and the instrument was wrong.
    code = await sweep.run(dry_run=True)
    check("upto.sweep --dry-run exits 0 and deletes nothing — a count, not a rehearsal of refusals",
          code == 0 and all((await rows_left(con, for_job)).values())
          and all((await rows_left(con, victim)).values()), code)
    code = await sweep.run()
    check("upto.sweep exits 1 for the pinned circle and still sweeps the other",
          code == 1 and not any((await rows_left(con, for_job)).values())
          and all((await rows_left(con, victim)).values()), code)
    await con.execute("delete from weight_contribution where preference_id = $1", victim["pref"])
    code = await sweep.run()
    check("with the outside pin gone the next night is clean (exit 0)",
          code == 0 and not any((await rows_left(con, victim)).values()), code)

    # --- 4. races --------------------------------------------------------------------------
    other = await asyncpg.connect(url)
    lock_config = await con.fetchval(
        "select array_to_string(proconfig, ';') from pg_proc where proname = 'sweep_circle'")
    lock_timeout = [c.split("=", 1)[1] for c in lock_config.split(";") if c.startswith("lock_timeout=")]
    below = await con.fetchval(
        "select $1::text::interval < current_setting('deadlock_timeout')::interval", lock_timeout[0])
    check("the function's lock_timeout is below the server's deadlock_timeout "
          "(the sweep must yield before a member's deadlock check)", below, (lock_config,))

    # (a) an insert in flight before the sweep: the sweep times out on the round lock and refuses.
    flight = await make_circle(con, "a member mid-proposal")
    place = await con.fetchval(
        "insert into place (origin, circle_id, name, created_at) "
        "values ('circle-local', $1, 'y', now() - $2::interval) returning id", flight["circle"], OLD)
    member_tx = other.transaction()
    await member_tx.start()
    await other.execute(
        "insert into proposal (round_id, place_id, member_id) values ($1, $2, $3)",
        flight["round"], place, flight["member"])
    state = await sqlstate_of(as_erasure(con, "select * from sweep_circle($1)", flight["circle"]))
    check("(a) a proposal in flight makes the sweep time out on its lock (55P03)", state == "55P03",
          state)
    await member_tx.commit()
    check("    and after the member commits, nothing of theirs was swept and the circle is touched",
          all((await rows_left(con, flight)).values())
          and flight["circle"] not in await candidates(con))

    # (b) an insert arriving after the sweep's locks waits for it, and is never swept with the circle.
    late = await make_circle(con, "a member arriving late")
    sweep_tx = con.transaction()
    await sweep_tx.start()
    await con.execute('set local role "{}"'.format(roles.ERASURE))
    await con.fetch("select * from sweep_circle($1, true)", late["circle"])  # takes and holds the locks
    await other.execute("set lock_timeout = '300ms'")
    state = await sqlstate_of(other.execute(
        "insert into preference (member_id, kind, value, stance, persist) "
        "values ($1, 'avoid_category', '火鍋', 'avoid', false)", late["member"]))
    check("(b) a write arriving after the sweep's locks waits on them (55P03 at its own timeout)",
          state == "55P03", state)
    await sweep_tx.rollback()
    await other.execute(
        "insert into preference (member_id, kind, value, stance, persist) "
        "values ($1, 'avoid_category', '火鍋', 'avoid', false)", late["member"])
    check("    and once the sweep lets go it lands, and the circle is touched",
          late["circle"] not in await candidates(con))
    await other.close()

    # --- 3. H98: the same sweep after every foreign key is re-created in reverse order ----------
    reordered = await make_circle(con, "after a restore")
    keys = await con.fetch(
        "select conrelid::regclass::text as tbl, conname, pg_get_constraintdef(oid) as def "
        "from pg_constraint where contype = 'f' and connamespace = 'public'::regnamespace "
        "order by oid desc")
    async with con.transaction():
        for key in keys:
            await con.execute('alter table {} drop constraint "{}"'.format(key["tbl"], key["conname"]))
        for key in keys:
            await con.execute('alter table {} add constraint "{}" {}'.format(
                key["tbl"], key["conname"], key["def"]))
    check("every foreign key was dropped and re-created in reverse order ({})".format(len(keys)),
          len(keys) > 20, len(keys))
    await as_erasure(con, "select * from sweep_circle($1)", reordered["circle"])
    check("H98: the sweep still takes the circle whole — the order is the function's, not the triggers'",
          not any((await rows_left(con, reordered)).values()))

    await con.close()


async def with_temporary_database() -> int:
    admin_url, test_url = urls()
    admin = await asyncpg.connect(admin_url)
    await admin.execute('drop database if exists "{}" with (force)'.format(TEST_DB))
    await admin.execute('create database "{}"'.format(TEST_DB))
    await admin.close()
    environment = dict(os.environ,
                       UPTO_DATABASE_URL=test_url.replace("postgresql://", "postgresql+asyncpg://"))
    try:
        migrate = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv", env=environment,
                                 capture_output=True, text=True)
        if migrate.returncode != 0:
            print(migrate.stderr, file=sys.stderr)
            return 2
        await scenario(test_url)

        # The downgrade removes both functions and the column, and the upgrade puts them back.
        down = subprocess.run(["alembic", "downgrade", "0044"], cwd="/srv", env=environment,
                              capture_output=True, text=True)
        con = await asyncpg.connect(test_url)
        functions = await con.fetchval(
            "select count(*) from pg_proc where proname in ('sweep_circle', 'circle_sweep_candidates')")
        column = await con.fetchval(
            "select count(*) from information_schema.columns "
            "where table_name = 'circle' and column_name = 'self_serve'")
        residual = await con.fetchval(
            "select count(*) from information_schema.role_table_grants where grantee = $1",
            roles.SWEEPER)
        residual_columns = await con.fetchval(
            "select count(*) from information_schema.role_column_grants where grantee = $1",
            roles.SWEEPER)
        await con.close()
        check("downgrade to 0044 drops both functions and self_serve",
              down.returncode == 0 and functions == 0 and column == 0,
              (down.returncode, functions, column, down.stderr[-300:]))
        # `roles.ensure()` creates the role and grants nothing, so a boot after this cannot bring
        # the grants back; what matters is that the downgrade itself left none (the reviewer's pin).
        check("and leaves upto_sweeper holding no table or column privilege in this database",
              residual == 0 and residual_columns == 0, (residual, residual_columns))
        up = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv", env=environment,
                            capture_output=True, text=True)
        check("and upgrade head applies again", up.returncode == 0, up.stderr[-300:])
    finally:
        admin = await asyncpg.connect(admin_url)
        await admin.execute('drop database if exists "{}" with (force)'.format(TEST_DB))
        await admin.close()

    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("\nA24 item 4: the sweep takes only abandoned self-serve circles, takes them whole through "
          "D24's pin, keeps a principal seated elsewhere, refuses from the database itself, never "
          "sweeps a member mid-write, and does not depend on trigger order (H98)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
