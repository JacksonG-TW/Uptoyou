"""D42 as amended 2026-08-28 — weather readings older than ninety days are deleted.

    docker compose exec api python -m upto.retention
    docker compose exec api python -m upto.retention --dry-run   # count only, delete nothing

**Why a window exists at all.** Seventeen days of weather was 90% of a 1,253 MB database. A18
stopped the observation table growing by 97.8% and a one-off delete reclaimed the backlog, but the
forecast table is Taipei data the product needs and it grows ~9.5 MB a day — 3.5 GB a year, on a
demo machine. Owner-ruled: **ninety days, both tables, unpinned rows only.**

**Ninety, and what it costs.** It keeps a quarter of history for any question about a past round and
for the cadence measurements M2 still reports as *insufficient history*. **A reading older than that
which nothing pinned cannot be recovered** — CWA publishes the current file, not an archive — so
this is genuinely irreversible for those rows. *Rejected:* 365 days (~4 GB of forecast, and nothing
was named that would read it); 30 days (it would already have deleted the window M2 is waiting on).

**What it may never delete: a reading a round pinned.** `weight_contribution` holds composite
foreign keys to both tables and `round_forecast_baseline` holds one more, all `ON DELETE RESTRICT`.
**The filter does the skipping, not the constraint** — a job that let the refusal raise would
abandon the rest of its batch on the first pinned row, which is the same reasoning D24 already
records for preferences. `TRUNCATE … CASCADE` is refused outright by revision 0020's triggers (H32)
and is not a route.

**Publication rows stay.** They are the ledger — M2 reads their `detected_at` and `ingest_run`, never
a reading — so both halves of that probe are untouched by this job. Nothing here writes
`rows_written`: this is not an ingest (H32).

**Batched, so the database stays serviceable.** Each batch is its own statement and its own commit;
the API reads `observation_reading` for the home screen's weather line while this runs.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import text

from upto.db import dispose_all, session_factory

#: Owner-ruled 2026-08-28. Named rather than inlined: a policy number in the middle of a statement
#: is a number nobody finds when the policy changes.
RETENTION_DAYS = 90

#: Rows per statement. Small enough that no single delete holds a lock long enough to be noticed,
#: large enough that three million rows do not need sixty thousand round trips.
BATCH = 50_000

# **`not exists` per table, spelled out rather than generated.** The two tables' composite keys have
# different shapes — the forecast's is five columns, the observation's four — and a helper that
# built these from a column list would be harder to check than the two statements it replaced.
OBSERVATION_UNPINNED = """
not exists (
  select 1 from weight_contribution wc
   where wc.observation_publication_id = r.publication_id
     and wc.observation_station_id = r.station_id
     and wc.observation_element = r.element
     and wc.observation_observed_at = r.observed_at)
"""

# The forecast has a second pin: `round_forecast_baseline` names the reading the round's pool was
# compared against (A12/D71, revision 0030). A reading pinned there and nowhere else is still a
# reading a round leans on, and `explain_round` reads it.
FORECAST_UNPINNED = """
not exists (
  select 1 from weight_contribution wc
   where wc.forecast_publication_id = r.publication_id
     and wc.forecast_township_code = r.township_code
     and wc.forecast_element = r.element
     and wc.forecast_measure = r.measure
     and wc.forecast_slot_start = r.slot_start)
and not exists (
  select 1 from round_forecast_baseline b
   where b.publication_id = r.publication_id
     and b.township_code = r.township_code
     and b.element = r.element
     and b.measure = r.measure
     and b.slot_start = r.slot_start)
"""

# **Age is the publication's `detected_at`, not the reading's own stamp, and the difference matters.**
# A forecast row's `slot_start` is in the *future* when it is published, and an observation's
# `observed_at` is the hour it describes. What "ninety days old" means here is *when we learned it*,
# which is the publication — the same instant M2 measures detection lag against.
TABLES = {
    "observation_reading": ("observation_publication", OBSERVATION_UNPINNED),
    "forecast_reading": ("forecast_publication", FORECAST_UNPINNED),
}

DELETE = """
with doomed as (
  select r.ctid from {table} r
    join {publication} p on p.id = r.publication_id
   where p.detected_at < now() - interval '{days} days'
     and {unpinned}
   limit {batch})
delete from {table} r using doomed d where r.ctid = d.ctid
"""

COUNT_DELETABLE = """
select count(*) from {table} r
  join {publication} p on p.id = r.publication_id
 where p.detected_at < now() - interval '{days} days'
   and {unpinned}
"""

# What had to be left behind, so the report is a true statement rather than a flattering one.
COUNT_PINNED = """
select count(*) from {table} r
  join {publication} p on p.id = r.publication_id
 where p.detected_at < now() - interval '{days} days'
   and not ({unpinned})
"""


def _sql(template: str, table: str, **extra) -> str:
    publication, unpinned = TABLES[table]
    return template.format(
        table=table, publication=publication, unpinned=unpinned.strip(),
        days=RETENTION_DAYS, **extra
    )


async def run(dry_run: bool = False) -> int:
    Session = session_factory()
    try:
        for table in TABLES:
            async with Session() as session:
                deletable = (
                    await session.execute(text(_sql(COUNT_DELETABLE, table)))
                ).scalar()
                pinned = (await session.execute(text(_sql(COUNT_PINNED, table)))).scalar()
            if dry_run:
                print(
                    "{}: {} rows older than {} days would be deleted, {} kept because a round "
                    "pinned them".format(table, deletable, RETENTION_DAYS, pinned)
                )
                continue
            deleted = 0
            while True:
                async with Session() as session:
                    result = await session.execute(text(_sql(DELETE, table, batch=BATCH)))
                    await session.commit()
                if not result.rowcount:
                    break
                deleted += result.rowcount
            # **Printed even when it is zero, because a silent pass is H34's shape.** "Nothing was
            # old enough tonight" and "the job did not run" must not read the same in a task log.
            print(
                "{}: {} rows deleted (older than {} days), {} left because a round pinned "
                "them".format(table, deleted, RETENTION_DAYS, pinned)
            )
    finally:
        await dispose_all()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="count what would go and delete nothing")
    arguments = parser.parse_args()
    return asyncio.run(run(dry_run=arguments.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
