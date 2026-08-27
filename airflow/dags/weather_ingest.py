"""MVP item 10 on a schedule — the CWA weather ingest, hourly.

The DAG is thin on purpose. Fetching and storing live in `upto.ingest`, unit-tested without
a network or a database, and this file only supplies *where the credentials come from* and
*when it runs*. That split is why the DAG could be written without touching the ingest code.

**Hourly for both datasets, and the forecast's schedule deliberately does not match its
cadence** (D42). The observation republishes every 60 minutes with no exception measured;
the forecast changes about every six hours with fifty minutes of jitter across three gaps,
so there is no clock to align to. The content hash decides whether anything was published,
which makes roughly twenty of the twenty-four daily forecast runs no-ops — **silent
successes, not failures and not warnings.**

**The ingest runs in its own interpreter, and that is a dependency conflict rather than a
style.** Airflow 3 pins SQLAlchemy below 2.0; the ingest needs 2.0's async session, because
H1 forbids a synchronous driver anywhere in this project. The image builds a venv for it.

**Credentials arrive as Connections (D33) and are handed to that interpreter as subprocess
environment, which is the one place they can go without being recorded.** A task argument
would land in XCom, and a templated `BashOperator` env would land in the UI's rendered
fields — both are the metadata database, both are readable later. A subprocess environment
exists for the length of the call and is written nowhere.

**What this DAG cannot honestly do: backfill.** CWA serves the present publication and has
no history endpoint, so triggering a past interval fetches *now* and stores it under today's
content hash. That is not the result the run would have produced then, and pretending
otherwise would put a wrong lineage label on a real row. `catchup=False` for that reason —
the limitation is the source's, and it is recorded rather than worked around.
"""

from __future__ import annotations

import os
import sys
import subprocess
from datetime import datetime, timedelta

from airflow.hooks.base import BaseHook
from airflow.sdk import dag, task

# H46 — Airflow 3 does not put the dags folder on `sys.path` (Airflow 2 did), so a sibling import
# inserts it. Read `doc/build-hazards.md` H46 before moving this to `PYTHONPATH`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _alerts import send_failure_alert

# A15 / D115: the pipeline runs as `upto_ingest`, which can read nothing that names a
# person (§3.0, D14). `upto_postgres` is the owner's connection and no DAG uses it.
POSTGRES_CONNECTION = "upto_ingest_postgres"
CWA_CONNECTION = "cwa_open_data"

FORECAST_DATASET = "F-D0047-061"
OBSERVATION_DATASET = "O-A0001-001"


def _database_url() -> str:
    """Build the async URL from the Connection, at run time and never before."""
    connection = BaseHook.get_connection(POSTGRES_CONNECTION)
    return "postgresql+asyncpg://{}:{}@{}:{}/{}".format(
        connection.login,
        connection.password,
        connection.host,
        connection.port or 5432,
        connection.schema,
    )


def _api_key() -> str:
    key = BaseHook.get_connection(CWA_CONNECTION).password
    if not key:
        raise RuntimeError(
            "the {} connection carries no password. It holds the CWA open-data key, and "
            "airflow-init is what puts it there (D33).".format(CWA_CONNECTION)
        )
    return key


def _run(dataset_id: str) -> str:
    interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
    source = os.environ.get("UPTO_SRC", "/opt/upto/src")

    environment = dict(os.environ)
    environment["PYTHONPATH"] = source
    environment["UPTO_DATABASE_URL"] = _database_url()
    # Ticket 09: lineage over a scheduled run and over a hand-triggered one are different
    # answers to "why does this row exist", so the runner records which it was.
    environment["UPTO_INVOKED_BY"] = "airflow"
    environment["UPTO_CWA_API_KEY"] = _api_key()

    finished = subprocess.run(
        [interpreter, "-m", "upto.ingest.run", "--dataset", dataset_id],
        env=environment,
        capture_output=True,
        text=True,
    )
    # stdout is the ingest's own one-line verdict — "stored…" or "no change…". stderr only
    # carries a real failure, because a source that answered the same thing as last time is
    # not one.
    if finished.stdout:
        print(finished.stdout.strip())
    if finished.returncode != 0:
        # The whole of stderr reaches the task log before anything is truncated, and the
        # exception keeps the *tail*. Written as `[:500]` this reported a real schema mismatch
        # as "F-D0047-061 ingest failed:" followed by five frames of SQLAlchemy internals and
        # nothing else: a Python traceback puts the line that names the failure last, so
        # truncating from the front discards the only part that is a diagnosis.
        stderr = (finished.stderr or "").strip()
        if stderr:
            print(stderr)
        raise RuntimeError(
            "{} ingest failed: {}".format(dataset_id, stderr[-500:] or "no stderr at all")
        )
    return finished.stdout.strip()


@dag(
    dag_id="upto_weather_ingest",
    description="Item 10 — CWA forecast and observation, hourly, deduplicated by content hash",
    schedule="@hourly",
    start_date=datetime(2026, 8, 11),
    catchup=False,
    max_active_runs=1,
    default_args={
        # A10 — one Telegram message per failed task, after the retries are spent. It never
        # raises, and it is silently absent when the `telegram_alerts` Connection is not
        # there, which is the designed state for a stack nobody is watching.
        "on_failure_callback": send_failure_alert,
        "retries": 2,
        "retry_delay": timedelta(minutes=3),
        "depends_on_past": False,
    },
    tags=["ingest", "item-10", "cwa"],
)
def upto_weather_ingest():
    @task(task_id="observation")
    def observation() -> str:
        """`O-A0001-001`. Republishes every 60 minutes, measured with no exception."""
        return _run(OBSERVATION_DATASET)

    @task(task_id="forecast")
    def forecast() -> str:
        """`F-D0047-061`. About twenty of twenty-four daily runs store nothing, by design."""
        return _run(FORECAST_DATASET)

    # Independent on purpose: a forecast failure must not stop the observation, which is the
    # one with a strict hourly cadence and the one D36's read path prefers.
    observation()
    forecast()


upto_weather_ingest()
