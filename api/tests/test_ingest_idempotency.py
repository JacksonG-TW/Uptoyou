#!/usr/bin/env python3
"""M1 — **idempotency of every ingest source**, measured rather than assumed.

Run inside the stack:
    docker compose exec api python /srv/tests/test_ingest_idempotency.py

The test builds its own database and drops it, so it never touches the stack's data.

**The claim under measurement.** Running the same source file twice leaves a *byte-identical*
database: the same rows in every table the source writes, the same publication row, no
duplicated `*_row`, and an `ingest_run` ledger that says `stored` once and `no_change`
afterwards. Then the stronger form: a **third** run with `--force-parse`, which disables the
hash short-circuit and re-parses and re-offers every row, must also change nothing — so what
refuses the duplicate is the database's own key rather than the runner declining to write.

**Why byte-identity rather than counts.** The sibling integration tests assert row counts and
named columns, which is a strictly weaker claim: a re-run that rewrote a name, moved a
`detected_at`, or renumbered a publication would pass all of them. Here every column of every
table the source writes is dumped, ordered totally, and hashed. **Nothing is excluded** —
`detected_at`, `id`, the count columns and the hashes are all compared as they stand, because
a no-op inserts no row and therefore has nothing legitimate to vary. If that ever stops being
true the exclusion has to be argued in this docstring, not quietly added to a list.

`ingest_run` is the one table left out of the dumps, and only because it is *supposed* to grow:
every run appends a row by design (ticket 09). It is checked separately and just as tightly —
the outcome sequence, one appended row per run, and no publication attached to a no-op.

**The CLI-versus-DAG entry.** `name_reference_ingests.py` runs the same module with
`UPTO_INVOKED_BY=airflow` and nothing else changed. A fourth run sets that variable, and the
two `no_change` ledger rows are compared column by column: `invoked_by` must be the only
difference once the per-run identity (`id`) and the two timestamps are set aside. Those three
are excluded from *that* comparison alone, and each is a different value per run by definition
— a sequence and two clock readings — so requiring them equal would be requiring the clock to
stand still.

**Coverage.** Five sources run through their real `python -m …` entry point in a subprocess,
because that is what a scheduler calls and an exit code is only real at a process boundary:

    upto.ingest.run_places            item 11, FDA places (zip)
    upto.ingest.run_brands            D77, brands (CSV)
    upto.ingest.run_storefronts       D78, storefronts (CSV)
    upto.ingest.run_business_status   D81, registry status (CSV)
    upto.ingest.run_business_tax      D85, tax registry (zip)

They share one scratch database and run in that order on purpose: D85's filter reads the 統編
of the latest `place_publication`, so item 11 seeds it for real instead of by hand.

**The weather source (`upto.ingest.run`) is covered offline and differently, and the difference
is stated rather than hidden.** It has no `--file`: `ingest_once` fetches from CWA with a key,
so a subprocess run would need the network and `~/.keys/cwa_api_key`. Instead the module's
`fetch_publication` is replaced in-process with a recorded fixture, which exercises the real
store, the real ledger mapping and the real `invoked_by` handling — everything except the HTTP
call and the JSON parse. It also has no `--force-parse` flag, and could not use one: the parse
happens *before* the claim, so an unchanged run already re-parses and the flag would gate
nothing. Its stronger form is done by hand instead — `store.py`'s own reading-insert statements
are replayed against the held publication with identical rows, which is precisely the
re-offer `--force-parse` produces elsewhere.
"""

import asyncio
import hashlib
import io
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_idempotency_check"
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
TAIPEI = timezone(timedelta(hours=8))

# The three columns set aside in the CLI-versus-airflow ledger comparison, and nowhere else.
# `id` is a sequence; the two stamps are clock readings taken by the run itself. Requiring any
# of the three equal across two runs would be requiring time not to pass.
PER_RUN_LEDGER_COLUMNS = ("id", "started_at", "finished_at")


# --------------------------------------------------------------------------------------
# Fixtures. Small on purpose — the claim is about the database's behaviour under a repeat,
# and 36,000 rows demonstrate it no better than three.
# --------------------------------------------------------------------------------------

FDA_HEADER = "公司或商業登記名稱,公司統一編號,業者地址,食品業者登錄字號,登錄項目"
FDA_ROWS = [
    '"福利麵包食品有限公司","11820764","台北市信義區菸廠路88號B1","A-111820764-00022-1","餐飲場所"',
    '"全家便利商店股份有限公司","23060248","臺北市中正區忠孝西路一段４９號Ｂ１","A-123060248-13440-5","餐飲場所"',
    # H25: a fixture with no defect never reaches the code that cleans one. This address
    # resolves to no township, so the unresolved count is non-zero and gets compared too.
    '"某小吃店","20003433","台北市長安東路一段58號","A-200034336-00001-9","餐飲場所"',
]
# The 統編 item 11 will have stored, and therefore the only ones D85 is allowed to keep.
REFERENCE_NOS = ("11820764", "23060248", "20003433")

BRAND_HEADER = "行政區域代碼,公司名稱,品牌名稱,產品名稱,原料名稱,原料品牌,每一份量,熱量大卡,相關資訊連結"
GRADE_HEADER = "行政區域代碼,業者名稱店名,食品業者登錄字號,地址,評核結果"
STATUS_HEADER = '"統一編號","商業名稱","商業地址","登記狀態","備註"'

TAX_STAMP = "14-AUG-26"
TAX_HEADER = (
    "營業地址,統一編號,總機構統一編號,營業人名稱,資本額,設立日期,組織別名稱,使用統一發票,"
    "行業代號,名稱,行業代號1,名稱1,行業代號2,名稱2,行業代號3,名稱3"
)


def fda_zip() -> bytes:
    body = "\r\n".join([FDA_HEADER] + FDA_ROWS) + "\r\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(
            zipfile.ZipInfo("97_2.csv", date_time=(2026, 8, 1, 3, 30, 2)),
            b"\xef\xbb\xbf" + body.encode("utf-8"),
        )
    return buffer.getvalue()


def brand_csv() -> bytes:
    # The pair for 摩斯 repeats, because the real file is product-level: the dedup happens in
    # the parse, and a repeat that reached the database twice would show up as a diff.
    pairs = [
        ("安心食品服務股份有限公司", "摩斯漢堡"),
        ("安心食品服務股份有限公司", "摩斯漢堡"),
        ("頂呱呱國際股份有限公司", "頂呱呱"),
        ("頂呱呱國際股份有限公司", "東京油組"),
    ]
    lines = [BRAND_HEADER] + [
        "63000000,{},{},產品,原料,牌,100g,200,https://example.invalid".format(company, brand)
        for company, brand in pairs
    ]
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


def grade_csv() -> bytes:
    rows = [("福利麵包 信義店", "A-111820764-00022-1"), ("某小吃店", "A-200034336-00001-9")]
    lines = [GRADE_HEADER] + [
        "63000010,{},{},臺北市某路1號,優".format(name, registry) for name, registry in rows
    ]
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


def status_csv() -> bytes:
    # The third row carries an empty 登記狀態, which the measured file does: it is part of the
    # ON CONFLICT key, and an empty string is not NULL — which is what makes the key work.
    rows = [
        ("11820764", "福利麵包食品有限公司", "核准設立"),
        ("20003433", "某小吃店", "歇業"),
        ("23060248", "全家便利商店股份有限公司", ""),
    ]
    lines = [STATUS_HEADER] + [
        '"{}","{}","x","{}",""'.format(number, name, status) for number, name, status in rows
    ]
    return ("﻿" + "\n".join(lines) + "\n").encode("utf-8")


def tax_row(business_no, name, address, industries):
    cells = [
        '"{}"'.format(address), business_no, "", '"{}"'.format(name),
        "100000", "1040413", "獨資", "N",
    ]
    for code, industry_name in list(industries) + [("", "")] * (4 - len(industries)):
        cells.extend([code, industry_name])
    return ",".join(cells)


def tax_zip() -> bytes:
    rows = [
        tax_row(REFERENCE_NOS[0], "福利麵包食品有限公司", "臺北市信義區菸廠路88號B1",
                (("562100", "餐館"),)),
        tax_row(REFERENCE_NOS[1], "全家便利商店股份有限公司", "臺北市中正區忠孝西路一段49號B1",
                (("472913", "菸酒零售"), ("471913", "雜貨店"), ("562100", "餐館"))),
        tax_row(REFERENCE_NOS[2], "某小吃店", "臺北市中山區長安東路一段58號",
                (("562100", "餐館"),)),
        # In the file and in no publication of ours — the shape of 1.69M of its rows.
        tax_row("82554400", "啟輝環管企業社", "南投縣中寮鄉永平路51之1號", (("812100", "清潔服務"),)),
    ]
    body = ("﻿" + "\n".join([TAX_HEADER, TAX_STAMP + "," * 15] + rows) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            zipfile.ZipInfo("BGMOPEN1.csv", date_time=(2026, 8, 14, 3, 30, 2)), body
        )
    return buffer.getvalue()


# `tables` is every table the source writes. The publication comes first so a diff report
# reads top-down. `ingest_run` is deliberately absent — it is meant to grow.
SOURCES = (
    {
        "name": "item 11 FDA places",
        "module": "upto.ingest.run_places",
        "source": "fda-97",
        "suffix": ".zip",
        "fixture": fda_zip,
        "tables": ("place_publication", "reference_place"),
    },
    {
        "name": "D77 brands",
        "module": "upto.ingest.run_brands",
        "source": "taipei-foodtracer",
        "suffix": ".csv",
        "fixture": brand_csv,
        "tables": ("brand_publication", "brand_registration"),
    },
    {
        "name": "D78 storefronts",
        "module": "upto.ingest.run_storefronts",
        "source": "taipei-hygiene-grade",
        "suffix": ".csv",
        "fixture": grade_csv,
        "tables": ("storefront_publication", "storefront_name"),
    },
    {
        "name": "D81 business status",
        "module": "upto.ingest.run_business_status",
        "source": "gcis-restaurant-registry",
        "suffix": ".csv",
        "fixture": status_csv,
        "tables": ("business_status_publication", "business_status_row"),
    },
    {
        "name": "D85 tax registry",
        "module": "upto.ingest.run_business_tax",
        "source": "fia-business-tax",
        "suffix": ".zip",
        "fixture": tax_zip,
        "tables": ("business_tax_publication", "business_tax_row"),
    },
)


# --------------------------------------------------------------------------------------
# The instrument: a total, column-complete dump of a table, hashed.
# --------------------------------------------------------------------------------------

async def columns_of(Session, table):
    async with Session() as session:
        result = await session.execute(
            text(
                "select column_name from information_schema.columns "
                "where table_schema = 'public' and table_name = :t order by ordinal_position"
            ),
            {"t": table},
        )
        names = [row[0] for row in result.fetchall()]
    assert names, "table {} does not exist — the dump would silently compare nothing".format(table)
    return names


async def dump(Session, table):
    """Every column of every row, ordered by every column. No sampling, no projection.

    `order by 1, 2, … n` is a total order over the whole row, so the dump does not depend on
    knowing the primary key and cannot be reordered by a rewrite that happens to preserve
    content — which a `select *` with no order by can.
    """
    names = await columns_of(Session, table)
    quoted = ", ".join('"{}"'.format(name) for name in names)
    ordering = ", ".join(str(index + 1) for index in range(len(names)))
    async with Session() as session:
        result = await session.execute(
            text("select {} from {} order by {}".format(quoted, table, ordering))
        )
        rows = [tuple(repr(cell) for cell in row) for row in result.fetchall()]
    return names, rows


async def snapshot(Session, tables):
    return {table: await dump(Session, table) for table in tables}


def digest(shot):
    hasher = hashlib.sha256()
    for table in sorted(shot):
        names, rows = shot[table]
        hasher.update(("\x00".join([table] + names) + "\x01").encode("utf-8"))
        for row in rows:
            hasher.update(("\x00".join(row) + "\x01").encode("utf-8"))
    return hasher.hexdigest()


def first_difference(before, after):
    """The first differing row pair, as a printable report. `None` when the two agree."""
    for table in sorted(set(before) | set(after)):
        names_a, rows_a = before.get(table, ([], []))
        names_b, rows_b = after.get(table, ([], []))
        if names_a != names_b:
            return "{}: the column list changed\n  before {}\n  after  {}".format(
                table, names_a, names_b
            )
        for index in range(max(len(rows_a), len(rows_b))):
            row_a = rows_a[index] if index < len(rows_a) else None
            row_b = rows_b[index] if index < len(rows_b) else None
            if row_a == row_b:
                continue
            lines = [
                "{}: row {} of {} differs (before {} rows, after {} rows)".format(
                    table, index, len(names_a), len(rows_a), len(rows_b)
                )
            ]
            if row_a is None:
                lines.append("  before  <absent — the re-run APPENDED a row>")
                lines.append("  after   " + " | ".join(row_b))
            elif row_b is None:
                lines.append("  before  " + " | ".join(row_a))
                lines.append("  after   <absent — the re-run DELETED a row>")
            else:
                for name, cell_a, cell_b in zip(names_a, row_a, row_b):
                    if cell_a != cell_b:
                        lines.append("  {}: {}  ->  {}".format(name, cell_a, cell_b))
            return "\n".join(lines)
    return None


def assert_identical(label, before, after):
    report = first_difference(before, after)
    assert report is None, "{}\n{}".format(label, report)


# --------------------------------------------------------------------------------------
# The ledger, read whole so the comparison can be column-by-column.
# --------------------------------------------------------------------------------------

async def ledger(Session, source):
    names = await columns_of(Session, "ingest_run")
    quoted = ", ".join('"{}"'.format(name) for name in names)
    async with Session() as session:
        result = await session.execute(
            text("select {} from ingest_run where source = :s order by id".format(quoted)),
            {"s": source},
        )
        rows = [dict(zip(names, row)) for row in result.fetchall()]
    return names, rows


def ledger_difference(names, cli_row, airflow_row):
    """Which columns differ, once the per-run identity and the two clock readings are set aside."""
    return {
        name: (cli_row[name], airflow_row[name])
        for name in names
        if name not in PER_RUN_LEDGER_COLUMNS and cli_row[name] != airflow_row[name]
    }


def cli(module, arguments, test_url, invoked_by=None):
    """One real run of the module a scheduler calls, at a real process boundary."""
    environment = dict(
        os.environ,
        UPTO_DATABASE_URL=test_url,
        PYTHONPATH=SRC + os.pathsep + os.environ.get("PYTHONPATH", ""),
    )
    if invoked_by is None:
        # The plain CLI path: the module must default to "cli" on its own.
        environment.pop("UPTO_INVOKED_BY", None)
    else:
        environment["UPTO_INVOKED_BY"] = invoked_by
    started = time.perf_counter()
    finished = subprocess.run(
        [sys.executable, "-m", module] + arguments,
        env=environment,
        capture_output=True,
        text=True,
    )
    return finished, time.perf_counter() - started


# --------------------------------------------------------------------------------------
# One source, four runs.
# --------------------------------------------------------------------------------------

async def measure_file_source(Session, spec, test_url, results):
    name, module, source = spec["name"], spec["module"], spec["source"]
    tables = spec["tables"]

    handle = tempfile.NamedTemporaryFile(suffix=spec["suffix"], delete=False)
    handle.write(spec["fixture"]())
    handle.close()
    path = handle.name

    row = {"name": name, "seconds": 0.0}
    try:
        # 1 — the first run stores.
        first, seconds = cli(module, ["--file", path], test_url)
        row["seconds"] += seconds
        assert first.returncode == 0, "{} run 1 exited {}\n{}\n{}".format(
            name, first.returncode, first.stdout, first.stderr
        )
        _, runs = await ledger(Session, source)
        assert [entry["outcome"] for entry in runs] == ["stored"], (
            "{}: the first run must be `stored`, the ledger says {}".format(
                name, [entry["outcome"] for entry in runs]
            )
        )
        after_first = await snapshot(Session, tables)
        assert any(rows for _, rows in after_first.values()), (
            "{}: the first run wrote nothing, so there is no idempotency to measure".format(name)
        )

        # 2 — the same bytes again. Nothing written, and the database must not have moved.
        second, seconds = cli(module, ["--file", path], test_url)
        row["seconds"] += seconds
        assert second.returncode == 0, "{} run 2 exited {}\n{}\n{}".format(
            name, second.returncode, second.stdout, second.stderr
        )
        _, runs = await ledger(Session, source)
        assert len(runs) == 2, (
            "{}: run 2 appended {} ledger rows, expected exactly one".format(name, len(runs) - 1)
        )
        assert runs[1]["outcome"] == "no_change", (
            "{}: run 2 recorded {!r}, not `no_change`".format(name, runs[1]["outcome"])
        )
        assert runs[1]["rows_written"] == 0, "{}: a no-op reported rows written".format(name)
        after_second = await snapshot(Session, tables)
        assert_identical(
            "{}: the second run on identical bytes changed the database".format(name),
            after_first, after_second,
        )
        row["run2"] = True
        row["no_change"] = True

        # 3 — the short-circuit disabled: every row is re-parsed and re-offered, and the
        # database's own key is what refuses it.
        forced, seconds = cli(module, ["--file", path, "--force-parse"], test_url)
        row["seconds"] += seconds
        assert forced.returncode == 0, "{} run 3 (--force-parse) exited {}\n{}\n{}".format(
            name, forced.returncode, forced.stdout, forced.stderr
        )
        assert "re-parsed into" in forced.stdout, (
            "{}: --force-parse did not re-parse, so this run proves nothing:\n{}".format(
                name, forced.stdout
            )
        )
        _, runs = await ledger(Session, source)
        assert runs[2]["outcome"] == "no_change", (
            "{}: a forced re-parse recorded {!r}".format(name, runs[2]["outcome"])
        )
        after_forced = await snapshot(Session, tables)
        assert_identical(
            "{}: a forced re-parse of identical bytes changed the database".format(name),
            after_first, after_forced,
        )
        row["forced"] = True

        # 4 — the DAG's entry: the same module, `UPTO_INVOKED_BY=airflow`, nothing else.
        as_dag, seconds = cli(module, ["--file", path], test_url, invoked_by="airflow")
        row["seconds"] += seconds
        assert as_dag.returncode == 0, "{} run 4 (airflow) exited {}\n{}\n{}".format(
            name, as_dag.returncode, as_dag.stdout, as_dag.stderr
        )
        names, runs = await ledger(Session, source)
        assert len(runs) == 4, "{}: expected four ledger rows, found {}".format(name, len(runs))
        assert runs[1]["invoked_by"] == "cli", (
            "{}: the plain CLI run recorded {!r} — the default is the claim under test".format(
                name, runs[1]["invoked_by"]
            )
        )
        assert runs[3]["invoked_by"] == "airflow", (
            "{}: the DAG-shaped run recorded {!r}".format(name, runs[3]["invoked_by"])
        )
        differing = ledger_difference(names, runs[1], runs[3])
        assert set(differing) == {"invoked_by"}, (
            "{}: a CLI and an airflow run differ in more than `invoked_by`: {}".format(
                name, differing
            )
        )
        row["invoker"] = True
        after_dag = await snapshot(Session, tables)
        assert_identical(
            "{}: the airflow-invoked re-run changed the database".format(name),
            after_first, after_dag,
        )
    finally:
        os.unlink(path)
    results.append(row)


# --------------------------------------------------------------------------------------
# The weather source, offline. Stated limits are in the module docstring.
# --------------------------------------------------------------------------------------

FORECAST_HOUR = datetime(2026, 8, 11, 19, 0, tzinfo=TAIPEI)


def weather_fixtures():
    from upto.ingest.cwa import (  # noqa: PLC0415
        FORECAST_DATASET,
        OBSERVATION_DATASET,
        ForecastRow,
        ObservationRow,
        Publication,
    )

    forecast = Publication(
        dataset_id=FORECAST_DATASET,
        content_sha256="c" * 64,
        detected_at=datetime(2026, 8, 11, 17, 5, tzinfo=TAIPEI),
        payload_bytes=2048,
        forecast_rows=[
            ForecastRow(
                township_code="63000040", township="中山區", element="溫度",
                measure="Temperature", slot_start=FORECAST_HOUR,
                slot_end=FORECAST_HOUR + timedelta(hours=1), value="32",
            ),
            ForecastRow(
                township_code="63000040", township="中山區", element="3小時降雨機率",
                measure="ProbabilityOfPrecipitation", slot_start=FORECAST_HOUR,
                slot_end=FORECAST_HOUR + timedelta(hours=3), value="20",
            ),
        ],
    )
    observation = Publication(
        dataset_id=OBSERVATION_DATASET,
        content_sha256="d" * 64,
        detected_at=datetime(2026, 8, 11, 17, 6, tzinfo=TAIPEI),
        payload_bytes=4096,
        observation_rows=[
            ObservationRow(
                station_id="C0A980", station_name="測試站", county="臺北市", town="中山區",
                town_code="63000040", observed_at=FORECAST_HOUR, element="溫度", value="31.4",
            ),
            # A row whose optional fields are absent, so the NULL-carrying shape is compared too.
            # Its county is 臺北市 since A18 (2026-08-28): the store keeps that county's stations
            # and drops the rest, so a `county=None` row is never stored — and a replay that
            # re-offered it anyway read as «the re-run APPENDED a row» for a week.
            ObservationRow(
                station_id="C0A981", station_name="無鎮站", county="臺北市", town=None,
                town_code=None, observed_at=FORECAST_HOUR, element="溫度", value=None,
            ),
        ],
    )
    return {FORECAST_DATASET: forecast, OBSERVATION_DATASET: observation}


async def replay_readings(Session, fixtures):
    """`--force-parse`'s analogue: re-offer every reading against the publication already held.

    The weather runner has no such flag and needs none — its parse happens before the claim,
    so an unchanged run already re-parses. What it never does is re-offer the rows, and that
    is the half a duplicate would appear in, so it is done here with `store.py`'s own
    statements rather than a paraphrase of them.
    """
    from upto.ingest.cwa import FORECAST_DATASET, in_stored_scope  # noqa: PLC0415
    from upto.ingest.store import (  # noqa: PLC0415
        INSERT_FORECAST_READING,
        INSERT_OBSERVATION_READING,
    )

    for dataset_id, publication in fixtures.items():
        forecast = dataset_id == FORECAST_DATASET
        table = "forecast_publication" if forecast else "observation_publication"
        async with Session() as session:
            publication_id = (
                await session.execute(
                    text(
                        "select id from {} where dataset_id = :d and content_sha256 = :h".format(
                            table
                        )
                    ),
                    {"d": dataset_id, "h": publication.content_sha256},
                )
            ).scalar_one()
            if forecast:
                batch = [
                    {
                        "publication_id": publication_id,
                        "township_code": row.township_code, "township": row.township,
                        "element": row.element, "measure": row.measure,
                        "slot_start": row.slot_start, "slot_end": row.slot_end,
                        "value": row.value,
                    }
                    for row in publication.forecast_rows
                ]
                await session.execute(text(INSERT_FORECAST_READING), batch)
            else:
                batch = [
                    {
                        "publication_id": publication_id,
                        "station_id": row.station_id, "station_name": row.station_name,
                        "county": row.county, "town": row.town, "town_code": row.town_code,
                        "observed_at": row.observed_at, "element": row.element,
                        "value": row.value,
                    }
                    # The store's own scope rule (A18), by its own function — re-offering a row
                    # the store would never have stored tests the fixture, not the database.
                    for row in publication.observation_rows
                    if in_stored_scope(row.county)
                ]
                await session.execute(text(INSERT_OBSERVATION_READING), batch)
            await session.commit()


async def measure_weather(Session, test_url, results):
    import upto.ingest.run as runner  # noqa: PLC0415
    from upto.ingest.cwa import FORECAST_DATASET, OBSERVATION_DATASET  # noqa: PLC0415

    tables = (
        "forecast_publication", "forecast_reading",
        "observation_publication", "observation_reading",
    )
    fixtures = weather_fixtures()
    real_fetch = runner.fetch_publication
    previous_key = os.environ.get(runner.KEY_VAR)
    previous_invoker = os.environ.get("UPTO_INVOKED_BY")
    # The key is never used: the fetch is replaced. It is set because the runner refuses to
    # start without one, and that refusal is correct and not what is being measured.
    os.environ[runner.KEY_VAR] = "fixture-run-no-network"
    os.environ.pop("UPTO_INVOKED_BY", None)
    runner.fetch_publication = lambda dataset_id, key: fixtures[dataset_id]

    row = {"name": "CWA weather (offline fixture)", "seconds": 0.0}
    try:
        started = time.perf_counter()
        assert await runner.ingest_once() == 0, "the first weather run reported a failure"
        row["seconds"] += time.perf_counter() - started
        after_first = await snapshot(Session, tables)
        for dataset_id in (FORECAST_DATASET, OBSERVATION_DATASET):
            _, runs = await ledger(Session, dataset_id)
            assert [entry["outcome"] for entry in runs] == ["stored"], (
                "weather {}: the first run says {}".format(
                    dataset_id, [entry["outcome"] for entry in runs]
                )
            )

        started = time.perf_counter()
        assert await runner.ingest_once() == 0, "the second weather run reported a failure"
        row["seconds"] += time.perf_counter() - started
        after_second = await snapshot(Session, tables)
        assert_identical(
            "weather: the second run on identical content changed the database",
            after_first, after_second,
        )
        row["run2"] = True
        for dataset_id in (FORECAST_DATASET, OBSERVATION_DATASET):
            names, runs = await ledger(Session, dataset_id)
            assert len(runs) == 2, "weather {}: {} ledger rows".format(dataset_id, len(runs))
            assert runs[1]["outcome"] == "no_change", (
                "weather {}: run 2 recorded {!r}".format(dataset_id, runs[1]["outcome"])
            )
            assert runs[1]["place_publication_id"] is None
        row["no_change"] = True

        started = time.perf_counter()
        await replay_readings(Session, fixtures)
        row["seconds"] += time.perf_counter() - started
        after_replay = await snapshot(Session, tables)
        assert_identical(
            "weather: re-offering every reading against the held publication wrote a duplicate",
            after_first, after_replay,
        )
        row["forced"] = True

        os.environ["UPTO_INVOKED_BY"] = "airflow"
        started = time.perf_counter()
        assert await runner.ingest_once() == 0
        row["seconds"] += time.perf_counter() - started
        after_dag = await snapshot(Session, tables)
        assert_identical(
            "weather: the airflow-invoked re-run changed the database", after_first, after_dag
        )
        for dataset_id in (FORECAST_DATASET, OBSERVATION_DATASET):
            names, runs = await ledger(Session, dataset_id)
            assert runs[1]["invoked_by"] == "cli", (
                "weather {}: the plain run recorded {!r}".format(
                    dataset_id, runs[1]["invoked_by"]
                )
            )
            assert runs[2]["invoked_by"] == "airflow"
            differing = ledger_difference(names, runs[1], runs[2])
            assert set(differing) == {"invoked_by"}, (
                "weather {}: a CLI and an airflow run differ in more than `invoked_by`: "
                "{}".format(dataset_id, differing)
            )
        row["invoker"] = True
    finally:
        runner.fetch_publication = real_fetch
        if previous_key is None:
            os.environ.pop(runner.KEY_VAR, None)
        else:
            os.environ[runner.KEY_VAR] = previous_key
        if previous_invoker is None:
            os.environ.pop("UPTO_INVOKED_BY", None)
        else:
            os.environ["UPTO_INVOKED_BY"] = previous_invoker
    results.append(row)


# --------------------------------------------------------------------------------------

def mark(row, key):
    return "yes" if row.get(key) else "NO"


def report(results):
    header = ("source", "run2 identical", "force-parse identical", "ingest_run no_change",
              "airflow diff = invoked_by only", "seconds")
    body = [
        (
            row["name"], mark(row, "run2"), mark(row, "forced"), mark(row, "no_change"),
            mark(row, "invoker"), "{:.2f}".format(row["seconds"]),
        )
        for row in results
    ]
    widths = [max(len(line[index]) for line in [header] + body) for index in range(len(header))]
    rule = "  ".join("-" * width for width in widths)
    print()
    print("M1 — idempotency of every ingest source")
    print(rule)
    print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(header)))
    print(rule)
    for line in body:
        print("  ".join(cell.ljust(widths[index]) for index, cell in enumerate(line)))
    print(rule)


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    results = []
    try:
        # Item 11 first: D85's filter reads the 統編 of the latest place publication, so the
        # reference list is seeded by the source that owns it rather than by hand.
        for spec in SOURCES:
            await measure_file_source(Session, spec, test_url, results)
        await measure_weather(Session, test_url, results)
    finally:
        report(results)
        await engine.dispose()
        from upto.db import dispose_all  # noqa: PLC0415

        await dispose_all()
    print()
    print(
        "M1: every source is idempotent on identical bytes — the re-run leaves every column of "
        "every table it writes untouched, a forced re-parse re-offers every row and the "
        "database's own key refuses all of them, the ledger says `stored` once and `no_change` "
        "after, and a DAG-shaped run differs from a CLI one in `invoked_by` and nothing else"
    )


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}" with (force)'.format(TEST_DB)))
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
        # A place points at its township through D27's foreign key, so the twelve codes have to
        # be present before item 11 writes a row. Ticket 06's seed is where they live.
        from upto.seed.township_station import load  # noqa: PLC0415

        await load(test_url)
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
