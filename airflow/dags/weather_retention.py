"""D42 as amended 2026-08-28 — weather readings older than ninety days are deleted, nightly.

Thin the way the other erasure DAG is thin: the rules live in `upto.retention`, and this file
supplies only *when* and *with which database*. What it deletes, what it must leave alone (a
reading some round pinned) and why the count of what it left behind is printed are all in that
module's docstring.

**The cron is UTC and the minute was chosen against the other crons, not against Taipei clock
times.** In use: `0 19` (item 11) and `20 19` · `40 19` · `0 20` · `20 20` (D83's four name
references), then `0 21` for `upto_preference_erasure`. **`40 21` is 21:40 UTC, 05:40 Taipei** —
clear of the whole ingest block, and **forty minutes after the preference erasure** so the two
deletion jobs never contend for locks or arrive as one ambiguous red square. Reading those Taipei
figures as if they were the cron is the mistake D83 exists to prevent; read D83 before moving this.

The hourly weather DAG cannot be avoided by any minute and is not worth avoiding: this job takes
row-level locks in batches and commits each one.

Paused on arrival like every new DAG here — `airflow dags unpause upto_weather_retention` — and a
paused DAG queues nothing and shows no stuck run, which is the hazard `CLAUDE.md` carries.
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

# A15 / D115 as amended 2026-08-28: this job runs as `upto_erasure`, which gained DELETE on the two
# reading tables and SELECT on their publications and on `round_forecast_baseline`. It is **not**
# `upto_ingest`, which already holds DELETE on both tables — that role may read nothing that names a
# person, and the pinned-row filter must read `weight_contribution`. The reasoning is in
# `upto/roles.py` beside the grants.
POSTGRES_CONNECTION = "upto_erasure_postgres"


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


@dag(
    dag_id="upto_weather_retention",
    description="delete weather readings older than ninety days that no round pinned",
    schedule="40 21 * * *",
    start_date=datetime(2026, 8, 28),
    catchup=False,
    max_active_runs=1,
    default_args={
        # A10 — one Telegram message per failed task, after the retries are spent.
        "on_failure_callback": send_failure_alert,
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "depends_on_past": False,
    },
    tags=["retention", "d42", "weather"],
)
def _weather_retention_dag():
    @task(task_id="delete_old_readings")
    def delete_old_readings() -> str:
        interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
        src = os.environ.get("UPTO_SRC", "/opt/upto/src")

        environment = dict(os.environ)
        environment["PYTHONPATH"] = src
        environment["UPTO_DATABASE_URL"] = _database_url()

        finished = subprocess.run(
            [interpreter, "-m", "upto.retention"],
            env=environment, capture_output=True, text=True,
        )
        if finished.stdout:
            print(finished.stdout.strip())
        stderr = (finished.stderr or "").strip()
        if stderr and finished.returncode != 0:
            print(stderr)
        if finished.returncode != 0:
            # Red on purpose. A retention job that fails quietly grows a database nobody is
            # watching, and the whole reason this exists is that seventeen days of weather was
            # 90% of the database before anyone looked.
            raise RuntimeError(
                "weather retention failed: {}".format(stderr[-500:] or "no stderr at all")
            )
        return finished.stdout.strip()

    delete_old_readings()


_weather_retention_dag()
