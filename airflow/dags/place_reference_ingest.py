"""MVP item 11 on a schedule — the 食藥署 reference ingest, daily.

Thin for the same reason `weather_ingest.py` is thin: fetching, hashing and parsing live in
`upto.ingest`, unit-tested with no network and no database, and this file supplies only *where
the credentials come from* and *when it runs*.

**Daily against a monthly file, and that is D34's aliasing argument rather than generosity.** A
monthly poll of a monthly file leaves the phase to luck and can be two months stale; a daily one
is bounded at a day. The cost is twenty-nine fetches a month that publish nothing — 17 MB each,
about two seconds — and those runs must be **silent successes**. They do not even decompress the
CSV: the content hash is read from the compressed bytes, so an unchanged day never touches the
99 MB inside.

**One task, not two.** Item 10 splits observation from forecast because a forecast failure must
not stop the hourly observation. Here there is one file and one publication, so a second task
would only be a second thing to explain.

**Credentials: only the database one exists.** D33 counts the sources and this is the one needing
no key — the file is an open download — so the only Connection read here is `upto_postgres`, and
it is handed to the subprocess as environment for the reason the weather DAG states: a task
argument lands in XCom and a templated env lands in the UI's rendered fields, and both of those
are the metadata database.

**Exit code 2 means the two version signals disagree** — the archive stamp says one thing about
whether anything changed and the content hash says another (D34, D35). The task is failed
deliberately in that case, and the verdict printed above the failure says whether anything was
stored: content can move while the stamp stands still, and the stamp can move while the content
stands still. Whatever the run decided to write is already written when the task turns red, so red
here means "come and read the log", not "the data is missing"; a printed warning on a green task is
a fact filed where nobody looks.

**What this DAG cannot honestly do: backfill.** The endpoint serves the current file and has no
history, so triggering a past interval fetches today's bytes and stores them under today's hash —
the same limitation `weather_ingest.py` records, from a different publisher. `catchup=False` for
that reason.
"""

from __future__ import annotations

import os
import sys
import subprocess
from datetime import datetime, timedelta

from airflow.exceptions import AirflowSkipException
from airflow.hooks.base import BaseHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, dag, task
from airflow.utils.trigger_rule import TriggerRule

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

# A9's shape check, shared with the four name-reference DAGs. It defines no DAG, so nothing is
# registered twice. The key it wants is the ledger's `source`, which is `SOURCE` below and never
# a display label.
from _publication_check import make_check_task
from _alerts import send_failure_alert

# A15 / D115: the pipeline runs as `upto_ingest`, which can read nothing that names a
# person (§3.0, D14). `upto_postgres` is the owner's connection and no DAG uses it.
POSTGRES_CONNECTION = "upto_ingest_postgres"

# Stored on the publication row and printed in every verdict line. Kept in step with
# `upto.ingest.fda.SOURCE` by hand, because this file must not import the ingest package —
# Airflow parses DAGs in its own interpreter, and the ingest lives in a separate venv.
SOURCE = "fda-97"

DISAGREEMENT = 2

# **A8's asset — `from airflow.sdk import Asset`, and the path matters.** This is Airflow 3.0.2;
# `airflow.Asset` does not exist and `airflow.Dataset` does but is deprecated. Checked rather than
# assumed, because getting it wrong is an import error at parse time and a DAG that never appears.
PLACE_PUBLICATION = Asset("place_publication")


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
    dag_id="upto_place_reference_ingest",
    description="Item 11 — 食藥署 食品業者登錄 餐飲場所, daily, deduplicated by content hash",
    # 19:00 UTC = 03:00 Taipei the next morning. The cron is UTC — Airflow's
    # `core.default_timezone` is `utc` in this stack — and written as `0 3 * * *` it landed
    # 11:00 Taipei, in the middle of the working day; moved 2026-08-14. Away from the hourly
    # weather ingest's own minute, and at an hour when a 17 MB download competes with nothing.
    # The publisher has never been observed to publish at a particular time of day, so this is
    # a quiet hour rather than an aligned one — and D34's whole point is that no alignment is
    # being attempted.
    schedule="0 19 * * *",
    start_date=datetime(2026, 8, 11),
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
    tags=["ingest", "item-11", "fda", "reference"],
)
def upto_place_reference_ingest():
    @task(task_id="reference_places")
    def reference_places() -> str:
        """One fetch. About twenty-nine of thirty runs a month store nothing, by design."""
        interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
        source = os.environ.get("UPTO_SRC", "/opt/upto/src")

        environment = dict(os.environ)
        environment["PYTHONPATH"] = source
        environment["UPTO_DATABASE_URL"] = _database_url()
        # Ticket 09, and the weather DAG has carried this line since `runlog` was written: a
        # scheduled run and a hand-triggered one are different answers to "why does this row
        # exist". Absent, every run of this DAG records itself as `cli`, which is worse than
        # recording nothing because it is a wrong fact rather than a missing one.
        environment["UPTO_INVOKED_BY"] = "airflow"

        finished = subprocess.run(
            [interpreter, "-m", "upto.ingest.run_places"],
            env=environment,
            capture_output=True,
            text=True,
        )
        # stdout carries the verdict — "stored…", "no change…", and the unresolved-township
        # report. It is printed whatever the exit code, because on a disagreement it is the
        # half that says what was written.
        if finished.stdout:
            print(finished.stdout.strip())
        # stderr reaches the log whole, and the exceptions keep its *tail*. A traceback names
        # the failure on its last line, so `[:500]` kept the frames and discarded the diagnosis
        # — it cost an hour on the weather DAG before it was noticed there.
        stderr = (finished.stderr or "").strip()
        if stderr and finished.returncode != 0:
            print(stderr)
        if finished.returncode == DISAGREEMENT:
            raise RuntimeError(
                "{}: the archive stamp and the content hash disagree — the verdict above says "
                "what was written: {}".format(SOURCE, stderr[-500:])
            )
        if finished.returncode != 0:
            raise RuntimeError(
                "{} ingest failed: {}".format(SOURCE, stderr[-500:] or "no stderr at all")
            )
        return finished.stdout.strip()

    @task(task_id="publication_stored", outlets=[PLACE_PUBLICATION],
          trigger_rule=TriggerRule.NONE_FAILED)
    def publication_stored(verdict: str) -> str:
        """Emit the asset event **only** when the run actually stored a publication (A8 (a)).

        **Why this is its own task rather than an outlet on the ingest.** Airflow does not let a task
        choose to emit: it registers outlet events when the task **succeeds** — verified in
        `api_fastapi/execution_api/routes/task_instances.py`, where `register_asset_changes_in_db` is
        called only under `TISuccessStatePayload`. So the only way to suppress an event is for the task
        to skip. Putting the outlet on the ingest would therefore mean **skipping the ingest** on a
        `no_change` day, and that would be a lie: the ingest fetched 17 MB, hashed it, and correctly
        found nothing new. That is a success, and the UI would say otherwise — on the page the evaluator
        reads this requirement from. So the ingest stays green and this small task skips instead.
        Owner-ruled reading, 2026-08-19.

        **The outcome comes from the ledger, never from the verdict text.** `verdict` is passed in only
        so this task depends on the ingest and appears downstream of it; the decision is a `select` on
        `ingest_run.outcome`. Reading prose for a decision is H36's shape — a guard that reads text
        fires on the sentence that states the rule — and "stored" appears in more sentences than the
        one that means it.

        **`max_active_runs=1` is what makes «the latest row for this source» unambiguous**, and it is
        set on this DAG. Without it two concurrent runs could each read the other's row.
        """
        rows = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION).get_records(
            "select outcome, rows_written from ingest_run "
            " where source = %s order by started_at desc limit 1",
            parameters=(SOURCE,),
        )
        if not rows:
            raise RuntimeError(
                "{}: the ingest returned success and wrote no ledger row — nothing to emit an asset "
                "for, and a missing row is a bug rather than a quiet day".format(SOURCE)
            )
        outcome, rows_written = rows[0]
        if outcome != "stored":
            # Skipped, not failed: nothing was stored and that is the ordinary case, twenty-nine days
            # in thirty. A skipped task emits no asset event, which is precisely the requirement.
            raise AirflowSkipException(
                "{}: outcome is `{}`, so no publication landed and no asset event is emitted. The "
                "ingest above succeeded — this is the designed quiet day, not a failure.".format(
                    SOURCE, outcome)
            )
        print("{}: stored, {} rows newly accepted — emitting {}".format(
            SOURCE, rows_written, PLACE_PUBLICATION.name))
        return verdict

    # **The three-task chain, and the trigger rule is the load-bearing part.** A9's check sits
    # between the ingest and the asset emitter so that a red check emits nothing — using the
    # mechanism A8 already established (an outlet fires only on success, so an unrun task is a
    # silent one) rather than a second suppression path.
    #
    # `publication_stored` takes its XCom from the **ingest**, not from the check, and depends on
    # the check only for ordering. That is deliberate: the check *skips* on the two ordinary
    # non-comparisons — a `no_change` day, and the first publication a source ever stores — and a
    # skipped task leaves no XCom to read. Reading the ingest's verdict keeps the argument real in
    # every path.
    #
    # `NONE_FAILED` is what makes the first publication work at all. `ALL_SUCCESS` would treat the
    # check's n/a skip as a reason not to emit, so the very first publication would land and no
    # classify pass would follow it — the check's honesty about having nothing to compare would
    # silently cost the thing A8 was built for. `NONE_FAILED` runs on success or skip and refuses
    # only on failure, which is precisely the gate wanted here.
    verdict = reference_places()
    check = make_check_task(SOURCE)(verdict)
    stored = publication_stored(verdict)
    check >> stored


upto_place_reference_ingest()
