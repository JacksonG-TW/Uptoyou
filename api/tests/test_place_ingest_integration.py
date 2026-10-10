#!/usr/bin/env python3
"""H14's item-11 test, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_place_ingest_integration.py

**The H14 scenario was committed unrun on purpose** — no database was reachable when it was
written, so every assertion in it was a claim about what the code should do rather than a report
of what it did. An assertion written before the first live run is one that has not been fitted to
whatever the first live run happened to produce. **It first passed 2026-08-12**, unchanged.

**A second scenario was added 2026-08-12: `runlog_scenario`, ticket 09's run row.** Its own
header says what it holds and how it was shown to discriminate.

H14 names this test, and names what it must not settle for:

    "run the ingest, run it again against an unchanged file, and assert **one** publication row
    and 232,212 data rows rather than two and 464,424 — with the short-circuit **deliberately
    disabled**, so that what is being tested is the constraint rather than the scheduler's good
    behaviour. A test that passes only because the ingest declined to write proves nothing about
    this hazard."

That is the third scenario below. The row count is this ingest's own — 臺北市 `餐飲場所`, not the
nationwide 232,212 the hazard quotes — and the fixture is small, because the property under test
is the key rather than the volume.

**How to show these assertions discriminate, which is the step item 10's test took and this one
has not.** Change the publication key from the content hash to the run: in `0003`, replace the
unique constraint `(source, content_sha256)` with `(source, detected_at)`, and the conflict target
in `fda_store.CLAIM_PUBLICATION` with it. That is D18's fallback, which D35 rejects for this
source. Under it the second run mints a second publication and writes the same places again, so
`test_an_unchanged_file_produces_no_duplicate` must fail with *expected one publication, got 2*.
A test that cannot fail under the wrong key is the test H14 threw out.

The test builds its own database and drops it, so it never touches the stack's data.
"""

import asyncio
import io
import os
import sys
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import _tempdb  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.ingest import fda  # noqa: E402
from upto.ingest.fda_store import PlaceStore  # noqa: E402
from upto.ingest.run_places import ingest_archive  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))
TEST_DB = "upto_item11_check"

HEADER = "公司或商業登記名稱,公司統一編號,業者地址,食品業者登錄字號,登錄項目"

# Three rows: one ordinary, one carrying the defects the real file carries (H25 — a fixture
# with no defect never reaches the code that cleans one), and one real address that resolves
# to no township at all.
ROWS = [
    '"福利麵包食品有限公司","11820764","台北市信義區菸廠路88號B1","A-111820764-00022-1","餐飲場所"',
    '"全家便利商店股份有限公司","23060248","臺北市中正區忠孝西路一段４９號Ｂ１","A-123060248-13440-5","餐飲場所"',
    '"某小吃店","20003433","台北市長安東路一段58號","A-200034336-00001-9","餐飲場所"',
]
CHANGED_ROWS = ROWS[:2] + [
    '"某小吃店","20003433","台北市中山區長安東路一段58號","A-200034336-00001-9","餐飲場所"',
]
# A third distinct content, for the run-row scenario, so it never has to reuse a hash the H14
# scenario above already spent.
LATER_ROWS = ROWS[:2] + [
    '"某小吃店","20003433","台北市大安區長安東路一段58號","A-200034336-00001-9","餐飲場所"',
]

PLACES = len(ROWS)


def archive_bytes(rows, stamp):
    body = "\r\n".join([HEADER] + rows) + "\r\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(zipfile.ZipInfo("97_2.csv", date_time=stamp), b"\xef\xbb\xbf" + body.encode("utf-8"))
    return buffer.getvalue()


def archive(rows, stamp, detected_at, raw=None):
    """Read the bytes into an Archive.

    **Each call reads them again on purpose.** This helper used to be called once per file and
    the resulting object reused for every run, which meant the identity of a publication was
    only ever computed once — so a key that varies per *read* was invisible, and the mutant
    that models D18's run-interval fallback survived. Re-reading is what makes the second run
    a second run.
    """
    return fda.read_archive(archive_bytes(rows, stamp) if raw is None else raw, detected_at)


async def counts(Session):
    async with Session() as session:
        publications = await session.execute(text("select count(*) from place_publication"))
        places = await session.execute(text("select count(*) from reference_place"))
        return publications.scalar(), places.scalar()


async def scenario(test_url: str) -> None:
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    JULY_STAMP = (2026, 7, 3, 9, 16, 50)
    july_raw = archive_bytes(ROWS, JULY_STAMP)
    july = archive(ROWS, JULY_STAMP, datetime(2026, 8, 10, 3, 0, tzinfo=TAIPEI), raw=july_raw)
    august = archive(CHANGED_ROWS, (2026, 8, 3, 10, 41, 40), datetime(2026, 8, 11, 3, 0, tzinfo=TAIPEI))

    # 1 — the first run stores a publication and its places.
    async with Session() as session:
        first = await ingest_archive(PlaceStore(session), july)
    assert first.stored, "the first run must store a publication"
    assert first.parsed
    assert first.rows_held == PLACES, "expected {} places, got {}".format(PLACES, first.rows_held)
    assert len(first.unresolved) == 1, "the address with no district must be reported"
    assert first.alarms == [], "nothing to disagree with on a first run"
    assert await counts(Session) == (1, PLACES)

    # 2 — the same file again. Nothing is written, nothing is parsed, and the run succeeds.
    # Re-read, with a later detected_at: the bytes are identical and only the clock moved,
    # which is exactly what an unchanged day looks like to the scheduler.
    july_again = archive(ROWS, JULY_STAMP, datetime(2026, 8, 10, 4, 0, tzinfo=TAIPEI), raw=july_raw)
    async with Session() as session:
        again = await ingest_archive(PlaceStore(session), july_again)
    assert not again.stored, "an unchanged file must not store a second publication"
    assert not again.parsed, "an unchanged file must not be parsed at all (D34)"
    assert again.exit_code() == 0, "a no-op is a success, not a warning"
    assert await counts(Session) == (1, PLACES)

    # 3 — H14's own scenario: run it again with the short-circuit **disabled**, so the
    # constraint is what stops the duplicate rather than this module's good behaviour.
    july_third = archive(ROWS, JULY_STAMP, datetime(2026, 8, 10, 5, 0, tzinfo=TAIPEI), raw=july_raw)
    async with Session() as session:
        forced = await ingest_archive(PlaceStore(session), july_third, force_parse=True)
    assert forced.parsed, "force-parse must actually parse"
    assert not forced.stored, "no second publication may be created for the same content"
    assert forced.rows_held == PLACES, "the places must not have doubled: {}".format(forced.rows_held)
    publications, places = await counts(Session)
    assert publications == 1, "expected one publication, got {}".format(publications)
    assert places == PLACES, "expected {} places, got {}".format(PLACES, places)

    # 4 — the township came out of the address, and the row that had none was stored anyway.
    async with Session() as session:
        result = await session.execute(
            text(
                "select registry_no, township_code, township_name, origin, address, address_raw "
                "from reference_place order by registry_no"
            )
        )
        rows = {row.registry_no: row for row in result}
    assert rows["A-111820764-00022-1"].township_code == "63000020", "信義區 by address (D27)"
    assert rows["A-123060248-13440-5"].township_code == "63000050", "中正區, full-width folded"
    assert rows["A-123060248-13440-5"].address == "臺北市中正區忠孝西路一段49號B1"
    assert rows["A-123060248-13440-5"].address_raw.endswith("４９號Ｂ１"), "the raw string survives (H24)"
    assert rows["A-200034336-00001-9"].township_code is None, "no district in the address"
    assert rows["A-200034336-00001-9"].township_name is None
    for row in rows.values():
        assert row.origin == "reference", "D28: the origin is recorded on every row"

    async with Session() as session:
        recorded = await session.execute(
            text("select place_rows, unresolved_township_rows, scope, archive_stamp from place_publication")
        )
        publication = recorded.fetchone()
    assert publication.place_rows == PLACES
    assert publication.unresolved_township_rows == 1
    assert publication.scope == fda.SCOPE
    assert publication.archive_stamp == datetime(2026, 7, 3, 9, 16, 50, tzinfo=TAIPEI), (
        "the stamp is stored as the label, with its zone (H17)"
    )

    # 5 — a genuinely new file. Both publications survive; the earlier rows do not move,
    # because a round's snapshot may already have pinned one (D15).
    async with Session() as session:
        second = await ingest_archive(PlaceStore(session), august)
    assert second.stored, "changed content is a new publication"
    assert second.alarms == [], "both signals moved together, which is agreement"
    publications, places = await counts(Session)
    assert publications == 2, "expected two publications, got {}".format(publications)
    assert places == 2 * PLACES, "expected {} places, got {}".format(2 * PLACES, places)

    async with Session() as session:
        pinned = await session.execute(
            text(
                "select p.detected_at, r.township_code from reference_place r "
                "join place_publication p on p.id = r.publication_id "
                "where r.registry_no = :registry order by p.detected_at"
            ),
            {"registry": "A-200034336-00001-9"},
        )
        versions = pinned.fetchall()
    assert len(versions) == 2
    assert versions[0].township_code is None, "the earlier row was rewritten"
    assert versions[1].township_code == "63000040", "the later row reads its township (中山區)"

    # 6 — re-running the *first* file after the second one must still change nothing.
    async with Session() as session:
        rerun = await ingest_archive(PlaceStore(session), july)
    assert not rerun.stored
    assert not rerun.parsed
    assert await counts(Session) == (2, 2 * PLACES)

    await engine.dispose()
    print("H14/item 11: one publication per content hash; a forced re-parse writes no duplicate")


async def runs(Session):
    """Every run row, oldest first, with the three publication columns beside it."""
    async with Session() as session:
        result = await session.execute(
            text(
                "select id, source, outcome, rows_written, detail, invoked_by, started_at, "
                "finished_at, forecast_publication_id, observation_publication_id, "
                "place_publication_id from ingest_run order by id"
            )
        )
        return result.fetchall()


async def runlog_scenario(test_url: str) -> None:
    """Ticket 09's other half: **a run leaves a row, including the runs that wrote nothing.**

    `run_places` never called `runlog.record`, so item 11 left no `ingest_run` row on any path —
    not on the daily no-op D34 schedules, not on a failure, not even when it stored. This goes
    through `ingest_once`, which is where the row is written, rather than through
    `ingest_archive` as the H14 scenario above does.

    **What this asserts that the unit tests cannot:** revision 0005's CHECKs. `run_record`'s
    mapping is asserted in `test_fda_ingest.py` with no database; here the rows have to survive
    `ck_ingest_run_stored_has_publication`, `ck_ingest_run_rows_only_when_stored` and
    `ck_ingest_run_outcome`, which is why a wrong mapping fails as an `IntegrityError` rather
    than as a mismatched value.

    **Shown to discriminate.** Delete the `runlog.record` call at the end of `ingest_once` and
    the first assertion below fails with *expected one run row after a stored run, got 0*.
    Attach the verdict's publication id on the no-op path — `publication_id=verdict.publication_id`
    in `run_record` — and step 2 fails inside PostgreSQL on the stored-has-publication CHECK.
    """
    from upto.db import dispose_all
    from upto.ingest import run_places

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    STAMP = (2026, 9, 3, 11, 0, 0)
    raw = archive_bytes(LATER_ROWS, STAMP)

    def at(hour):
        return archive(LATER_ROWS, STAMP, datetime(2026, 8, 12, hour, 0, tzinfo=TAIPEI), raw=raw)

    # The DAG sets this, and the row records it: lineage over a scheduled run and over a
    # hand-triggered one are different answers to "why does this row exist".
    previous_invoker = os.environ.get("UPTO_INVOKED_BY")
    os.environ["UPTO_INVOKED_BY"] = "airflow"
    try:
        # 1 — a stored run. The row names the publication it wrote and how many rows landed.
        stored = await run_places.ingest_once(archive=at(3), url=test_url)
        assert stored.stored and stored.parsed
        rows = await runs(Session)
        assert len(rows) == 1, "expected one run row after a stored run, got {}".format(len(rows))
        first = rows[0]
        assert first.source == fda.SOURCE, first.source
        assert first.outcome == "stored", "a run that stored must say so: {}".format(first.outcome)
        assert first.place_publication_id == stored.publication_id, (
            "D24: item 11's run points at its publication through its own column"
        )
        assert first.forecast_publication_id is None
        assert first.observation_publication_id is None
        assert first.rows_written == PLACES, "expected {}, got {}".format(PLACES, first.rows_written)
        assert first.invoked_by == "airflow", first.invoked_by
        assert first.finished_at >= first.started_at
        assert "stored" in first.detail, first.detail

        # 2 — the same bytes again: D34's ordinary day. It wrote nothing and it is still a run.
        again = await run_places.ingest_once(archive=at(4), url=test_url)
        assert not again.stored and not again.parsed
        rows = await runs(Session)
        assert len(rows) == 2, "a no-op leaves a row too, or it is inferred from an absence"
        second = rows[1]
        assert second.outcome == "no_change", (
            "a no-op is not a failure and not an absence: {}".format(second.outcome)
        )
        assert second.place_publication_id is None, (
            "the verdict names the publication still current; the row must not claim to have "
            "written it"
        )
        assert second.rows_written == 0
        assert "no change" in second.detail, second.detail

        # 3 — H14's forced re-parse. Rows were offered, none were accepted, none were written.
        forced = await run_places.ingest_once(archive=at(5), url=test_url, force_parse=True)
        assert forced.parsed and not forced.stored
        third = (await runs(Session))[2]
        assert third.outcome == "no_change", third.outcome
        assert third.rows_written == 0, "offered is not written: {}".format(third.rows_written)
        assert third.place_publication_id is None

        # 4 — the source did not answer. `failed` and `no_change` are the pair that cannot be
        # told apart once they are inferred from an absence, which is the whole of ticket 09.
        def unavailable():
            raise fda.FdaUnavailable("fda-97: the download was empty")

        real_fetch = run_places.fetch_archive
        run_places.fetch_archive = unavailable
        try:
            failed_as_expected = False
            try:
                await run_places.ingest_once(url=test_url)
            except fda.FdaUnavailable:
                failed_as_expected = True
            assert failed_as_expected, "a source that did not answer must still raise"
        finally:
            run_places.fetch_archive = real_fetch

        rows = await runs(Session)
        assert len(rows) == 4, "the failure leaves a row: {}".format(len(rows))
        fourth = rows[3]
        assert fourth.outcome == "failed", fourth.outcome
        assert fourth.place_publication_id is None
        assert fourth.rows_written == 0
        assert "the download was empty" in fourth.detail, fourth.detail
        assert fourth.source == fda.SOURCE, "a failure before the fetch still names the source"

        outcomes = [row.outcome for row in rows]
        assert outcomes == ["stored", "no_change", "no_change", "failed"], outcomes
    finally:
        if previous_invoker is None:
            os.environ.pop("UPTO_INVOKED_BY", None)
        else:
            os.environ["UPTO_INVOKED_BY"] = previous_invoker
        await engine.dispose()
        # `ingest_once` builds its engine through the module-level cache, so it outlives this
        # function and would still hold connections when the database is dropped.
        await dispose_all()
    print("ticket 09/item 11: stored, no_change, no_change and failed all leave a run row")


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""

    async def run(test_url: str, environment: dict) -> None:
        # The township reference table has to exist before a place can point at it — the
        # foreign key is D27's, and ticket 06's seed is where the twelve codes live.
        from upto.seed.township_station import load  # noqa: PLC0415

        await load(test_url)
        await scenario(test_url)
        # After the H14 scenario on purpose: it drives `ingest_archive` directly and so writes no
        # run rows at all, which leaves `ingest_run` empty for the one below to count from zero.
        await runlog_scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, run)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
