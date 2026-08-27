"""A2 / G9–G11 — the aged budget row, so the expired state can be *seen* rather than described.

Run inside the stack (the database is not published to the host — A11 ①):

    docker compose exec api python -m upto.fixture expired-budget <member_id>
    docker compose exec api python -m upto.fixture expired-budget <member_id> --band easy --months 2

**Why a command and not a SQL snippet in a ticket.** `expires_on` is computed by the database at
write time from `now()` (`upto.preferences.INSERT`, D25), so **no sequence of API calls can produce
an expired band** — the state A2's gate lines G9–G11 are about is unreachable through the product.
The evaluator drives the live app and never runs git; handing them hand-typed SQL against the only
copy of the development database makes a typo the instrument. Rejected: a snippet in the ticket
(above), and a test-only helper (the state is needed on the *running* stack, in a browser, which is
where the gate is judged).

**It writes one ordinary row and nothing else.** No new table, no column, no schema change, no
product code touched — the aged row is exactly what a member who set a band last month and never
came back would have. The `expires_on` it stores is the API's own month-end formula applied to the
back-dated month, taken from that formula rather than restated, so the fixture cannot drift from
the product it is a fixture for.

**`persist` is `true` and there is no flag to change it.** `upto.privacy.erase` deletes every
`persist = false` row on a nightly DAG (05:00 Taipei), so a `false` fixture would be correct when
written and gone by morning — the evaluator would open the screen to a state that had silently
erased itself, which is worse than no fixture. Expiry is not deletion and that job does not touch
an expired row (its docstring says so), so a persisted aged band survives exactly as intended.

**It refuses rather than writing something that cannot be seen.** "In force" is the latest row per
kind, so a back-dated row is invisible if the member already holds a newer band. That case rolls
back and names the row that masks it — an absence with a shape (D112), never a silent success. It
verifies through `upto.preferences.IN_FORCE_BUDGET`, the query the screen itself reads, so "the
evaluator will see this" is checked rather than assumed.

**Re-running is safe.** `valid_from` is deterministic for a given `--months`, and revision 0022's
`uq_preference_budget_version` is unique on `(member_id, valid_from)` for a budget — so a second run
in the same month collides, reports the row already there, and writes nothing. Exit 0: the state
asked for is the state that exists.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from upto.db import dispose_all, session_factory
from upto.preferences import BUDGET_BANDS, IN_FORCE_BUDGET, TIMEZONE, month_end_of
from upto.privacy.erase import RETENTION

# The back-dated instant, as one expression the database evaluates once. The ninth day of the month
# rather than its first: a `date_trunc` on its own lands on midnight of day 1, and a row written at
# a month boundary is the one row a reader cannot tell from a boundary bug.
#
# **Taipei's month, then converted back to a timestamptz.** `now() at time zone 'Asia/Taipei'` is a
# naive local timestamp; the trailing `at time zone` turns the result back into a real instant, so
# `valid_from` stays an honest timestamptz rather than a Taipei wall-clock time stored as if it were
# UTC — an eight-hour lie in a column the retention window reads.
AGED_INSTANT = (
    "((date_trunc('month', now() at time zone '{tz}')"
    " - make_interval(months => cast(:months as integer))"
    " + interval '9 days') at time zone '{tz}')"
).format(tz=TIMEZONE)

# `expires_on` is D25's month end, taken from `upto.preferences.month_end_of` with the back-dated
# instant in place of `now()` — the product's own expression, imported rather than copied, so the
# fixture cannot drift from the boundary it is a fixture for. It followed the boundary from UTC to
# Taipei on 2026-08-27 without being edited, which is what the shared expression buys.
INSERT_AGED = """
insert into preference (member_id, kind, value, stance, persist, valid_from, recorded_at,
                        expires_on)
select :member_id, 'budget', :value, null, true, aged.vf, aged.vf,
       {month_end}
  from (select {instant} as vf) aged
returning id, valid_from, expires_on
""".format(instant=AGED_INSTANT, month_end=month_end_of("aged.vf"))

# Asked before anything is written. A row older than the retention window is erased by
# `upto.privacy.erase` on the same nightly DAG that would spare it if it were newer, so this refuses
# the argument instead of writing a fixture with a deletion date. The window is imported, never
# retyped — the policy number lives in one file.
TOO_OLD = "select {instant} < now() - interval '{window}'".format(
    instant=AGED_INSTANT, window=RETENTION
)

WHO = """
select m.nickname, m.circle_id, c.name as circle_name
  from member m join circle c on c.id = m.circle_id
 where m.id = :member_id
"""

EXISTING_AT = """
select id, value, persist, valid_from, expires_on
  from preference
 where member_id = :member_id and kind = 'budget' and valid_from = {instant}
""".format(instant=AGED_INSTANT)


async def expired_budget(member_id: int, band: str, months: int) -> int:
    Session = session_factory()
    try:
        async with Session() as session:
            who = (
                await session.execute(text(WHO), {"member_id": member_id})
            ).one_or_none()
            if who is None:
                print(
                    f"no member with id {member_id} — nothing was written. "
                    "`python -m upto.issue` prints a member id when it seats someone.",
                    file=sys.stderr,
                )
                return 1

            too_old = (
                await session.execute(text(TOO_OLD), {"months": months})
            ).scalar_one()
            if too_old:
                print(
                    f"--months {months} lands outside the {RETENTION} retention window, so "
                    "`upto.privacy.erase` would delete this row on its next nightly run — "
                    "nothing was written. A band expires at its own month end; it does not need "
                    "to be old to be expired.",
                    file=sys.stderr,
                )
                return 1

            try:
                written = (
                    await session.execute(
                        text(INSERT_AGED),
                        {"member_id": member_id, "value": band, "months": months},
                    )
                ).one()
            except IntegrityError:
                await session.rollback()
                already = (
                    await session.execute(text(EXISTING_AT), {"member_id": member_id,
                                                              "months": months})
                ).one_or_none()
                if already is None:  # pragma: no cover — some other constraint, not ours
                    raise
                print(f"already there — preference {already.id}, {already.value}, "
                      f"expires_on {already.expires_on}; nothing was written")
                return 0

            # **Checked through the screen's own query before committing.** A row that exists and
            # is not the one in force is a fixture that reads as done and shows nothing.
            in_force = (
                await session.execute(text(IN_FORCE_BUDGET), {"member_id": member_id})
            ).one_or_none()
            if in_force is None or in_force.valid_from != written.valid_from:
                await session.rollback()
                masking = (
                    "" if in_force is None else
                    " — preference version of {} ({}) is newer and is what the screen would "
                    "show".format(in_force.valid_from.date(), in_force.value)
                )
                print(
                    f"member {member_id} already holds a newer budget row, so a back-dated one "
                    f"would never be in force{masking}. Rolled back, nothing was written. "
                    "Use a member with no budget set, or a larger --months than the newest row.",
                    file=sys.stderr,
                )
                return 1
            if not in_force.expired:
                await session.rollback()
                print(
                    f"the row would be in force but reads as NOT expired "
                    f"(expires_on {written.expires_on}) — rolled back rather than left as a "
                    "fixture that does not hold the state it is for.",
                    file=sys.stderr,
                )
                return 1

            await session.commit()
    finally:
        await dispose_all()

    print(f"preference: {written.id}")
    print(f"member: {member_id} ({who.nickname}) in circle {who.circle_id} ({who.circle_name})")
    print(f"band: {band}, persist: true")
    print(f"valid_from: {written.valid_from}")
    print(f"expires_on: {written.expires_on} — in the past, so the read flags it `expired`")
    print("GET /circles/{}/preferences on this member's device now returns the band filled in "
          "and flagged expired (D25).".format(who.circle_id))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m upto.fixture",
        description="Evaluator fixtures — states the product cannot reach through its own API.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    aged = sub.add_parser(
        "expired-budget",
        help="write a back-dated, persisted budget band so the screen shows D25's expired state",
    )
    aged.add_argument("member_id", type=int, help="the member whose screen should show it")
    aged.add_argument(
        "--band", choices=list(BUDGET_BANDS), default="tight",
        help="which band expired (default: tight)",
    )
    aged.add_argument(
        "--months", type=int, default=1,
        help="how many months back to date it (default: 1 — last month, expired since its end)",
    )
    args = parser.parse_args()
    if args.months < 1:
        print("--months must be at least 1; a band in the current month is not expired",
              file=sys.stderr)
        return 1
    return asyncio.run(expired_budget(args.member_id, args.band, args.months))


if __name__ == "__main__":
    sys.exit(main())
