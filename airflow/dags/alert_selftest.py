"""A10's self-test — the one DAG in this repository that exists to fail.

*Owner-ruled 2026-08-19.*

**The question it answers.** A10 puts an `on_failure_callback` on every task in every DAG, and the
code path was verified piece by piece: the absent-Connection branch, the refused-by-Telegram branch,
the three redactions, and a DagBag load proving all 16 tasks carry the callback. **What none of that
proves is that Airflow calls it when a task really fails.** Every real failure reachable for a test
costs something: breaking the CWA Connection writes a false `failed` row into `ingest_run`, and that
ledger's whole job is telling a broken source from a quiet one — a lie there is worse than an
unproven callback.

So: one task, no source, no ledger row, no side effect, whose only job is to raise. Triggered by
hand, it proves the whole real path at once — Airflow catches the failure, calls the callback, the
message arrives on the phone.

**And it keeps proving it.** That is the larger half of the argument. A monitoring channel nobody can
test is a channel nobody knows is dead: a revoked bot token, a deleted chat, a Connection lost to a
volume reset, all look exactly like a quiet month. This is how "is alerting still working?" gets an
answer in ten seconds instead of waiting for the first real failure to double as the test — the same
argument `ingest_run`'s daily heartbeat won, one layer up.

**The cost, stated because it is real.** One more DAG in a list of eight, forever, and it is the only
one here designed to go red. Somebody will see `upto_alert_selftest` failed and spend ten minutes
finding out it means nothing. Three things are done about that and none of them removes it: the id
says `selftest`, the `description` says it, and the exception message itself reads *nothing is
wrong* — so the sentence that arrives on the phone and the sentence in the log both explain
themselves without this file being opened.

**Rejected: leaving the gap.** A10 works or it does not and we find out the first night something
breaks. Cheaper today, and it makes the first real failure the test — which is exactly the
arrangement that lets a dead channel sit dead for weeks. This whole item exists because nobody was
watching at 03:20.

**`schedule=None` and paused on arrival.** It must never run by itself: a DAG that fails on a timer
is an alert channel that cries wolf nightly, which is how a channel stops being read. Hand-triggered
only, and `is_paused_upon_creation=True` states the standing hazard as the intended state for once
rather than as a trap.

**`retries: 0`, and that is not a detail.** `on_failure_callback` fires when the task instance
finishes in FAILED state, which is after the retries are spent — so the repository's usual
`retries: 2, retry_delay: 10 minutes` would make this self-test take twenty minutes to send one
message. Zero here, and the message arrives in seconds.

Run it:
    docker compose exec airflow-scheduler airflow dags unpause upto_alert_selftest   # once
    docker compose exec airflow-scheduler airflow dags trigger upto_alert_selftest
    # the task goes red, and one Telegram message arrives. Re-pause it if you like; it
    # cannot run on its own either way, because it has no schedule.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

from airflow.sdk import dag, task

# H46 — Airflow 3 does not put the dags folder on `sys.path` (Airflow 2 did), so a sibling import
# inserts it. A wrong move shows only in `airflow dags list-import-errors`, never in the DAG
# list, so check there before moving this to `PYTHONPATH`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _alerts import CONNECTION_ID, send_failure_alert

# The sentence that arrives on the phone and stands in the log. **It says what it is, because the
# reader of an alert at 03:20 has not opened this file and should not need to.**
MESSAGE = "A10 self-test — nothing is wrong"


@dag(
    dag_id="upto_alert_selftest",
    description="A10's self-test: this DAG exists to FAIL, on purpose, to prove failure alerts work",
    # No schedule at all. Hand-triggered only — see the docstring: a DAG that fails on a timer is a
    # channel that cries wolf nightly.
    schedule=None,
    start_date=datetime(2026, 8, 19),
    catchup=False,
    max_active_runs=1,
    # Paused on arrival, stated rather than inherited. Everywhere else in this repository that is a
    # hazard (a triggered run sits queued forever); here it is the point.
    is_paused_upon_creation=True,
    default_args={
        # A10 — the callback under test. Everything else in this file is scaffolding around it.
        "on_failure_callback": send_failure_alert,
        # **Zero, unlike every other DAG here.** The callback fires only once the retries are spent,
        # so the usual `2` with a ten-minute delay would make a self-test take twenty minutes.
        "retries": 0,
        "depends_on_past": False,
    },
    tags=["a10", "selftest", "alerting", "expected-to-fail"],
)
def upto_alert_selftest():
    @task(task_id="selftest")
    def selftest() -> None:
        """Raise. But say first whether a message is actually expected.

        **Without this, a green Connection and a missing one look identical from the phone** — no
        message arrives either way, and the natural conclusion is that the callback is broken. The
        callback does print its own reason into this task's log, but it prints it *after* the failure,
        below a traceback, which is the one place nobody looks first. So the expectation is stated
        before the failure instead.
        """
        try:
            from airflow.hooks.base import BaseHook

            BaseHook.get_connection(CONNECTION_ID)
            print("A10 self-test: the `{}` Connection exists, so ONE Telegram message is expected "
                  "within a few seconds of the failure below.".format(CONNECTION_ID))
        except Exception:  # noqa: BLE001 — an absent Connection is a legal state (A10)
            print("A10 self-test: there is no `{}` Connection, so NO message will be sent and that "
                  "is not a failure of this test — alerting is off on this stack. Set "
                  "UPTO_TELEGRAM_BOT_TOKEN and UPTO_TELEGRAM_CHAT_ID in app/.env and re-run "
                  "`docker compose up airflow-init --force-recreate --no-deps`.".format(
                      CONNECTION_ID))

        # The whole point. Nothing has been written, nothing fetched, no ledger row exists.
        raise RuntimeError(MESSAGE)

    selftest()


upto_alert_selftest()
