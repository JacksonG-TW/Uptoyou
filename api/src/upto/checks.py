"""A28 question 1 — value-level checks on what the ingests store, as pure rules over a few numbers.

*Owner-ruled 2026-09-15 (decision-log «A28 question 1, value-level anomaly checks — the light
option» and «A28's checks read through a new read-only check role»).*

**What this module is.** The statements a check runs and the rules it applies, with no Airflow in
them, so the rules are testable host-side and the same rules are asserted against a real database in
`tests/test_value_check_integration.py`. `airflow/dags/_value_check.py` is the thin task that runs
these statements through `PostgresHook` as `upto_check`, writes the metrics to `metric_history`, and
raises on a finding — which is what turns a finding into one A10 message.

**Every threshold here is a named constant measured from the data, with its source line, and none
follows the data live.** A threshold that moves with a stale source is no threshold: the median
publication interval of a source that has stopped publishing grows with every night it is silent,
and a live median would quietly raise its own line. The numbers are the ones
`probes/a28-backtest.md` measured on 2026-09-15 over 1,862 runs; when a source's habit changes, the
constant is re-measured and edited here, and the edit says why.

**What is deliberately NOT a rule.** The forecast's raw row count. CWA republishes partial slot
sets — 6,720 rows on 146 of 214 publications, 1,376–6,608 on the rest — and a threshold on that
count fired 60–90 times in 35 days in the backtest, every one false. The forecast is checked on its
freshness and its coverage (12 townships on every publication), never on its rows.

**A `failed` run is A10's alert, not this module's.** It is recorded as a metric (how many in the
last 24 h) so a reader can see it beside the rest; raising on it here would turn one failure into
two messages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# --- the sources, as the ledger names them ------------------------------------------------------

#: Hours between two runs of the source's DAG. The hourly pair runs `@hourly`; every other source
#: runs once a night. SILENT fires at 2 × this — the same line the backtest used (two true events
#: in 35 days, both on the stack's first evening).
RUN_CADENCE_H: dict[str, float] = {
    "F-D0047-061": 1.0,
    "O-A0001-001": 1.0,
    "fda-97": 24.0,
    "taipei-foodtracer": 24.0,
    "taipei-hygiene-grade": 24.0,
    "gcis-restaurant-registry": 24.0,
    "fia-business-tax": 24.0,
}

#: The median hours between two STORED publications of the source, measured on 2026-09-15 over
#: every publication since 2026-08-11 (`probes/a28-backtest.md`, «Median inter-publication interval
#: per source»). `None` where the source has published once, so no interval exists to measure —
#: the metric is still recorded, and no line is drawn until there is one. STALE fires at
#: `STALE_FACTOR` × this.
PUBLICATION_INTERVAL_H: dict[str, float | None] = {
    "F-D0047-061": 4.0,        # 214 publications; CWA republishes about four times a day
    "O-A0001-001": 1.0,        # 841 publications, one an hour, no exception measured
    "fda-97": 523.0,           # two publications, 2026-08-11 and 2026-09-02 (the place file)
    "taipei-foodtracer": None,  # one publication since 2026-08-14 (brands)
    "taipei-hygiene-grade": None,  # one publication since 2026-08-14 (storefronts)
    "gcis-restaurant-registry": 449.7,  # two publications, ~monthly roster
    "fia-business-tax": 24.0,  # 32 publications in 32 nights
}

#: The publication table, its row-count column and the ledger's foreign-key column, per source —
#: the same map `airflow/dags/_publication_check.py` keeps for A9, plus the two weather sources
#: A9 does not check.
PUBLICATIONS: dict[str, tuple[str, str, str]] = {
    "F-D0047-061": ("forecast_publication", "payload_bytes", "forecast_publication_id"),
    "O-A0001-001": ("observation_publication", "payload_bytes", "observation_publication_id"),
    "fda-97": ("place_publication", "place_rows", "place_publication_id"),
    "taipei-foodtracer": ("brand_publication", "pair_rows", "brand_publication_id"),
    "taipei-hygiene-grade": ("storefront_publication", "name_rows", "storefront_publication_id"),
    "gcis-restaurant-registry": ("business_status_publication", "status_rows", "business_status_publication_id"),
    "fia-business-tax": ("business_tax_publication", "tax_rows", "business_tax_publication_id"),
}

#: The five nightly sources whose stored row count is compared with the previous publication's.
#: A9 fails on a ≥ 20 % DROP; this records the step either way and alerts at `ROW_STEP` in either
#: direction. The weather sources are absent on purpose (see the module docstring).
ROW_STEP_SOURCES: tuple[str, ...] = (
    "fda-97", "taipei-foodtracer", "taipei-hygiene-grade", "gcis-restaurant-registry", "fia-business-tax",
)

#: Coverage constants for the two weather sources — what every publication on record carried
#: (`probes/a28-backtest.md`: 12 townships on all 214 forecast publications; 171 rows and 19
#: stations on all 841 observation publications). A change either way is news.
COVERAGE: dict[str, dict[str, int]] = {
    "F-D0047-061": {"townships": 12},
    "O-A0001-001": {"stations": 19, "reading_rows": 171},
}

STALE_FACTOR = 3.0   # hours since the last stored publication > this × the measured interval
SILENT_FACTOR = 2.0  # hours since the last run of any outcome > this × the run cadence
ROW_STEP = 0.10      # |rows − previous rows| / previous rows ≥ this, on ROW_STEP_SOURCES

SOURCES: tuple[str, ...] = tuple(RUN_CADENCE_H)

# --- the statements, one value each, `:source` bound by the caller -------------------------------

#: `metric → SQL`. Each returns one row with one value (or NULL). Parameter style is SQLAlchemy's
#: `:name`; `pyformat()` below rewrites it for psycopg2, which `PostgresHook` speaks.
STATEMENTS: dict[str, str] = {
    "hours_since_last_run": (
        "select extract(epoch from (now() - max(started_at))) / 3600.0 "
        "from ingest_run where source = :source"
    ),
    "failed_24h": (
        "select count(*) from ingest_run where source = :source and outcome = 'failed' "
        "and started_at > now() - interval '24 hours'"
    ),
}


def publication_statements(source: str) -> dict[str, str]:
    """The per-source statements over its publication table (and readings, for the weather pair)."""
    table, rows_column, _ = PUBLICATIONS[source]
    out = {
        "hours_since_last_stored": (
            "select extract(epoch from (now() - max(detected_at))) / 3600.0 from {}".format(table)
        ),
    }
    if source in ROW_STEP_SOURCES:
        out["rows"] = "select {} from {} order by id desc limit 1".format(rows_column, table)
        out["previous_rows"] = "select {} from {} order by id desc limit 1 offset 1".format(rows_column, table)
    else:
        # The weather pair's publication tables carry no row count, only the payload's size; the
        # reading count is queried. Both are recorded for a reader and neither carries a line.
        out["payload_bytes"] = "select {} from {} order by id desc limit 1".format(rows_column, table)
    if source == "F-D0047-061":
        out["reading_rows"] = (
            "select count(*) from forecast_reading "
            "where publication_id = (select max(id) from forecast_publication)"
        )
        out["townships"] = (
            "select count(distinct township_code) from forecast_reading "
            "where publication_id = (select max(id) from forecast_publication)"
        )
    if source == "O-A0001-001":
        out["stations"] = (
            "select count(distinct station_id) from observation_reading "
            "where publication_id = (select max(id) from observation_publication)"
        )
        out["reading_rows"] = (
            "select count(*) from observation_reading "
            "where publication_id = (select max(id) from observation_publication)"
        )
    return out


def statements_for(source: str) -> dict[str, str]:
    """Every statement a value check runs for one source, in a fixed order."""
    if source not in SOURCES:
        raise KeyError("{} is not a source the ledger names".format(source))
    out = dict(STATEMENTS)
    out.update(publication_statements(source))
    return out


def pyformat(sql: str) -> str:
    """`:source` → `%(source)s`, the one rewrite psycopg2 needs. Nothing else in these statements
    contains a colon."""
    return sql.replace(":source", "%(source)s")


# --- the rules -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Metric:
    source: str
    metric: str
    value: float | None
    threshold: float | None
    verdict: str  # "ok" | "alert" | "recorded"
    detail: str


@dataclass(frozen=True)
class Finding:
    source: str
    metric: str
    sentence: str


def _h(value: float | None) -> str:
    return "—" if value is None else "{:.1f} h".format(value)


def evaluate(source: str, values: dict[str, float | None]) -> tuple[list[Metric], list[Finding]]:
    """Apply the rules to the values one check read. Pure.

    Returns every metric as a row to record (with its verdict) and the findings that make the task
    fail. A value the statement could not produce (`None`, a source with no run yet) is recorded
    and never alerts: an absence is a different fact from a threshold crossed.
    """
    if source not in SOURCES:
        raise KeyError("{} is not a source the ledger names".format(source))
    metrics: list[Metric] = []
    findings: list[Finding] = []

    def record(metric: str, value, threshold=None, verdict: str = "recorded", detail: str = "") -> None:
        metrics.append(Metric(source, metric, None if value is None else float(value), threshold, verdict, detail))

    def alert(metric: str, value, threshold, sentence: str) -> None:
        metrics.append(Metric(source, metric, float(value), threshold, "alert", sentence))
        findings.append(Finding(source, metric, sentence))

    # 1. STALE — hours since the last stored publication against the measured interval.
    since_stored = values.get("hours_since_last_stored")
    interval = PUBLICATION_INTERVAL_H[source]
    if since_stored is None or interval is None:
        record("hours_since_last_stored", since_stored, None if interval is None else STALE_FACTOR * interval,
               detail="no publication yet" if since_stored is None else "no measured interval yet — recorded, no line")
    elif since_stored > STALE_FACTOR * interval:
        alert("hours_since_last_stored", since_stored, STALE_FACTOR * interval,
              "{}: {} since the last stored publication — its measured interval is {} and the line is "
              "{} (× {:g})".format(source, _h(since_stored), _h(interval), _h(STALE_FACTOR * interval), STALE_FACTOR))
    else:
        record("hours_since_last_stored", since_stored, STALE_FACTOR * interval, "ok")

    # 2. SILENT — hours since the last run of any outcome against the run cadence. In a per-DAG
    #    check this is nearly always small (the check runs right after the ingest); the nightly
    #    freshness task is where it bites. Kept here so the per-source row exists every run.
    since_run = values.get("hours_since_last_run")
    cadence = RUN_CADENCE_H[source]
    if since_run is None:
        record("hours_since_last_run", None, SILENT_FACTOR * cadence, detail="no run in the ledger")
    elif since_run > SILENT_FACTOR * cadence:
        alert("hours_since_last_run", since_run, SILENT_FACTOR * cadence,
              "{}: {} since its last run of any outcome — it runs every {} and the line is {} (× {:g})".format(
                  source, _h(since_run), _h(cadence), _h(SILENT_FACTOR * cadence), SILENT_FACTOR))
    else:
        record("hours_since_last_run", since_run, SILENT_FACTOR * cadence, "ok")

    # 3. FAILED in the last 24 h — A10 already said so; recorded, never raised here.
    record("failed_24h", values.get("failed_24h"), detail="A10 alerts per failure; this is the count")

    # 4. ROW STEP — the five nightly sources only, either direction.
    rows, previous = values.get("rows"), values.get("previous_rows")
    if source in ROW_STEP_SOURCES:
        if rows is None or previous is None or not previous:
            record("row_step", None, ROW_STEP, detail="fewer than two publications — nothing to compare")
        else:
            step = (float(rows) - float(previous)) / float(previous)
            if abs(step) >= ROW_STEP:
                alert("row_step", step, ROW_STEP,
                      "{}: the stored row count moved {:+.1%} ({:.0f} → {:.0f}) against the previous publication — "
                      "the line is ±{:.0%}".format(source, step, float(previous), float(rows), ROW_STEP))
            else:
                record("row_step", step, ROW_STEP, "ok")
    else:
        # The weather pair: recorded for a reader, no line on either (module docstring).
        record("payload_bytes", values.get("payload_bytes"), detail="recorded only")
        if source == "F-D0047-061":
            record("reading_rows", values.get("reading_rows"),
                   detail="recorded only — the forecast's row count is not a metric (partial publications are ordinary)")

    # 5. COVERAGE — the weather constants.
    for metric, expected in COVERAGE.get(source, {}).items():
        observed = values.get(metric)
        if observed is None:
            record(metric, None, float(expected), detail="no reading rows for the newest publication")
        elif int(observed) != expected:
            alert(metric, observed, float(expected),
                  "{}: the newest publication carries {} {}, every publication on record carried {}".format(
                      source, int(observed), metric.replace("_", " "), expected))
        else:
            record(metric, observed, float(expected), "ok")

    return metrics, findings


def freshness(rows: list[tuple[str, float | None]]) -> tuple[list[Metric], list[Finding]]:
    """The nightly cross-source check: `(source, hours since its last run)` per source the ledger
    holds, and a SILENT finding per source past 2 × its cadence. A source the ledger has never
    seen is recorded with no value and no line. Pure."""
    metrics: list[Metric] = []
    findings: list[Finding] = []
    seen = {source for source, _ in rows}
    for source, hours in rows:
        cadence = RUN_CADENCE_H.get(source)
        if cadence is None:
            metrics.append(Metric(source, "hours_since_last_run", hours, None, "recorded", "not a source this module knows"))
            continue
        line = SILENT_FACTOR * cadence
        if hours is None:
            metrics.append(Metric(source, "hours_since_last_run", None, line, "recorded", "no run in the ledger"))
        elif hours > line:
            sentence = "{}: {} since its last run of any outcome — it runs every {} and the line is {} (× {:g})".format(
                source, _h(hours), _h(cadence), _h(line), SILENT_FACTOR)
            metrics.append(Metric(source, "hours_since_last_run", hours, line, "alert", sentence))
            findings.append(Finding(source, "hours_since_last_run", sentence))
        else:
            metrics.append(Metric(source, "hours_since_last_run", hours, line, "ok", ""))
    for source in SOURCES:
        if source not in seen:
            metrics.append(Metric(source, "hours_since_last_run", None, SILENT_FACTOR * RUN_CADENCE_H[source],
                                  "recorded", "never ran"))
    return metrics, findings


FRESHNESS_SQL = (
    "select source, extract(epoch from (now() - max(started_at))) / 3600.0 "
    "from ingest_run group by source order by source"
)

INSERT_METRIC = (
    "insert into metric_history (source, metric, observed_at, publication_id, value, threshold, verdict, detail) "
    "values (:source, :metric, :observed_at, :publication_id, :value, :threshold, :verdict, :detail)"
)


def insert_params(metric: Metric, observed_at: datetime, publication_id: int | None = None) -> dict:
    return {
        "source": metric.source, "metric": metric.metric, "observed_at": observed_at,
        "publication_id": publication_id, "value": metric.value, "threshold": metric.threshold,
        "verdict": metric.verdict, "detail": metric.detail or None,
    }
