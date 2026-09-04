"""A22 — the product database is dumped nightly to S3, and the restore has been drilled.

Owner-ruled 2026-08-30 (A11's item ④, decidable since the Proxmox check). A daily `pg_dump` in
custom format to S3 Tokyo, thirty kept, and a restore proven by hand once rather than assumed.

**The cron: `20 22 * * *` UTC = 06:20 Taipei, and the minute is an argument rather than a gap in
the timetable.** D83 first: every cron here is UTC, and the block reads `0 19` place · `20 19`
brand · `40 19` storefront · `0 20` status · `20 20` tax · `0 21` preference erasure · `40 21`
weather retention. So the ingests finish at 20:20 and the two **deletion** jobs finish at 21:40.

This job goes *after the deletions*, and that is the whole reason for the slot. A backup taken
before the erasure would contain the preferences the erasure is about to remove — and then live in
S3 for thirty days, so a restore three weeks later would **resurrect data a member asked to be
forgotten**. D17 makes persistence opt-in and D25 says a revoked version is erased, not closed; a
backup that quietly undoes that is not a backup policy, it is a retention leak with a different
name. Same for D42's ninety-day weather window. Running after both means the dump can only ever
contain what the product was allowed to be holding at 21:40.

`20 22` keeps the forty-minute spacing the retention job already uses after the erasure, so no two
jobs contend and a red square is never ambiguous about which one it belongs to. The hourly weather
DAG cannot be avoided by any minute and is not worth avoiding.

**The role: `upto_backup`, read-only.** Revision 0038 and its docstring carry that argument; the
short version is that this task runs inside the long-lived scheduler (`pg_dump` is in the airflow
images and not in api/tests, H1) and D115 says only a job that exits may hold the owner.

**Designed-off is a legal state (A10's shape).** With `UPTO_BACKUP_S3_BUCKET` empty the first task
skips and the rest skip with it — a fresh clone, `split_boot_check.sh` and CI all boot with no
bucket, no AWS key and no red square. Absent is not broken here; it is the default.

**The Airflow metadata database is NOT backed up, and the reason is stronger than its cost.** It
lives in the same Postgres instance, so including it would genuinely be one more `pg_dump` line.
But `airflow` holds the **Fernet-encrypted Connections** — the CWA key, the Telegram token and all
five database passwords. Shipping it to S3 nightly would put every credential in this stack into a
bucket, encrypted with a key that lives in `app/.env`, i.e. one `.env` leak from plaintext and
under different access control than the machine. What its loss actually costs is history: DAG runs,
task instances, XComs. The DAGs are code in git, and `airflow-init` rebuilds every Connection from
`.env` on the next `up`. Trading every credential's blast radius for a run history is a bad trade,
so it is not made.

**Paused on arrival like every new DAG here** — `airflow dags unpause upto_db_backup` — and that
hazard is in `CLAUDE.md`, where it has cost hours already.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from airflow.exceptions import AirflowSkipException
from airflow.hooks.base import BaseHook
from airflow.sdk import dag, task

# H46 — Airflow 3 does not put the dags folder on `sys.path`. Read it before moving this.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _alerts import send_failure_alert

# A22 / D115: read-only, `pg_read_all_data`, nothing else. NOT the owner and NOT `upto_api`.
POSTGRES_CONNECTION = "upto_backup_postgres"
#: The scoped IAM key (D61), written into a Connection by `init.sh` and never in an image (H16).
S3_CONNECTION = "upto_backup_s3"

#: Thirty daily dumps. At ~20 MB each that is ~600 MB in S3 Tokyo — pennies a month against the
#: credit, and a month is long enough that a corruption introduced quietly still has a clean copy
#: behind it. A larger number costs almost nothing; the reason not to reach for one is that an
#: old dump of a database holding `preference` rows is the same retention question D42 answers for
#: weather, and thirty days is already longer than any window the product itself keeps.
KEEP_DAILY = 30


def _destination() -> tuple[str, str]:
    """`(bucket, prefix)` from the environment, or a skip.

    The bucket name is configuration, not a secret, so it rides `x-airflow-env` with the other
    Airflow settings; the IAM key is a secret and rides a Connection (A21, D33).
    """
    bucket = (os.environ.get("UPTO_BACKUP_S3_BUCKET") or "").strip()
    if not bucket:
        raise AirflowSkipException(
            "UPTO_BACKUP_S3_BUCKET is empty — no destination is configured, so nothing was "
            "dumped and nothing was uploaded. This is the designed state for a fresh clone "
            "and for CI (A10's shape), not a failure."
        )
    prefix = (os.environ.get("UPTO_BACKUP_S3_PREFIX") or "db").strip().strip("/")
    return bucket, prefix


def _psql_env() -> dict:
    """`PGPASSWORD` and friends for one subprocess call, built at run time and never before.

    H16 / A21: the credential exists as environment for the length of the call. It is in no image,
    and the scheduler's own environment never holds it — `BaseHook` decrypts it from the metadata
    database with the Fernet key each time this runs.
    """
    connection = BaseHook.get_connection(POSTGRES_CONNECTION)
    return {
        "PGHOST": connection.host,
        "PGPORT": str(connection.port or 5432),
        "PGUSER": connection.login,
        "PGPASSWORD": connection.password,
        "PGDATABASE": connection.schema,
    }


@dag(
    dag_id="upto_db_backup",
    description="nightly pg_dump of the product database to S3 (A22)",
    schedule="20 22 * * *",
    start_date=datetime(2026, 8, 30),
    catchup=False,
    max_active_runs=1,
    default_args={
        "on_failure_callback": send_failure_alert,
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["upto", "backup"],
)
def upto_db_backup():
    @task
    def dump_and_upload() -> dict:
        """Dump, name the object after the day and the schema, upload, and always clean up.

        **One task rather than two, deliberately.** A `dump` task handing a path to an `upload`
        task would leave a 20 MB file behind whenever the upload failed, in a container nobody
        rebuilds daily — so the temporary file's whole life is inside one `finally`.

        **The object name carries `alembic current`**, because the number that makes a dump
        restorable is not the date: a dump is only loadable into a schema it matches, and finding
        out which migration a file predates by loading it is the expensive way. `0037` in the name
        answers it before the download.
        """
        import boto3

        bucket, prefix = _destination()
        environment = dict(os.environ, **_psql_env())

        revision = subprocess.run(
            ["psql", "-tAc", "select version_num from alembic_version"],
            env=environment, capture_output=True, text=True, check=True,
        ).stdout.strip() or "unknown"

        # The run's own logical day, never `date` on the box: a re-run of a past day must name
        # that day. `ds` is Airflow's, and it is UTC like every other time here (D83).
        #
        # **But a hand-triggered run has no logical day at all, and `["ds"]` killed it — measured
        # 2026-09-04, `KeyError: 'ds'` six seconds in.** In Airflow 3 a manual trigger without
        # `--logical-date` leaves `logical_date` None and `ds` absent from the context. **That is
        # the path the runbook, A22's proof and every launch-day check use** — «trigger it once
        # and watch it go green» — so the DAG could not be verified by the only method anybody
        # would reach for, while its scheduled path was fine.
        #
        # Falls back to today in UTC and SAYS SO in the log, rather than silently: the object
        # name is a claim about which day's data is inside it, and a wrong one is discovered
        # during a restore.
        from airflow.sdk import get_current_context
        context = get_current_context()
        day = context.get("ds")
        if not day:
            logical = context.get("logical_date")
            day = (logical or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
            print("no logical day on this run (hand-triggered) — naming the object for today, "
                  "{}, from the box's UTC clock rather than from the schedule".format(day),
                  flush=True)

        key = "{}/upto-{}-{}.dump".format(prefix, day, revision)
        handle, path = tempfile.mkstemp(suffix=".dump", prefix="upto-backup-")
        os.close(handle)
        try:
            subprocess.run(
                ["pg_dump", "--format=custom", "--compress=6", "--file", path],
                env=environment, check=True,
            )
            size = os.path.getsize(path)
            if size < 1024:
                # A `pg_dump` that exits 0 having written almost nothing is the failure this
                # ticket exists to catch, and it is silent by nature. Refuse rather than upload.
                raise RuntimeError(
                    "pg_dump exited 0 but wrote only {} bytes to {} — refusing to upload a dump "
                    "that cannot be a database.".format(size, path)
                )
            connection = BaseHook.get_connection(S3_CONNECTION)
            client = boto3.client(
                "s3",
                aws_access_key_id=connection.login,
                aws_secret_access_key=connection.password,
                region_name=(connection.extra_dejson or {}).get("region_name", "ap-northeast-1"),
            )
            client.upload_file(path, bucket, key)
        finally:
            if os.path.exists(path):
                os.remove(path)

        print("backup: s3://{}/{} — {:,} bytes, schema {}".format(bucket, key, size, revision))
        return {"bucket": bucket, "prefix": prefix, "key": key, "bytes": size,
                "revision": revision}

    @task
    def sweep(uploaded: dict) -> int:
        """Keep the newest `KEEP_DAILY` objects under the prefix; delete the rest.

        **Sorted by the key, not by `LastModified`.** The key carries the day, so a re-uploaded
        object for an old day sorts where that day belongs rather than jumping to the front and
        pushing a newer dump out. It also means the sweep's decision can be read off the listing
        by a person, which `LastModified` does not allow.

        Takes `uploaded` so it runs **after** a successful upload and never before: sweeping first
        would, on the night the dump fails, delete the oldest copy and add nothing.
        """
        import boto3

        bucket, prefix = uploaded["bucket"], uploaded["prefix"]
        connection = BaseHook.get_connection(S3_CONNECTION)
        client = boto3.client(
            "s3",
            aws_access_key_id=connection.login,
            aws_secret_access_key=connection.password,
            region_name=(connection.extra_dejson or {}).get("region_name", "ap-northeast-1"),
        )
        keys = []
        token = None
        while True:
            page = client.list_objects_v2(
                **{"Bucket": bucket, "Prefix": prefix + "/"},
                **({"ContinuationToken": token} if token else {}),
            )
            keys.extend(item["Key"] for item in page.get("Contents", []))
            token = page.get("NextContinuationToken")
            if not token:
                break

        stale = sorted(keys)[:-KEEP_DAILY] if len(keys) > KEEP_DAILY else []
        for key in stale:
            client.delete_object(Bucket=bucket, Key=key)
        print("backup sweep: {} object(s) under {}/, {} kept, {} deleted".format(
            len(keys), prefix, min(len(keys), KEEP_DAILY), len(stale)))
        return len(stale)

    sweep(dump_and_upload())


upto_db_backup()
