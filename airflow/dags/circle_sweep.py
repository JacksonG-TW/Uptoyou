"""A24 item 4 — the nightly sweep of abandoned self-serve circles, on a schedule.

Thin the way `preference_erasure.py` is thin: the rules live in the database (`circle_sweep_candidates`
and `sweep_circle`, revision 0045) and the reporting in `upto.sweep`; this file supplies only *when*
and *with which database*. It connects as `upto_erasure` through the same Connection, which holds
EXECUTE on those two functions and no table grant for circles at all (owner, 2026-09-14).

**`0 22 * * *` UTC is 06:00 Taipei, and the slot is chosen against the other deletion jobs and the
dump** (D83: every cron here is UTC). Preference erasure `0 21` · weather retention `40 21` · **this
`0 22`** · the dump `20 22` · the dataset export `0 23`. After the other two deletions and before the
dump, so a circle removed tonight is not in the morning's backup.

**A red run is the designed signal.** `upto.sweep` keeps going past a circle it could not delete
and exits 1 at the end, so one stuck circle turns this DAG red every night until somebody looks —
never a silent skip.

Paused on arrival like every new DAG here — `airflow dags unpause upto_circle_sweep` (H46).
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
    dag_id="upto_circle_sweep",
    description="delete self-serve circles with no signed trip, untouched for 30 days",
    schedule="0 22 * * *",
    start_date=datetime(2026, 9, 14),
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
    tags=["privacy", "a24", "circle", "sweep"],
)
def _sweep_dag():
    @task(task_id="sweep")
    def sweep() -> str:
        interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
        src = os.environ.get("UPTO_SRC", "/opt/upto/src")

        environment = dict(os.environ)
        environment["PYTHONPATH"] = src
        environment["UPTO_DATABASE_URL"] = _database_url()

        finished = subprocess.run(
            [interpreter, "-m", "upto.sweep"],
            env=environment, capture_output=True, text=True,
        )
        if finished.stdout:
            print(finished.stdout.strip())
        stderr = (finished.stderr or "").strip()
        if stderr and finished.returncode != 0:
            print(stderr)
        if finished.returncode != 0:
            # Red on purpose: `upto.sweep` exits 1 when any circle could not be deleted, and
            # prints which and why on stdout, which is echoed above.
            raise RuntimeError(
                "circle sweep failed: {}".format(stderr[-500:] or finished.stdout.strip()[-500:]
                                                 or "no output at all")
            )
        return finished.stdout.strip()

    sweep()


_sweep_dag()
