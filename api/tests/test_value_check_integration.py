#!/usr/bin/env python3
"""A28 question 1 — the value checks against a real database, as the check role.

    docker compose run --rm tests python /srv/tests/test_value_check_integration.py

Builds and drops its own database (revision 0046 applied by `alembic upgrade head`). Pins the
owner's two rulings of 2026-09-15 («A28 question 1 … the light option», «A28's checks read
through a new read-only check role»):

1. **A stale source turns the check red with one sentence naming the source and the hours** — the
   observation source's last stored publication is ten hours old against a measured interval of
   one hour, and every statement is run the way the DAG task runs it, as `upto_check`.
2. **A normal night sends nothing** — the forecast stored a partial publication (1,376 rows after
   6,720, the backtest's false-alarm shape) two hours ago with its 12 townships: no finding.
3. **A row step on a nightly source is a finding; a small one is not** (the tax registry).
4. **The nightly freshness task names the source that did not run** (60 h without a run of any
   outcome for a nightly source) and no other.
5. **The role can write `metric_history` and is refused every other write, and every read outside
   its list** — asserted by doing, with the SQLSTATE read back (42501).

Nothing here needs Airflow: the statements and the rules are `upto.checks`; the task wrapper is a
few lines of hook calls proved by `airflow tasks test` on the stack.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto import checks  # noqa: E402

TEST_DB = "upto_value_check_test"
FAILURES: list[str] = []


def check(name, condition, detail=""):
    if condition:
        print("ok   {}".format(name))
    else:
        FAILURES.append(name)
        print("FAIL {} {}".format(name, detail))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(timezone.utc)


async def run_statement(con, sql: str, source: str):
    """Run one of `upto.checks`' statements the way the task does, through the check role."""
    if ":source" in sql:
        return await con.fetchval(sql.replace(":source", "$1"), source)
    return await con.fetchval(sql)


async def read_values(con, source: str) -> dict:
    out = {}
    for metric, sql in checks.statements_for(source).items():
        value = await run_statement(con, sql, source)
        out[metric] = None if value is None else float(value)
    return out


async def sqlstate_of(coroutine) -> str | None:
    try:
        await coroutine
    except asyncpg.PostgresError as error:
        return error.sqlstate
    return None


# --- fixtures, written as the owner --------------------------------------------------------------

async def seed_run(con, source, started, outcome, **publication):
    columns = ["source", "started_at", "finished_at", "outcome", "rows_written", "invoked_by"]
    values = [source, started, started + timedelta(seconds=5), outcome, 0, "test"]
    for column, value in publication.items():
        columns.append(column)
        values.append(value)
    if outcome == "stored":
        values[4] = 1
    await con.execute(
        "insert into ingest_run ({}) values ({})".format(
            ", ".join(columns), ", ".join("${}".format(i + 1) for i in range(len(values)))),
        *values)


async def seed_observation(con, detected, rows=171, stations=19):
    pid = await con.fetchval(
        "insert into observation_publication (dataset_id, content_sha256, detected_at, payload_bytes, stored_scope) "
        "values ('O-A0001-001', $1, $2, 886000, '臺北市') returning id", sha("obs" + detected.isoformat()), detected)
    await con.executemany(
        "insert into observation_reading (publication_id, station_id, station_name, observed_at, element, value) "
        "values ($1, $2, $3, $4, $5, $6)",
        [(pid, "S{:02d}".format(i % stations), "station", detected, "E{}".format(i // stations), "1")
         for i in range(rows)])
    await seed_run(con, "O-A0001-001", detected, "stored", observation_publication_id=pid)
    return pid


async def seed_forecast(con, detected, rows, townships=12):
    pid = await con.fetchval(
        "insert into forecast_publication (dataset_id, content_sha256, detected_at, payload_bytes) "
        "values ('F-D0047-061', $1, $2, 570000) returning id", sha("fc" + detected.isoformat() + str(rows)), detected)
    await con.executemany(
        "insert into forecast_reading (publication_id, township, element, slot_start, measure, value, township_code) "
        "values ($1, $2, $3, $4, $5, $6, $7)",
        [(pid, "T{}".format(i % townships), "E{}".format(i // townships), detected + timedelta(hours=i // townships),
          "M", "1", "6300{:04d}".format(i % townships)) for i in range(rows)])
    await seed_run(con, "F-D0047-061", detected, "stored", forecast_publication_id=pid)
    return pid


async def seed_tax(con, detected, rows):
    pid = await con.fetchval(
        "insert into business_tax_publication (source, content_sha256, detected_at, payload_bytes, entry_name, entry_bytes, scope, tax_rows) "
        "values ('fia-business-tax', $1, $2, 1000, 'x.csv', 1000, '臺北市', $3) returning id",
        sha("tax" + detected.isoformat() + str(rows)), detected, rows)
    await seed_run(con, "fia-business-tax", detected, "stored", business_tax_publication_id=pid)


async def seed_status(con, detected, rows):
    pid = await con.fetchval(
        "insert into business_status_publication (source, content_sha256, detected_at, payload_bytes, scope, status_rows) "
        "values ('gcis-restaurant-registry', $1, $2, 1000, '臺北市', $3) returning id",
        sha("st" + detected.isoformat() + str(rows)), detected, rows)
    await seed_run(con, "gcis-restaurant-registry", detected, "stored", business_status_publication_id=pid)


async def scenario(owner_url: str, check_url: str) -> None:
    owner = await asyncpg.connect(owner_url)
    t = now()
    try:
        # 1. the observation source: stored ten hours ago, then nine hourly no_change runs
        await seed_observation(owner, t - timedelta(hours=10))
        for h in range(9, 0, -1):
            await seed_run(owner, "O-A0001-001", t - timedelta(hours=h), "no_change")
        # 2. the forecast: a full publication five hours ago, a partial one two hours ago
        await seed_forecast(owner, t - timedelta(hours=5), 6720)
        await seed_forecast(owner, t - timedelta(hours=2), 1376)
        await seed_run(owner, "F-D0047-061", t - timedelta(minutes=5), "no_change")
        # 3. the tax registry: two publications a day apart, −14 %; the status roster: +5 %
        await seed_tax(owner, t - timedelta(hours=26), 14000)
        await seed_tax(owner, t - timedelta(hours=2), 12000)
        await seed_status(owner, t - timedelta(hours=26), 100)
        await seed_status(owner, t - timedelta(hours=2), 105)
        # 4. a nightly source that ran once, 60 hours ago, and one that ran last night
        await seed_run(owner, "taipei-hygiene-grade", t - timedelta(hours=60), "no_change")
        await seed_run(owner, "taipei-foodtracer", t - timedelta(hours=3), "no_change")
    finally:
        await owner.close()

    role = await asyncpg.connect(check_url)
    try:
        who = await role.fetchval("select current_user")
        check("the statements run as the check role", who == "upto_check", who)

        # (1) stale
        values = await read_values(role, "O-A0001-001")
        metrics, findings = checks.evaluate("O-A0001-001", values)
        check("a stale observation source yields exactly one finding", len(findings) == 1,
              [f.sentence for f in findings])
        sentence = findings[0].sentence if findings else ""
        check("  and the sentence names the source and the hours",
              "O-A0001-001" in sentence and "10.0 h" in sentence, sentence)
        check("  while its coverage reads 171 rows / 19 stations, ok",
              {m.metric: m.verdict for m in metrics}.get("stations") == "ok"
              and {m.metric: m.verdict for m in metrics}.get("reading_rows") == "ok",
              {m.metric: (m.value, m.verdict) for m in metrics})

        # (2) a normal night on the forecast, partial publication and all
        values = await read_values(role, "F-D0047-061")
        metrics, findings = checks.evaluate("F-D0047-061", values)
        check("a partial forecast publication two hours old is no finding", findings == [],
              [f.sentence for f in findings])
        check("  its raw row count is recorded without a line",
              any(m.metric == "reading_rows" and m.verdict == "recorded" and m.value == 1376 and m.threshold is None
                  for m in metrics), [(m.metric, m.value, m.verdict) for m in metrics])
        check("  and its 12 townships read ok",
              any(m.metric == "townships" and m.verdict == "ok" and m.value == 12 for m in metrics))

        # (3) row steps on the nightly sources
        values = await read_values(role, "fia-business-tax")
        _, findings = checks.evaluate("fia-business-tax", values)
        check("a −14 % step on the tax registry is one finding naming it",
              len(findings) == 1 and "fia-business-tax" in findings[0].sentence and "-14.3%" in findings[0].sentence,
              [f.sentence for f in findings])
        values = await read_values(role, "gcis-restaurant-registry")
        _, findings = checks.evaluate("gcis-restaurant-registry", values)
        check("a +5 % step on the status roster is not", findings == [], [f.sentence for f in findings])

        # (4) the nightly freshness sweep
        rows = [(source, None if hours is None else float(hours))
                for source, hours in await role.fetch(checks.FRESHNESS_SQL)]
        metrics, findings = checks.freshness(rows)
        check("the freshness sweep names the source that has not run for 60 h and no other",
              [f.source for f in findings] == ["taipei-hygiene-grade"] and "60.0 h" in findings[0].sentence,
              [f.sentence for f in findings])
        check("  and records one row per source the module knows",
              sorted(m.source for m in metrics) == sorted(checks.SOURCES))

        # (5) the role writes metric_history and nothing else
        insert = checks.INSERT_METRIC
        for i, name in enumerate(("source", "metric", "observed_at", "publication_id", "value", "threshold", "verdict", "detail"), 1):
            insert = insert.replace(":" + name, "${}".format(i))
        params = checks.insert_params(metrics[0], t)
        await role.execute(insert, *[params[k] for k in ("source", "metric", "observed_at", "publication_id", "value", "threshold", "verdict", "detail")])
        stored = await role.fetchval("select count(*) from metric_history")
        check("the check role inserts into metric_history and reads it back", stored == 1, stored)

        refusals = {
            "insert into ingest_run": role.execute(
                "insert into ingest_run (source, started_at, finished_at, outcome) values ('x', now(), now(), 'failed')"),
            "update metric_history": role.execute("update metric_history set verdict = 'ok'"),
            "delete from metric_history": role.execute("delete from metric_history"),
            "insert into forecast_publication": role.execute(
                "insert into forecast_publication (dataset_id, content_sha256, detected_at, payload_bytes) values ('x', repeat('0', 64), now(), 1)"),
            "select from member": role.fetch("select * from member"),
            "select from preference": role.fetch("select * from preference"),
            "select from place": role.fetch("select * from place"),
            "select from reference_place": role.fetch("select * from reference_place"),
            "delete from observation_reading": role.execute("delete from observation_reading"),
        }
        for what, coroutine in refusals.items():
            state = await sqlstate_of(coroutine)
            check("upto_check is refused: {} (42501)".format(what), state == "42501", state)
        # a refusal inside a transaction must not poison the connection for the next read
        still = await role.fetchval("select count(*) from ingest_run")
        check("and can still read the ledger afterwards", still and still > 0, still)
    finally:
        await role.close()


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"].replace("+asyncpg", "")
    check_live = os.environ.get("UPTO_CHECK_DATABASE_URL", "").replace("+asyncpg", "")
    if not check_live:
        print("UPTO_CHECK_DATABASE_URL is not set in this container — the tests service carries it since A28; "
              "nothing checked", file=sys.stderr)
        return 2
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    check_head, _, _ = check_live.rpartition("/")
    check_url = check_head + "/" + TEST_DB
    admin = await asyncpg.connect(admin_url)
    await admin.execute('drop database if exists "{}" with (force)'.format(TEST_DB))
    await admin.execute('create database "{}"'.format(TEST_DB))
    await admin.close()
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url.replace("postgresql://", "postgresql+asyncpg://"))
        migrate = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv", env=environment,
                                 capture_output=True, text=True)
        if migrate.returncode != 0:
            print(migrate.stderr[-2000:], file=sys.stderr)
            return 2
        await scenario(test_url, check_url)
    finally:
        admin = await asyncpg.connect(admin_url)
        await admin.execute('drop database if exists "{}" with (force)'.format(TEST_DB))
        await admin.close()
    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("\nA28 question 1: a stale source is one red task with one sentence naming it and the hours, a "
          "normal night stays green, the forecast's partial publication is ordinary, and upto_check writes "
          "metric_history and nothing else")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
