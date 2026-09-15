"""A28 question 1 — the one check no per-DAG task can make: which sources did not run at all.

*Owner-ruled 2026-09-15 (decision-log «A28 question 1, value-level anomaly checks — the light
option»: «plus one small nightly task for hours-since-last-run across sources»).*

A value check appended to an ingest DAG runs when that DAG runs. A DAG that never fired — paused
after a deploy (the runbook's first hazard), a scheduler that was down, a cron that a person edited
— leaves no failed task and so no A10 message. This DAG asks the ledger one question every night:
for every source, how many hours since its last run of any outcome; it writes one row per source to
`metric_history`; and it fails, naming each source past **2 × its run cadence** (`upto.checks`:
hourly sources 2 h, nightly ones 48 h — the same line the 35-day backtest used, which found two
true events and nothing else), which is one A10 message.

**04:30 Taipei (`30 20 * * *` UTC)** — after the last ingest of the block (the tax registry at
20:20) and before the deletion jobs at 21:00, so a night's silence is reported the same morning and
the task never contends with a deletion.

**Read as `upto_check`**, like every value check (`upto_check_postgres`; revision 0046).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

from airflow.sdk import dag

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _alerts import send_failure_alert  # noqa: E402
from _value_check import make_freshness_task  # noqa: E402


@dag(
    dag_id="upto_source_freshness",
    description="A28 — hours since each source's last run; fails past 2× its cadence",
    schedule="30 20 * * *",
    start_date=datetime(2026, 9, 15),
    catchup=False,
    max_active_runs=1,
    default_args={
        "on_failure_callback": send_failure_alert,
        # No retries: the answer is a `select` over the ledger, and a second try three minutes
        # later reads the same silence. One failure, one message.
        "retries": 0,
        "retry_delay": timedelta(minutes=3),
        "depends_on_past": False,
    },
    tags=["a28", "checks", "freshness"],
)
def upto_source_freshness():
    make_freshness_task()()


upto_source_freshness()
