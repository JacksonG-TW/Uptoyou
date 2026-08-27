"""D17/D25's erasure, on a schedule — because an obligation that depends on being remembered is not one.

Owner-ruled 2026-08-18 with A1. H22 is mitigated when this **runs**, not when the column exists:
D17 makes persistence opt-in and D25 says a member who revokes it must have the version history
*erased, not merely closed*.

Thin the way the ingest DAGs are thin: the rules live in `upto.privacy.erase`, and this file
supplies only *when* and *with which database*. What it erases, what it must leave alone (a version
some round pinned — `weight_contribution.preference_id` is `ON DELETE RESTRICT`) and why the count
of what it left behind is printed are all in that module's docstring.

**The cron is UTC, and choosing the minute needed D83 read first.** Every cron in this repository is
UTC (`airflow config get-value core default_timezone` prints `utc`), and D83's four reference
ingests read `20 19` · `40 19` · `0 20` · `20 20` — **19:20 to 20:20 UTC**, which is 03:20–04:20 in
Taipei. So "after the ingests" means **after 20:20 UTC**, not after 04:20 UTC: those Taipei figures
are what a reader remembers, and writing a cron against them is exactly the mistake D83 exists to
prevent — it landed four DAGs in the middle of the working day once. `0 21 * * *` is 21:00 UTC,
05:00 Taipei: clear of all four, and clear of item 11's `0 19`.

The hourly weather DAG cannot be avoided by any choice of minute and is not worth avoiding: this
job is a handful of deletes over a table with tens of rows.

Paused on arrival like every new DAG here — `airflow dags unpause upto_preference_erasure` — and the
hazard is in `CLAUDE.md`, where it has cost hours once already.
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

# A15 / D115 as amended: this job runs as `upto_erasure` — SELECT and DELETE on `preference`,
# SELECT on `weight_contribution` so it can leave a version some round pinned alone (D24), and
# nothing else in the database. Owner-ruled against running it as `upto_api`: a scheduled
# deletion holds exactly the capability it needs. It is NOT `upto_ingest` — that role may not
# touch `preference` at all, which is the point of the split.
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
    dag_id="upto_preference_erasure",
    description="erase preferences nobody agreed to keep, and versions past the retention window",
    schedule="0 21 * * *",
    start_date=datetime(2026, 8, 18),
    catchup=False,
    max_active_runs=1,
    default_args={
        # A10 — one Telegram message per failed task, after the retries are spent. It never
        # raises, and it is silently absent when the `telegram_alerts` Connection is not
        # there, which is the designed state for a stack nobody is watching.
        "on_failure_callback": send_failure_alert,
        "retries": 2,
        "retry_delay": timedelta(minutes=10),
        "depends_on_past": False,
    },
    tags=["privacy", "d17", "d25", "h22", "preference"],
)
def _erasure_dag():
    @task(task_id="erase")
    def erase() -> str:
        interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
        src = os.environ.get("UPTO_SRC", "/opt/upto/src")

        environment = dict(os.environ)
        environment["PYTHONPATH"] = src
        environment["UPTO_DATABASE_URL"] = _database_url()

        finished = subprocess.run(
            [interpreter, "-m", "upto.privacy.erase"],
            env=environment, capture_output=True, text=True,
        )
        if finished.stdout:
            print(finished.stdout.strip())
        stderr = (finished.stderr or "").strip()
        if stderr and finished.returncode != 0:
            print(stderr)
        if finished.returncode != 0:
            # A failed erasure is red on purpose. An obligation that fails quietly is the thing
            # H22 is about, and "nothing was erased tonight" must be visible without anyone
            # reading a log they had no reason to open.
            raise RuntimeError(
                "preference erasure failed: {}".format(stderr[-500:] or "no stderr at all")
            )
        return finished.stdout.strip()

    erase()


_erasure_dag()
