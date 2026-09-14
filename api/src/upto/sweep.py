"""A24 item 4 — sweep the self-serve circles nobody has touched for thirty days.

Run inside the stack, as the erasure role (the DAG supplies its URL):

    python -m upto.sweep            # do it
    python -m upto.sweep --dry-run  # count what would go, delete nothing

**The rules are not in this file, and that is the design.** Which circles may go and in what order
their rows are deleted live in two database functions, `circle_sweep_candidates()` and
`sweep_circle(id, dry_run)` (revision 0045), because the role this job connects as holds EXECUTE on
those two and no table grant at all (owner, 2026-09-14). This module lists, calls, and reports.

**One circle, one transaction, and a failure does not stop the night.** `privacy.erase`'s argument,
applied here: a job that stopped at the first circle it could not delete would delete nothing after
it. So each circle is its own call, rolled back on its own if it does not complete, and the rest
proceed. **Two outcomes, and they are not the same.** A circle somebody touched while the job ran,
or whose rows a member's write held past the function's lock timeout, is *skipped* — it is not
idle, or it will be tried again tomorrow. Anything else — a pin reaching in from another circle, a
grant gone missing — is a *failure*, and **the exit code is 1 when anything failed**, so the DAG
goes red and the alert fires: a sweep that quietly skipped the same broken circle every night would
be a sweep nobody knows is broken.

**The report prints every step's count, including the zeros**, so «deleted 1 circle» always says
what left with it (D112).

**`--dry-run` counts and cannot rehearse a refusal.** A foreign key reaching in from another circle
(D24's pin as the backstop) fires only when the row is really deleted, so a dry run can list a
circle the real run then fails on. The real run says so by id and exits 1.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timezone

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from upto.db import dispose_all, session_factory

CANDIDATES = "select circle_id, last_touch from circle_sweep_candidates()"

#: **Skipped, not failed** — the function refused because the circle was touched since the listing
#: (55000), a member's write held a lock past the function's `lock_timeout` (55P03), or the circle
#: is already gone (P0002). Each means «try again tomorrow» and none means the job is broken, so
#: they are counted and printed and do not turn the DAG red. Revision 0045 raises them.
SKIPPED_SQLSTATES = ("55000", "55P03", "P0002")
SWEEP = "select step, rows_affected from sweep_circle(:c, :dry)"


async def run(dry_run: bool = False) -> int:
    Session = session_factory()
    swept, skipped, failed, totals = [], [], [], {}
    try:
        async with Session() as session:
            candidates = (await session.execute(text(CANDIDATES))).all()

        for circle_id, last_touch in candidates:
            try:
                async with Session() as session:
                    steps = (await session.execute(
                        text(SWEEP), {"c": circle_id, "dry": dry_run})).all()
                    if dry_run:
                        await session.rollback()
                    else:
                        await session.commit()
            except DBAPIError as error:
                orig = getattr(error, "orig", error)
                sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
                reason = str(orig).strip().splitlines()[0]
                if sqlstate in SKIPPED_SQLSTATES:
                    skipped.append(circle_id)
                    print("circle {}: skipped tonight ({}) — {}".format(
                        circle_id, sqlstate, reason), flush=True)
                else:
                    failed.append((circle_id, reason))
                    print("circle {}: NOT swept ({}) — {}".format(
                        circle_id, sqlstate, reason), flush=True)
                continue
            swept.append(circle_id)
            for step, count in steps:
                totals[step] = totals.get(step, 0) + count
            print("circle {} (last touched {:%Y-%m-%d %H:%M} UTC): {}".format(
                circle_id, last_touch.astimezone(timezone.utc),
                " · ".join("{} {}".format(step, count) for step, count in steps)), flush=True)

        verb = "would sweep" if dry_run else "swept"
        print("{} {} of {} candidate circle(s){}; {} skipped, {} failed".format(
            verb, len(swept), len(candidates),
            " — " + " · ".join("{} {}".format(s, n) for s, n in totals.items()) if totals else "",
            len(skipped), len(failed)), flush=True)
        return 1 if failed else 0
    finally:
        await dispose_all()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="count what would go and delete nothing")
    arguments = parser.parse_args()
    return asyncio.run(run(dry_run=arguments.dry_run))


if __name__ == "__main__":
    sys.exit(main())
