#!/usr/bin/env python3
"""M4 — **backfill and replay**, measured rather than assumed.

Run inside the stack, without rebuilding anything, by bind-mounting this directory into a
one-off container:

    cd app && docker compose run --rm -T \\
        -v "$PWD/api/tests:/srv/tests_m4:z" --entrypoint python \\
        api /srv/tests_m4/test_ingest_replay.py

It builds its own database (`upto_m4_replay`) and drops it, so it never touches the stack's data.

**The claim under measurement.** A table dropped or truncated can be rebuilt from what the
pipeline already holds, the rebuild agrees with the original — same row count, same
order-independent content hash — and the `ingest_run` ledger explains the rebuild.

Two shapes, and they are not equally clean:

*Shape A — rows only.* `TRUNCATE <source>_row`, keep the publication, re-run the source against
the same file with `--force-parse`. The publication id is still there to write against, so the
rebuilt rows are comparable **column for column, publication id included**. This is the shape a
real backfill wants, and it is the one that works.

*Shape B — publication and rows.* Remove the publication too and re-run with no flags, so the
runner re-claims it. The content hash comes back identical because it is a hash of the file; the
**id does not**, because it is a sequence, and `detected_at` does not, because it is a clock
reading taken by the run. So the rows can only be compared with `publication_id` set aside — and
every foreign key in the database that pinned the *old* id is now pointing at nothing or at a
different fact. That is the finding this test exists to state precisely, not to smooth over, so
it enumerates the referencing keys from the catalog and measures what each one actually does.

*The cross-source order.* D85's tax ingest keeps only rows joinable to the latest place
publication, and reads that set from the database at run time. So place must be rebuilt before
tax, and the test measures what happens when it is not, rather than asserting it must not be.

**Nothing here is fixed.** Where a replay is refused or a cascade takes more than it was asked
for, the measurement is recorded and reported. `app/api/src` is not this test's to change.

**Fixtures, not downloads.** The five file-based sources run through their real `python -m …`
entry point in a subprocess against M1's fixtures — the same bytes, imported from
`test_ingest_idempotency` rather than copied, so a replay hash here is comparable with an
idempotency hash there. The claim is about the database's behaviour under a rebuild; 36,000 rows
demonstrate it no better than three, and a 66 MB download demonstrates it no better at all.

**The weather source is exercised only for its foreign key**, and the difference is stated
rather than hidden. It has no `--file` and no `--force-parse` (M1's docstring argues why), so
there is no replay of it to run here. What it uniquely has is `weight_contribution`, which pins
a *reading* — the one place in this schema where a ruled-permanent row (D14 keeps contributions
when it erases authorship) depends on a publication id. A publication and reading are inserted
by hand, a contribution is pinned to the reading, and the two removal routes are measured
against it. Hand-inserted on purpose: what is being measured is the constraint, and routing
through the runner would only add a fixture between the test and the thing it is testing.
"""

import asyncio
import hashlib
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))
sys.path.insert(0, HERE)

import _tempdb  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

# M1's fixtures, source list and table-dump instrument, imported rather than re-typed. M1 is a
# passed measurement and its fixtures are frozen; if that stops being true this import is where
# the coupling shows, which is better than two drifting copies of the same zip.
import test_ingest_idempotency as m1  # noqa: E402

TEST_DB = "upto_m4_replay"
TAIPEI = timezone(timedelta(hours=8))
SLOT = datetime(2026, 8, 13, 19, 0, tzinfo=TAIPEI)

FORECAST_PIN = (
    "forecast_publication_id, forecast_township_code, forecast_element, "
    "forecast_measure, forecast_slot_start"
)

# Set aside in the shape-B publication comparison and nowhere else. `id` is a sequence value and
# `detected_at` is the clock reading the re-claiming run took; requiring either equal would be
# requiring the replay to be the original run rather than a replay of it.
RECLAIM_VARIES = ("id", "detected_at")

DELETE_ACTIONS = {
    "a": "NO ACTION",
    "r": "RESTRICT",
    "c": "CASCADE",
    "n": "SET NULL",
    "d": "SET DEFAULT",
}

# Every foreign key whose *target* is a publication, a reading or a source row table — the keys
# a replay has to answer for. Read from the catalog rather than from the migrations, because
# what is installed is the fact and a migration is a claim about it.
REFERENCING_KEYS = """
select
    con.conname,
    child.relname as child_table,
    (
        select string_agg(att.attname, ', ' order by k.ord)
        from unnest(con.conkey) with ordinality k(attnum, ord)
        join pg_attribute att on att.attrelid = con.conrelid and att.attnum = k.attnum
    ) as child_columns,
    parent.relname as parent_table,
    con.confdeltype
from pg_constraint con
join pg_class child on child.oid = con.conrelid
join pg_class parent on parent.oid = con.confrelid
where con.contype = 'f'
  and (
      parent.relname like '%\\_publication'
      or parent.relname like '%\\_reading'
      or parent.relname like '%\\_row'
      or parent.relname = 'reference_place'
  )
order by parent.relname, child.relname, con.conname
"""


# --------------------------------------------------------------------------------------
# Instruments
# --------------------------------------------------------------------------------------

async def dump(Session, table, exclude=()):
    """M1's total, column-complete dump, with an explicit exclusion list.

    M1 excludes nothing and argues why: a no-op inserts no row, so nothing may legitimately
    vary. A replay is different — it really does insert rows — so an exclusion is sometimes
    honest. Every use of `exclude` below names the column and says why in the assertion text.
    """
    names = [name for name in await m1.columns_of(Session, table) if name not in exclude]
    assert names, "every column of {} was excluded — the dump compares nothing".format(table)
    quoted = ", ".join('"{}"'.format(name) for name in names)
    ordering = ", ".join(str(index + 1) for index in range(len(names)))
    async with Session() as session:
        result = await session.execute(
            text("select {} from {} order by {}".format(quoted, table, ordering))
        )
        rows = [tuple(repr(cell) for cell in row) for row in result.fetchall()]
    return names, rows


def content_hash(shot):
    """md5 of the ordered dump. Order-independent in the sense that matters: the dump imposes a
    total order over whole rows, so two databases holding the same set of rows hash alike
    whatever order they were written in."""
    names, rows = shot
    hasher = hashlib.md5()
    hasher.update(("\x00".join(names) + "\x01").encode("utf-8"))
    for row in rows:
        hasher.update(("\x00".join(row) + "\x01").encode("utf-8"))
    return hasher.hexdigest()


def same(before, after):
    return m1.first_difference({"t": before}, {"t": after}) is None


def why_different(label, before, after):
    return "{}\n{}".format(label, m1.first_difference({"t": before}, {"t": after}))


async def count_rows(Session, table):
    async with Session() as session:
        return (await session.execute(text("select count(*) from {}".format(table)))).scalar_one()


async def run_sql(url, statement, params=None):
    """One statement on its own engine, so a refusal cannot poison the shared pool.

    Returns `None` when it succeeded, or `(exception class, first line)` when the database
    refused it. A refusal is a measurement here, not an error to propagate.
    """
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement), params or {})
    except Exception as failure:  # noqa: BLE001 — the refusal is the measurement
        return type(failure).__name__, str(failure).strip().splitlines()[0]
    finally:
        await engine.dispose()
    return None


async def last_run(Session, source):
    _, runs = await m1.ledger(Session, source)
    return runs[-1] if runs else None


async def runs_per_source(Session):
    async with Session() as session:
        result = await session.execute(
            text("select source, count(*) from ingest_run group by source order by source")
        )
        return {row[0]: row[1] for row in result.fetchall()}


def ledger_phrase(entry):
    """How the ledger describes a run, in the two fields that carry the outcome."""
    if entry is None:
        return "<no row>"
    return "{} / rows_written={}".format(entry["outcome"], entry["rows_written"])


# --------------------------------------------------------------------------------------
# Phase 1 — seed, and snapshot every source
# --------------------------------------------------------------------------------------

async def seed(Session, test_url, paths):
    """Run the five file sources once, in M1's order: D85's filter reads item 11's output."""
    baseline = {}
    for spec in m1.SOURCES:
        publication_table, row_table = spec["tables"]
        finished, seconds = m1.cli(spec["module"], ["--file", paths[spec["source"]]], test_url)
        assert finished.returncode == 0, "seeding {} exited {}\n{}\n{}".format(
            spec["name"], finished.returncode, finished.stdout, finished.stderr
        )
        rows = await dump(Session, row_table)
        assert rows[1], "{} seeded no rows — there is no rebuild to measure".format(spec["name"])
        baseline[spec["source"]] = {
            "publication": await dump(Session, publication_table),
            "publication_stable": await dump(Session, publication_table, RECLAIM_VARIES),
            "rows": rows,
            "rows_unpinned": await dump(Session, row_table, ("publication_id",)),
            "count": await count_rows(Session, row_table),
            "seed_seconds": seconds,
        }
    return baseline


# --------------------------------------------------------------------------------------
# Phase 2 — shape A: the rows only, publication kept
# --------------------------------------------------------------------------------------

async def shape_a(Session, test_url, paths, baseline, results):
    for spec in m1.SOURCES:
        publication_table, row_table = spec["tables"]
        held = baseline[spec["source"]]

        refusal = await run_sql(test_url, "truncate {}".format(row_table))
        assert refusal is None, "truncating {} was refused: {}".format(row_table, refusal)
        assert await count_rows(Session, row_table) == 0, "{} did not empty".format(row_table)

        finished, seconds = m1.cli(
            spec["module"], ["--file", paths[spec["source"]], "--force-parse"], test_url
        )
        assert finished.returncode == 0, "{} replay exited {}\n{}\n{}".format(
            spec["name"], finished.returncode, finished.stdout, finished.stderr
        )
        assert "re-parsed into" in finished.stdout, (
            "{}: the replay did not re-parse, so it proves nothing:\n{}".format(
                spec["name"], finished.stdout
            )
        )

        rebuilt = await dump(Session, row_table)
        rebuilt_count = await count_rows(Session, row_table)
        assert same(held["rows"], rebuilt), why_different(
            "{}: shape A rebuilt {} differently — every column is comparable here, because the "
            "publication id was never removed".format(spec["name"], row_table),
            held["rows"], rebuilt,
        )
        assert rebuilt_count == held["count"], "{}: {} rows, expected {}".format(
            spec["name"], rebuilt_count, held["count"]
        )

        publication_now = await dump(Session, publication_table)
        assert same(held["publication"], publication_now), why_different(
            "{}: shape A moved the publication row, which it never wrote to".format(spec["name"]),
            held["publication"], publication_now,
        )

        entry = await last_run(Session, spec["source"])
        results.append({
            "source": spec["name"],
            "shape": "A: rows only, publication kept",
            "counts": "{} -> 0 -> {}".format(held["count"], rebuilt_count),
            "counts_match": rebuilt_count == held["count"],
            "hash_match": content_hash(held["rows"]) == content_hash(rebuilt),
            "ledger": ledger_phrase(entry),
            "seconds": seconds,
        })
        # The ledger's own account of a replay, recorded rather than asserted into a shape it
        # does not have: see the report footnotes.
        assert entry is not None and entry["outcome"] == "no_change", (
            "{}: a replay recorded {!r} — expected `no_change`, because the publication was "
            "already held and the claim is what decides the outcome".format(
                spec["name"], entry and entry["outcome"]
            )
        )
        assert "re-parsed into" in (entry["detail"] or ""), (
            "{}: the ledger row does not say the run re-parsed, so nothing in the database "
            "explains the rebuild".format(spec["name"])
        )


# --------------------------------------------------------------------------------------
# Phase 3 — the cross-source order (D85 reads item 11's latest publication)
# --------------------------------------------------------------------------------------

async def cross_source(Session, test_url, paths, baseline, results, findings):
    place = next(spec for spec in m1.SOURCES if spec["source"] == "fda-97")
    tax = next(spec for spec in m1.SOURCES if spec["source"] == "fia-business-tax")
    place_held, tax_held = baseline[place["source"]], baseline[tax["source"]]

    for table in ("reference_place", "business_tax_row"):
        refusal = await run_sql(test_url, "truncate {}".format(table))
        assert refusal is None, "truncating {} was refused: {}".format(table, refusal)

    # Wrong order: tax first, with the place rows it filters against still missing.
    started = time.perf_counter()
    finished, seconds = m1.cli(
        tax["module"], ["--file", paths[tax["source"]], "--force-parse"], test_url
    )
    kept_wrong_order = await count_rows(Session, "business_tax_row")
    entry = await last_run(Session, tax["source"])
    findings["tax_before_place"] = {
        "exit": finished.returncode,
        "kept": kept_wrong_order,
        "stderr": (finished.stderr or "").strip().splitlines()[-1:] or ["<empty>"],
        "ledger": ledger_phrase(entry),
    }
    assert finished.returncode == 1, (
        "replaying D85's tax source before item 11's places was expected to fail loudly; it "
        "exited {} and left {} rows\n{}\n{}".format(
            finished.returncode, kept_wrong_order, finished.stdout, finished.stderr
        )
    )
    assert kept_wrong_order == 0, (
        "the failed out-of-order replay still wrote {} rows — a partial rebuild is worse than "
        "no rebuild, because nothing afterwards can tell it from a complete one".format(
            kept_wrong_order
        )
    )
    assert entry is not None and entry["outcome"] == "failed", (
        "the out-of-order replay recorded {!r} — a source that could not be joined is a "
        "failure, and recording it as a no-op is how a broken backfill looks healthy".format(
            entry and entry["outcome"]
        )
    )
    results.append({
        "source": tax["name"],
        "shape": "cross-source: tax replayed BEFORE place restored",
        "counts": "{} -> 0 -> 0".format(tax_held["count"]),
        "counts_match": False,
        "hash_match": False,
        "ledger": ledger_phrase(entry),
        "seconds": seconds,
    })
    del started

    # Right order: place, then tax.
    finished, place_seconds = m1.cli(
        place["module"], ["--file", paths[place["source"]], "--force-parse"], test_url
    )
    assert finished.returncode == 0, "the place replay exited {}\n{}".format(
        finished.returncode, finished.stderr
    )
    restored = await dump(Session, "reference_place")
    assert same(place_held["rows"], restored), why_different(
        "the place replay did not restore reference_place identically", place_held["rows"], restored
    )

    finished, tax_seconds = m1.cli(
        tax["module"], ["--file", paths[tax["source"]], "--force-parse"], test_url
    )
    assert finished.returncode == 0, "the tax replay exited {}\n{}".format(
        finished.returncode, finished.stderr
    )
    rebuilt = await dump(Session, "business_tax_row")
    rebuilt_count = await count_rows(Session, "business_tax_row")
    assert same(tax_held["rows"], rebuilt), why_different(
        "tax replayed after place did not rebuild identically", tax_held["rows"], rebuilt
    )
    entry = await last_run(Session, tax["source"])
    results.append({
        "source": "{} after {}".format(tax["name"], place["name"]),
        "shape": "cross-source: place FIRST, then tax",
        "counts": "0 -> {}".format(rebuilt_count),
        "counts_match": rebuilt_count == tax_held["count"],
        "hash_match": content_hash(tax_held["rows"]) == content_hash(rebuilt),
        "ledger": ledger_phrase(entry),
        "seconds": place_seconds + tax_seconds,
    })


# --------------------------------------------------------------------------------------
# Phase 4 — shape B: publication and rows, on item 11's place source
# --------------------------------------------------------------------------------------

async def shape_b(Session, test_url, paths, baseline, results, findings):
    place = next(spec for spec in m1.SOURCES if spec["source"] == "fda-97")
    held = baseline[place["source"]]

    async with Session() as session:
        old_id = (
            await session.execute(text("select id from place_publication"))
        ).scalar_one()
        pinning = (
            await session.execute(
                text(
                    "select id, source, outcome from ingest_run "
                    "where place_publication_id = :p order by id"
                ),
                {"p": old_id},
            )
        ).fetchall()
    findings["pinned_runs"] = {
        "publication_id": old_id,
        "rows": [(row[0], row[1], row[2]) for row in pinning],
    }
    assert pinning, (
        "no ingest_run row points at the place publication, so the FK question this phase "
        "exists to measure does not arise — the seeding did not record itself"
    )

    # Route 1: DELETE. `ingest_run.place_publication_id` is ON DELETE SET NULL, and a `stored`
    # run with no publication attached violates ck_ingest_run_stored_has_publication — so the
    # question is whether the cascade's own UPDATE trips that CHECK.
    findings["delete_publication"] = await run_sql(
        test_url, "delete from place_publication where id = :p", {"p": old_id}
    )

    # Route 2: TRUNCATE CASCADE. **This assertion was inverted 2026-08-18 and the inversion is
    # the point.** Until revision 0020 this phase *measured a bypass*: `truncate place_publication
    # cascade` was allowed and it emptied `ingest_run` for every source at once, because all seven
    # publication foreign keys live on that one table. H32 recorded it; the owner ruled the guard;
    # 0020's `BEFORE TRUNCATE` trigger on `ingest_run` now aborts the whole statement. So the test
    # that found the hole is the test that holds it shut, and what it asserts is the refusal.
    before = await runs_per_source(Session)
    refusal = await run_sql(test_url, "truncate place_publication")
    findings["truncate_publication_plain"] = refusal
    guarded = await run_sql(test_url, "truncate place_publication cascade")
    findings["truncate_cascade_guarded"] = guarded
    assert guarded is not None, (
        "truncate place_publication cascade was ALLOWED — revision 0020's guard on ingest_run is "
        "missing or disabled, and H32's silent path is open again: this statement empties the "
        "ledger for every source at once"
    )
    assert "H32" in guarded[1], (
        "the cascade was refused by something other than 0020's guard: {}".format(guarded)
    )
    assert await runs_per_source(Session) == before, (
        "the refused cascade still moved the ledger — a BEFORE TRUNCATE trigger must abort the "
        "whole statement, not part of it"
    )
    assert await count_rows(Session, "reference_place") > 0, (
        "the refused cascade still emptied reference_place"
    )

    # The deliberate door, typed out on purpose. 0020 claims to stop the accident, not the intent
    # (`cannot be done by accident, not cannot be done`), and shape B needs the publication gone to
    # measure a from-scratch rebuild. So the route is: disable the guard, truncate, re-enable — and
    # the fact that it takes three statements and names the trigger is the mitigation working.
    disabled = await run_sql(test_url, "alter table ingest_run disable trigger upto_no_truncate")
    assert disabled is None, "could not disable the guard for the deliberate route: {}".format(
        disabled
    )
    refusal = await run_sql(test_url, "truncate place_publication cascade")
    assert refusal is None, "truncate cascade was refused with the guard disabled: {}".format(
        refusal
    )
    restored = await run_sql(test_url, "alter table ingest_run enable trigger upto_no_truncate")
    assert restored is None, "the guard was not restored: {}".format(restored)
    findings["deliberate_route"] = "guard disabled, truncated, guard re-enabled"
    after = await runs_per_source(Session)
    findings["truncate_cascade"] = {
        "ledger_before": before,
        "ledger_after": after,
        "reference_place": await count_rows(Session, "reference_place"),
        "other_sources_intact": {
            spec["tables"][1]: await count_rows(Session, spec["tables"][1])
            for spec in m1.SOURCES
            if spec["source"] != "fda-97"
        },
    }
    assert await count_rows(Session, "reference_place") == 0
    assert await count_rows(Session, "place_publication") == 0

    # The rebuild: no flags, because the content is no longer held and the runner must re-claim.
    finished, seconds = m1.cli(place["module"], ["--file", paths[place["source"]]], test_url)
    assert finished.returncode == 0, "the shape-B rebuild exited {}\n{}\n{}".format(
        finished.returncode, finished.stdout, finished.stderr
    )
    assert "stored publication" in finished.stdout, (
        "the rebuild did not store a new publication:\n{}".format(finished.stdout)
    )

    async with Session() as session:
        new_id, new_sha = (
            await session.execute(
                text("select id, content_sha256 from place_publication")
            )
        ).one()
    old_sha = dict(zip(*[held["publication"][0], held["publication"][1][0]]))["content_sha256"]
    findings["reclaim"] = {
        "old_publication_id": old_id,
        "new_publication_id": new_id,
        "content_sha256_equal": repr(new_sha) == old_sha,
        "orphaned_ledger_rows": len(findings["pinned_runs"]["rows"]),
        "exact_hash_match": None,  # filled in once the rows are dumped, below
    }
    assert repr(new_sha) == old_sha, (
        "the re-claimed publication carries a different content hash ({!r} vs {}), so the "
        "replay is not a replay of the same file".format(new_sha, old_sha)
    )
    assert new_id != old_id, (
        "the re-claimed publication reused id {} — that would make this phase's finding "
        "vanish, and it would mean the sequence was reset behind the runner's back".format(old_id)
    )

    publication_stable = await dump(Session, "place_publication", RECLAIM_VARIES)
    assert same(held["publication_stable"], publication_stable), why_different(
        "the re-claimed place publication differs in a column that is not the id or the "
        "detected_at stamp — those two are excluded because a sequence and a clock reading "
        "cannot repeat; anything else differing means the replay read the file differently",
        held["publication_stable"], publication_stable,
    )

    rebuilt_unpinned = await dump(Session, "reference_place", ("publication_id",))
    rebuilt_count = await count_rows(Session, "reference_place")
    assert same(held["rows_unpinned"], rebuilt_unpinned), why_different(
        "the shape-B rebuild changed a place row's content. `publication_id` is set aside for "
        "this comparison and only this one: the publication it points at is a different row "
        "than the one the original rows pointed at, which is the finding rather than a defect "
        "in the comparison",
        held["rows_unpinned"], rebuilt_unpinned,
    )
    exact = await dump(Session, "reference_place")
    findings["reclaim"]["exact_hash_match"] = content_hash(held["rows"]) == content_hash(exact)
    results.append({
        "source": place["name"],
        "shape": "B: publication + rows, re-claimed",
        "counts": "{} -> 0 -> {}".format(held["count"], rebuilt_count),
        "counts_match": rebuilt_count == held["count"],
        "hash_match": content_hash(held["rows_unpinned"]) == content_hash(rebuilt_unpinned),
        "exact_hash_match": content_hash(held["rows"]) == content_hash(exact),
        "ledger": ledger_phrase(await last_run(Session, place["source"])),
        "seconds": seconds,
    })

    # And the cross-source claim once more, now that the place publication id has moved: D85's
    # filter reads the *latest* publication, so a re-claimed one must give the same 統編 set.
    tax = next(spec for spec in m1.SOURCES if spec["source"] == "fia-business-tax")
    finished, tax_seconds = m1.cli(
        tax["module"], ["--file", paths[tax["source"]], "--force-parse"], test_url
    )
    assert finished.returncode == 0, "the post-reclaim tax replay exited {}\n{}".format(
        finished.returncode, finished.stderr
    )
    rebuilt = await dump(Session, "business_tax_row")
    assert same(baseline[tax["source"]]["rows"], rebuilt), why_different(
        "after the place publication was re-claimed under a new id, D85's filter kept a "
        "different set of tax rows", baseline[tax["source"]]["rows"], rebuilt,
    )
    results.append({
        "source": "{} against the re-claimed place publication".format(tax["name"]),
        "shape": "cross-source: filter re-read after re-claim",
        "counts": "{} -> {}".format(
            baseline[tax["source"]]["count"], await count_rows(Session, "business_tax_row")
        ),
        "counts_match": True,
        "hash_match": True,
        "ledger": ledger_phrase(await last_run(Session, tax["source"])),
        "seconds": tax_seconds,
    })


# --------------------------------------------------------------------------------------
# Phase 5 — the weather source's own foreign key: weight_contribution pins a reading
# --------------------------------------------------------------------------------------

async def weather_pin(Session, test_url, findings):
    async with Session() as session:
        circle = (
            await session.execute(text("insert into circle (name) values ('M4') returning id"))
        ).scalar_one()
        principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        member = (
            await session.execute(
                text(
                    "insert into member (principal_id, circle_id, nickname) "
                    "values (:p, :c, 'M4') returning id"
                ),
                {"p": principal, "c": circle},
            )
        ).scalar_one()
        place_id = (
            await session.execute(
                text(
                    "insert into place (origin, circle_id, name) "
                    "values ('circle-local', :c, '小林拉麵') returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        round_id = (
            await session.execute(
                text(
                    "insert into round (circle_id, target_hour, target_hour_typed) "
                    "values (:c, now() + interval '2 hours', false) returning id"
                ),
                {"c": circle},
            )
        ).scalar_one()
        await session.execute(
            text("insert into proposal (round_id, place_id, member_id) values (:r, :p, :m)"),
            {"r": round_id, "p": place_id, "m": member},
        )
        publication = (
            await session.execute(
                text(
                    "insert into forecast_publication "
                    "(dataset_id, content_sha256, detected_at, payload_bytes) "
                    "values ('F-D0047-061', repeat('a', 64), now(), 1000) returning id"
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into forecast_reading (publication_id, township, township_code, element, "
                "slot_start, measure, value) values (:pub, '松山區', '63000010', '降雨機率', "
                ":slot, 'ProbabilityOfPrecipitation', '80')"
            ),
            {"pub": publication, "slot": SLOT},
        )
        await session.execute(
            text(
                "insert into weight_contribution (round_id, place_id, channel, contributor, "
                "effect, reason, reason_visibility, {}) values (:r, :p, 'contextual', 'weather', "
                "0.8, '降雨機率80%', 'none', :pub, '63000010', '降雨機率', "
                "'ProbabilityOfPrecipitation', :slot)".format(FORECAST_PIN)
            ),
            {"r": round_id, "p": place_id, "pub": publication, "slot": SLOT},
        )
        await session.commit()

    findings["weather"] = {
        "publication_id": publication,
        "delete_publication": await run_sql(
            test_url, "delete from forecast_publication where id = :p", {"p": publication}
        ),
        "contributions_after_delete": await count_rows(Session, "weight_contribution"),
    }
    # The worse half of H32, and now the guarded half. `truncate forecast_publication cascade`
    # used to remove `weight_contribution` rows through the five-column composite key — D14's
    # permanent rows, silently, where the same DELETE is refused. 0020 puts the guard on
    # `weight_contribution` itself, so the cascade is aborted from the far end.
    truncate = await run_sql(test_url, "truncate forecast_publication cascade")
    findings["weather"]["truncate_cascade"] = truncate
    findings["weather"]["contributions_after_truncate"] = await count_rows(
        Session, "weight_contribution"
    )
    findings["weather"]["readings_after_truncate"] = await count_rows(Session, "forecast_reading")
    assert truncate is not None, (
        "truncate forecast_publication cascade was ALLOWED — 0020's guard on weight_contribution "
        "is missing, and D14's permanent rows are removable by a statement the schema refuses in "
        "its DELETE form"
    )
    assert "H32" in truncate[1], (
        "the weather cascade was refused by something other than 0020's guard: {}".format(truncate)
    )
    assert findings["weather"]["contributions_after_truncate"] == 1, (
        "the refused cascade still cost the contribution row"
    )

    # **And now the guard that the statement above did NOT exercise.** `truncate
    # forecast_publication cascade` reaches `ingest_run` as well (it holds a
    # `forecast_publication_id`), so the refusal above came from the ledger's trigger and says so
    # in its message — which leaves 0020's *second* trigger unproven. `forecast_reading` is
    # referenced by `weight_contribution` and by nothing in the ledger, so a cascade from there
    # can only be stopped by the guard on the contributions themselves. Measured separately
    # because one refusal standing in for two is how a half-installed mitigation reads as whole.
    contribution_guard = await run_sql(test_url, "truncate forecast_reading cascade")
    findings["weather"]["truncate_reading_cascade"] = contribution_guard
    assert contribution_guard is not None, (
        "truncate forecast_reading cascade was ALLOWED — 0020's guard on weight_contribution is "
        "missing, and D14's permanent rows go with the reading they pin"
    )
    assert "weight_contribution" in contribution_guard[1], (
        "the reading cascade was refused, but not by the contribution guard: {}".format(
            contribution_guard
        )
    )
    assert await count_rows(Session, "weight_contribution") == 1, (
        "the refused reading cascade still cost the contribution row"
    )

    assert findings["weather"]["delete_publication"] is not None, (
        "deleting a forecast publication that a weight_contribution pins through its reading "
        "was allowed — D14 keeps contributions when it erases authorship, so this row is not "
        "the database's to discard"
    )
    assert findings["weather"]["contributions_after_delete"] == 1, (
        "the refused DELETE still cost a contribution row"
    )


# --------------------------------------------------------------------------------------
# Phase 6 — the referencing keys, from the catalog
# --------------------------------------------------------------------------------------

async def referencing_keys(Session):
    async with Session() as session:
        result = await session.execute(text(REFERENCING_KEYS))
        rows = result.fetchall()
    keys = []
    for row in rows:
        # `confdeltype` is Postgres `"char"`, which asyncpg hands back as a single byte.
        action = row[4].decode("ascii") if isinstance(row[4], bytes) else row[4]
        keys.append((row[1], row[2], row[3], DELETE_ACTIONS.get(action, action), row[0]))
    return keys


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------

def mark(value):
    return "yes" if value else "NO"


def table(title, header, body):
    widths = [max(len(line[i]) for line in [header] + body) for i in range(len(header))]
    rule = "  ".join("-" * width for width in widths)
    print()
    print(title)
    print(rule)
    print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(header)))
    print(rule)
    for line in body:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(line)))
    print(rule)


def report(results, findings, keys):
    table(
        "M4 — backfill / replay",
        ("source", "replay shape", "rows", "counts match", "hash match", "ingest_run", "seconds"),
        [
            (
                row["source"], row["shape"], row["counts"], mark(row["counts_match"]),
                mark(row["hash_match"]), row["ledger"], "{:.2f}".format(row["seconds"]),
            )
            for row in results
        ],
    )

    table(
        "Every foreign key a replay has to answer for (from pg_constraint, not the migrations)",
        ("child table", "child columns", "target", "on delete", "constraint"),
        [tuple(row) for row in keys],
    )

    print()
    print("FK-orphan finding — shape B, item 11's place source")
    print("  the publication id moved: {} -> {} (content_sha256 identical: {})".format(
        findings["reclaim"]["old_publication_id"],
        findings["reclaim"]["new_publication_id"],
        mark(findings["reclaim"]["content_sha256_equal"]),
    ))
    print("  reference_place content hash with publication_id set aside: matches the original.")
    print("  reference_place content hash with publication_id included:  {}.".format(
        "matches" if findings["reclaim"]["exact_hash_match"] else "DOES NOT match — the rows are"
        " the same facts pinned to a different publication row"
    ))
    print("  ingest_run.place_publication_id pointed at the OLD id {} from {} row(s):".format(
        findings["pinned_runs"]["publication_id"], len(findings["pinned_runs"]["rows"])
    ))
    for run_id, source, outcome in findings["pinned_runs"]["rows"]:
        print("    ingest_run.id={} source={} outcome={}".format(run_id, source, outcome))
    print("  DELETE from place_publication: {}".format(
        "REFUSED — {}: {}".format(*findings["delete_publication"])
        if findings["delete_publication"] else "allowed"
    ))
    print("  TRUNCATE place_publication (no cascade): {}".format(
        "REFUSED — {}: {}".format(*findings["truncate_publication_plain"])
        if findings["truncate_publication_plain"] else "allowed"
    ))
    print("  TRUNCATE place_publication CASCADE: {}".format(
        "REFUSED by 0020's guard — {}: {}".format(*findings["truncate_cascade_guarded"])
        if findings["truncate_cascade_guarded"] else "ALLOWED — H32's path is open again"
    ))
    print("  the deliberate route ({}) then emptied it —".format(findings["deliberate_route"]))
    print("    ledger rows before: {}".format(findings["truncate_cascade"]["ledger_before"]))
    print("    ledger rows after:  {}".format(findings["truncate_cascade"]["ledger_after"]))
    print("    other sources' row tables, untouched: {}".format(
        findings["truncate_cascade"]["other_sources_intact"]
    ))

    print()
    print("Ordering finding — D85's tax source against item 11's places")
    print("  tax replayed BEFORE place restored: exit {}, {} rows kept, ledger {}".format(
        findings["tax_before_place"]["exit"],
        findings["tax_before_place"]["kept"],
        findings["tax_before_place"]["ledger"],
    ))
    print("    {}".format(findings["tax_before_place"]["stderr"][0]))
    print("  place FIRST then tax: rebuilt identically (row above)")

    print()
    print("Ledger finding — what `ingest_run` says about a shape-A replay")
    print("  outcome `no_change`, rows_written 0, for a run that rebuilt every row of the table.")
    print("  Both fields are forced by the schema, not by the runner: the claim short-circuits")
    print("  on a hash it already holds, so `stored` is false, and")
    print("  ck_ingest_run_rows_only_when_stored refuses a non-zero count on any other outcome.")
    print("  The rebuild is recoverable only from `detail`, which reads `re-parsed into")
    print("  publication N — … rows held`. A reader counting rows_written sees a replay as a")
    print("  no-op. Reported, not fixed: app/api/src is not this measurement's to change.")

    print()
    print("Weather finding — weight_contribution pins a reading, not a publication")
    weather = findings["weather"]
    print("  DELETE forecast_publication id={}: {}".format(
        weather["publication_id"],
        "REFUSED — {}: {}".format(*weather["delete_publication"])
        if weather["delete_publication"] else "ALLOWED",
    ))
    print("  TRUNCATE forecast_publication CASCADE: {}".format(
        "REFUSED — {}: {}".format(*weather["truncate_cascade"])
        if weather["truncate_cascade"] else "ALLOWED",
    ))
    # Printed separately because the statement above is refused by the *ledger's* guard — a
    # forecast publication is pinned by `ingest_run` too — so it proves nothing about the guard on
    # the contributions. This one can only be refused by that second trigger.
    print("  TRUNCATE forecast_reading CASCADE: {}".format(
        "REFUSED by the contribution guard — {}: {}".format(
            *weather["truncate_reading_cascade"])
        if weather.get("truncate_reading_cascade") else "ALLOWED",
    ))
    print("  weight_contribution rows: 1 before, {} after the refused DELETE, {} after the "
          "cascade".format(
              weather["contributions_after_delete"], weather["contributions_after_truncate"]
          ))
    print("  forecast_reading rows after the cascade: {}".format(
        weather["readings_after_truncate"]
    ))


# --------------------------------------------------------------------------------------

async def scenario(test_url):
    os.environ["UPTO_DATABASE_URL"] = test_url
    engine = create_async_engine(test_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    directory = tempfile.mkdtemp(prefix="m4-replay-")
    paths = {}
    for spec in m1.SOURCES:
        path = os.path.join(directory, spec["source"] + spec["suffix"])
        with open(path, "wb") as handle:
            handle.write(spec["fixture"]())
        paths[spec["source"]] = path

    results, findings = [], {}
    try:
        baseline = await seed(Session, test_url, paths)
        await shape_a(Session, test_url, paths, baseline, results)
        await cross_source(Session, test_url, paths, baseline, results, findings)
        await shape_b(Session, test_url, paths, baseline, results, findings)
        await weather_pin(Session, test_url, findings)
        keys = await referencing_keys(Session)
    finally:
        if results and "reclaim" in findings and "weather" in findings:
            report(results, findings, keys)
        else:
            print("\nM4 stopped early — partial results:", results, findings, file=sys.stderr)
        await engine.dispose()
        from upto.db import dispose_all  # noqa: PLC0415

        await dispose_all()
        for path in paths.values():
            os.unlink(path)
        os.rmdir(directory)

    print()
    print(
        "M4: a truncated row table rebuilds exactly — same count, same content hash, every "
        "column including the publication id — when the publication survives, and the ledger "
        "records the rebuild as a `no_change` whose detail line says it re-parsed. When the "
        "publication is removed too the rows come back with identical content but a new "
        "publication id, so the claim holds only up to that id, and the keys that pinned the "
        "old one are listed above. D85's tax source must be replayed after item 11's places "
        "and fails loudly rather than quietly when it is not."
    )


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""

    async def run(test_url: str, environment: dict) -> None:
        # D27's key: a place points at a township, so ticket 06's twelve codes come first.
        from upto.seed.township_station import load  # noqa: PLC0415

        await load(test_url)
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, run)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
