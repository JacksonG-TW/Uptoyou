"""A28 question 1 — the value check that follows every ingest, and the nightly freshness sweep.

*Owner-ruled 2026-09-15 (decision-log «A28 question 1, value-level anomaly checks — the light
option» and «A28's checks read through a new read-only check role»).*

**What a value check is.** After an ingest and its A9 publication check, one task reads a handful of
numbers about that source — hours since its last stored publication, hours since its last run,
failures in the last 24 h, the stored row count and its step against the previous publication, and
for the weather pair the coverage constants — writes every one of them to `metric_history` with a
verdict, and **fails on a finding**, which is what sends one A10 message naming the source and the
hours. The rules and the statements are `upto.checks` (pure, tested host-side and against a real
database); this file is the Airflow around them.

**It runs on a quiet day too.** A9's check task skips when the ingest stored nothing, and a task
downstream of a skip is skipped by default — but «no publication for three intervals» is exactly
the night this check exists for, so it carries `trigger_rule=NONE_FAILED` and runs after a skipped
A9 as well as after a passed one. It does not run after a failed ingest: A10 has alerted, and a
second message about the same night would be the double alert A10's docstring rules out.

**The credential is a Connection, read in this process, and it is the check role's.**
`upto_check_postgres` holds `upto_check` — SELECT on exactly the tables the statements read and
INSERT on `metric_history`, refused on every write elsewhere (revision 0046; `test_role_grants`).
D33/H16 unchanged: the hook reads the Fernet-encrypted Connection in the task process, nothing
lands in XCom or a rendered field, and Airflow masks the password in the task log. The statements
carry no credential and no person's row, so the templated `sql` the SQL operators would log is not
a concern here either — these are plain hook calls, not templated operators.

**Every threshold is a constant in `upto.checks`, measured from the data with its source line.** A
threshold that follows a stale source live is no threshold (the owner's ruling on this choice,
2026-09-15). Nothing here reads a threshold from the database.

Airflow is imported inside the factory functions, like `_publication_check.py`, so the module
imports host-side (`tests/test_value_check.py` asserts it) and the rules stay testable without a
scheduler.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.environ.get("UPTO_SRC", "/opt/upto/src"))

from upto import checks  # noqa: E402

POSTGRES_CONNECTION = "upto_check_postgres"


def _read_values(hook, source: str) -> dict:
    values = {}
    for metric, sql in checks.statements_for(source).items():
        row = hook.get_first(checks.pyformat(sql), parameters={"source": source})
        values[metric] = None if row is None or row[0] is None else float(row[0])
    return values


def _insert_sql() -> str:
    """`INSERT_METRIC` with every `:name` turned into psycopg2's `%(name)s`."""
    return re.sub(r":([a-z_]+)", r"%(\1)s", checks.INSERT_METRIC)


def _record(hook, metrics, observed_at: datetime, publication_id=None) -> None:
    sql = _insert_sql()
    for metric in metrics:
        hook.run(sql, parameters=checks.insert_params(metric, observed_at, publication_id))


def make_value_check_task(source: str, task_id: str = "value_check"):
    """Build the value-check task for one source. Call inside a `@dag` body, downstream of the
    A9 check (or of the ingest, for the weather pair, which has no A9 check)."""
    if source not in checks.SOURCES:
        raise KeyError("{} is not a source `upto.checks` knows — the key is the ledger's".format(source))

    from airflow.providers.postgres.hooks.postgres import PostgresHook
    from airflow.sdk import task
    from airflow.utils.trigger_rule import TriggerRule

    @task(task_id=task_id, trigger_rule=TriggerRule.NONE_FAILED)
    def value_check(_upstream=None) -> str:
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION)
        observed_at = datetime.now(timezone.utc)
        values = _read_values(hook, source)
        publication_id = values.pop("publication_id", None)
        metrics, findings = checks.evaluate(source, values)
        _record(hook, metrics, observed_at, None if publication_id is None else int(publication_id))
        for metric in metrics:
            print("{} {} = {} [{}]{}".format(
                metric.source, metric.metric, "—" if metric.value is None else "{:.3f}".format(metric.value),
                metric.verdict, " — " + metric.detail if metric.detail else ""))
        if findings:
            raise RuntimeError("; ".join(finding.sentence for finding in findings))
        return "{}: {} metrics recorded, no finding".format(source, len(metrics))

    return value_check


def make_freshness_task(task_id: str = "hours_since_last_run"):
    """The nightly cross-source task: one statement over the ledger, one row per source in
    `metric_history`, a failure naming every source past 2 × its cadence."""
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    from airflow.sdk import task

    @task(task_id=task_id)
    def hours_since_last_run() -> str:
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION)
        observed_at = datetime.now(timezone.utc)
        rows = [(source, None if hours is None else float(hours))
                for source, hours in hook.get_records(checks.FRESHNESS_SQL)]
        metrics, findings = checks.freshness(rows)
        _record(hook, metrics, observed_at)
        for metric in metrics:
            print("{} = {} [{}]{}".format(
                metric.source, "—" if metric.value is None else "{:.1f} h".format(metric.value),
                metric.verdict, " — " + metric.detail if metric.detail else ""))
        if findings:
            raise RuntimeError("; ".join(finding.sentence for finding in findings))
        return "{} sources, none silent".format(len(rows))

    return hours_since_last_run
