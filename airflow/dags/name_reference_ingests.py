"""The four reference sources on a schedule — D77 brands, D78 storefront signs, D81 registry
status, D85 tax registry. One file, four DAGs, because they are the same shape four times.

Ruled 2026-08-14: these sources ran by hand while they were being built; from here they run
themselves. Each is thin the way `place_reference_ingest.py` is thin — fetch, hash and parse
live in `upto.ingest`, this file supplies only *when* and *with which database*.

**Daily against slow-moving files, and it is D34's aliasing argument again.** The 食材登錄 and
衛生評核 CSVs have no publication rhythm anyone has observed; the 商業登記 roster is monthly and
the 營業稅籍 extract is cut monthly too. A schedule matched to a guessed rhythm leaves the phase
to luck; a daily poll bounds staleness at a day and costs a few MB a fetch — 66 MB for the tax
file, the largest download in this repository, and on the days it does store, about fifteen
seconds to read 1.7M rows down to the 14.5k worth keeping (measured 2026-08-14, from a saved
file, so the download itself is on top). The no-change days are not waste: each writes a
`no_change` row to `ingest_run`, and a ledger with a
daily heartbeat is what makes a silently broken source distinguishable from a quiet one — the
absence-vs-absence problem `ingest_run` exists to solve.

**Exit 2 applies to the tax source alone.** The first three are bare CSVs with no archive
stamp, so there is no second version signal to disagree with the content hash. D85's file states
its own extract date in row 2, so item 11's disagreement check exists again — and, as there, the
task is failed deliberately on it. Red means "come and read the log", never "the rows are
missing": whatever the run decided to write is already written by the time the code is returned.
Exit 0 is stored-or-no-change, exit 1 is the source failing.

**`--file` never appears here** — item 11's rule, restated because this is the file where it
would be tempting: a local file in a DAG turns the operator's hand-run mistakes into pipeline
history.

**Schedules are staggered after item 11's FDA fetch, and every cron here is UTC.** Airflow's
`core.default_timezone` is `utc` in this stack and nothing sets otherwise, so these read
19:20 · 19:40 · 20:00 · 20:20 UTC — 03:20 · 03:40 · 04:00 · 04:20 the next morning in Taipei.
Quiet hours, one download at a time, no alignment attempted or claimed. Written as if the cron
were Taipei-local they landed 11:20–12:20 Taipei, in the middle of the working day; moved
2026-08-14.

Like every DAG in this repository: no backfill (the endpoints serve only the current file), so
`catchup=False`; a new DAG arrives **paused** and a triggered run sits queued forever until
`airflow dags unpause <dag_id>` — the hazard is in CLAUDE.md and it has cost hours once already.
"""

from __future__ import annotations

import os
import sys
import subprocess
from datetime import datetime, timedelta

from airflow.hooks.base import BaseHook
from airflow.sdk import dag, task

# **The dags folder is NOT on `sys.path` in Airflow 3, and this line is what a wrong assumption
# cost.** Airflow 2 added `dags_folder` to `sys.path` and the documentation for it is still easy to
# find; 3.0.2 loads DAGs through a *bundle* and does not. Measured 2026-08-19: without this line
# both this file and `name_reference_ingests.py` failed to import with
# `ModuleNotFoundError: No module named '_publication_check'`, and the DAGs vanished from the list
# while `airflow dags list` still printed their previous serialisation — so the UI looked fine and
# only `airflow dags list-import-errors` said otherwise.
#
# **Rejected: `PYTHONPATH` on the four airflow services in `compose.yaml`.** It works and it is one
# line instead of two, and it puts the reason a sibling import resolves in a different file from the
# import — so the next person to tidy an environment block breaks a DAG and finds out at 03:20.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A9's shape check, shared with `place_reference_ingest.py`. It defines no DAG of its own, so
# nothing is registered twice.
from _publication_check import make_check_task
from _alerts import send_failure_alert

# A15 / D115: the pipeline runs as `upto_ingest`, which can read nothing that names a
# person (§3.0, D14). `upto_postgres` is the owner's connection and no DAG uses it.
POSTGRES_CONNECTION = "upto_ingest_postgres"

# Item 11's exit code for "the two version signals contradict each other". Only D85's source
# can return it here; the others have one signal and nothing to disagree with.
DISAGREEMENT = 2

# (dag_id suffix, module, source label as printed by the runner, cron — UTC, see above, tags,
#  **db_source**)
#
# **The fourth field and the last one are two different names for the same source, and only the
# last is a key.** The display label is what the runner prints in an error message; `db_source` is
# what `ingest_run.source` and the publication table actually store, and for three of these four
# they are not the same string. A9's check keyed off the display label would find zero rows and
# read that as "no previous publication" — a false n/a, which is the exact bug the n/a state exists
# to prevent. Measured against the live ledger 2026-08-19. The labels are left alone rather than
# renamed: they appear in the logs of every run since 2026-08-14, and rewriting history to make
# one string do two jobs is a bigger change than carrying two fields.
SOURCES = (
    (
        "brand",
        "upto.ingest.run_brands",
        "foodtracer-brands",
        "20 19 * * *",
        ["ingest", "d77", "brands", "reference"],
        "taipei-foodtracer",
    ),
    (
        "storefront",
        "upto.ingest.run_storefronts",
        "gradelist-storefronts",
        "40 19 * * *",
        ["ingest", "d78", "storefronts", "reference"],
        "taipei-hygiene-grade",
    ),
    (
        "business_status",
        "upto.ingest.run_business_status",
        "gcis-status",
        "0 20 * * *",
        ["ingest", "d81", "registry-status", "reference"],
        "gcis-restaurant-registry",
    ),
    (
        "business_tax",
        "upto.ingest.run_business_tax",
        "fia-business-tax",
        "20 20 * * *",
        ["ingest", "d85", "tax-registry", "reference"],
        "fia-business-tax",
    ),
)


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


def _make(name: str, module: str, source: str, cron: str, dag_tags: list[str],
          db_source: str):
    @dag(
        dag_id=f"upto_{name}_ingest",
        description=f"{source} — daily, deduplicated by content hash",
        schedule=cron,
        start_date=datetime(2026, 8, 14),
        catchup=False,
        max_active_runs=1,
        default_args={
            # A10 — one Telegram message per failed task, after the retries are spent. It never
            # raises and it is silently absent when the `telegram_alerts` Connection is not
            # there, which is the designed state for a stack nobody is watching.
            "on_failure_callback": send_failure_alert,
            "retries": 2,
            "retry_delay": timedelta(minutes=10),
            "depends_on_past": False,
        },
        tags=dag_tags,
    )
    def _ingest_dag():
        @task(task_id=name)
        def run() -> str:
            """One fetch; most days store nothing, and that no-op is recorded by design."""
            interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
            src = os.environ.get("UPTO_SRC", "/opt/upto/src")

            environment = dict(os.environ)
            environment["PYTHONPATH"] = src
            environment["UPTO_DATABASE_URL"] = _database_url()
            # A scheduled run and a hand-triggered one are different answers to "why does
            # this row exist" — absent, the run records itself as `cli`, a wrong fact.
            environment["UPTO_INVOKED_BY"] = "airflow"

            finished = subprocess.run(
                [interpreter, "-m", module],
                env=environment,
                capture_output=True,
                text=True,
            )
            if finished.stdout:
                print(finished.stdout.strip())
            # stderr's tail carries the diagnosis; truncating from the front cost an hour
            # on the weather DAG once.
            stderr = (finished.stderr or "").strip()
            if stderr and finished.returncode != 0:
                print(stderr)
            if finished.returncode == DISAGREEMENT:
                raise RuntimeError(
                    "{}: the file's own stamp and the content hash disagree — the verdict "
                    "above says what was written: {}".format(source, stderr[-500:])
                )
            if finished.returncode != 0:
                raise RuntimeError(
                    "{} ingest failed: {}".format(source, stderr[-500:] or "no stderr at all")
                )
            return finished.stdout.strip()

        # A9 — the shape check, downstream of the ingest. Nothing depends on it here (these four
        # emit no asset), so it needs no trigger rule: it is the leaf, and its three states are the
        # whole report. A red one means the source changed the shape of its file or its row count
        # collapsed, and the rows it stored are already stored — red means "come and read the log",
        # the same reading as the disagreement above.
        make_check_task(db_source)(run())

    _ingest_dag()


for _name, _module, _source, _cron, _tags, _db_source in SOURCES:
    _make(_name, _module, _source, _cron, _tags, _db_source)
