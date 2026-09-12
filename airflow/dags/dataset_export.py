"""The dataset export — a Parquet of every place, nightly to S3 beside the dump.

Owner-ruled 2026-09-12 (「有好的資料集，才好訓練模型跟給資料科學家分析」), option (c) of
`idea & img/research/dataset-as-product.md`: export only, no schema change, reversible by deleting
this file.

**The cron: `0 23 * * *` UTC = 07:00 Taipei, and the slot is an argument.** D83 first — every cron
here is UTC, and the block reads `0 19` place · `20 19` brand · `40 19` storefront · `0 20` status ·
`20 20` tax · `0 21` preference erasure · `40 21` weather retention · `20 22` the dump.

This goes **after the dump**, forty minutes later, keeping the spacing every job in the block
already uses so no two contend and a red square is never ambiguous about which one it belongs to.
After the ingests because it exports what they published; after the deletions for the same reason
the dump is, though it matters less here — **this file contains no member data at all**, so the
retention argument that puts the dump at `20 22` does not bind it. It is placed last because it is
the least urgent thing in the timetable and the most tolerant of a late start: a dataset written an
hour later is the same dataset.

**The role: `upto_backup`, and no new role.** It already holds `pg_read_all_data` and already writes
this bucket for the dump. D115's shape asks that a new role argue better than the fourth did, and
this one has nothing to argue with: it reads exactly what the backup reads and writes to the same
place. A fifth role here would be one more password and one more grant map for no boundary that is
not already drawn.

**The export runs in the venv, not in Airflow's interpreter.** `place_display` is the app's own read
path and needs SQLAlchemy 2.0's async session, which Airflow 3 pins below — the same split the
ingests use, so this shells out to `UPTO_PYTHON` exactly as they do.

**Designed-off is a legal state (A10/A22's shape).** With `UPTO_BACKUP_S3_BUCKET` empty the first
task skips and the rest skip with it. A fresh clone, `split_boot_check.sh` and CI all boot with this
DAG present and skipping.

**Paused on arrival like every new DAG here** — `airflow dags unpause upto_dataset_export`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta

from airflow.exceptions import AirflowSkipException
from airflow.hooks.base import BaseHook
from airflow.sdk import dag, task

# H46 — Airflow 3 does not put the dags folder on `sys.path`. Read it before moving this.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _alerts import send_failure_alert

#: A22/D115: read-only, `pg_read_all_data`. The same Connection the dump uses, for the same reason.
POSTGRES_CONNECTION = "upto_backup_postgres"
S3_CONNECTION = "upto_backup_s3"

UPTO_PYTHON = os.environ.get("UPTO_PYTHON", "python")
UPTO_SRC = os.environ.get("UPTO_SRC", "/opt/upto/src")


def _destination() -> tuple[str, str]:
    """`(bucket, prefix)` or a skip — **read from `upto.dataset.export`, not re-derived here.**

    This function and `object_names` below used to hold their own copies of the rule, which meant
    the tested copy and the running copy were two different pieces of code that happened to agree
    (the reviewer's second `should`, 2026-09-12). The module is importable with the standard library
    alone, so reading it here costs Airflow's interpreter nothing — it does not pull in SQLAlchemy or
    pyarrow.
    """
    sys.path.insert(0, UPTO_SRC)
    from upto.dataset.export import destination  # noqa: PLC0415

    found = destination()
    if found is None:
        raise AirflowSkipException(
            "UPTO_BACKUP_S3_BUCKET is empty — no destination is configured, so nothing was "
            "exported and nothing was uploaded. This is the designed state for a fresh clone "
            "and for CI (A10's shape), not a failure."
        )
    return found


def _database_url() -> str:
    """The async URL for the venv's own process, built at run time and never before (H16/A21)."""
    connection = BaseHook.get_connection(POSTGRES_CONNECTION)
    return "postgresql+asyncpg://{}:{}@{}:{}/{}".format(
        connection.login, connection.password, connection.host,
        connection.port or 5432, connection.schema,
    )


@dag(
    dag_id="upto_dataset_export",
    description="nightly Parquet of every place to S3, beside the dump",
    schedule="0 23 * * *",
    start_date=datetime(2026, 9, 12),
    catchup=False,
    max_active_runs=1,
    default_args={
        "on_failure_callback": send_failure_alert,
        "retries": 1,
        "retry_delay": timedelta(minutes=10),
    },
    tags=["upto", "dataset"],
)
def upto_dataset_export():
    @task
    def export_and_upload() -> dict:
        """Write the Parquet and its dictionary, upload both, and always clean up.

        **One task rather than two, for the reason the dump gives:** a `write` task handing a path
        to an `upload` task leaves the file behind whenever the upload fails, in a container nobody
        rebuilds daily. The temporary directory's whole life is inside one `finally`.

        **The row count is asserted against `place`'s own count and printed either way.** A partial
        write is a smaller file that looks like a working export, which is the one failure a
        dataset job has that nobody notices — so the number is in the log and a mismatch raises.
        """
        import boto3

        bucket, prefix = _destination()
        workdir = tempfile.mkdtemp(prefix="upto-dataset-")
        try:
            # The venv's interpreter, because `place_display` needs SQLAlchemy 2.0's async session.
            result = subprocess.run(
                [UPTO_PYTHON, "-m", "upto.dataset.run", workdir],
                env=dict(os.environ, PYTHONPATH=UPTO_SRC, UPTO_DATABASE_URL=_database_url()),
                capture_output=True,
                text=True,
                check=False,
            )
            print(result.stdout)
            if result.returncode != 0:
                print(result.stderr, file=sys.stderr)
                raise RuntimeError(
                    "the dataset export exited {} — nothing was uploaded".format(result.returncode)
                )

            written = {}
            for line in result.stdout.splitlines():
                if line.startswith("dataset:"):
                    key, _, value = line[len("dataset:"):].strip().partition("=")
                    written[key.strip()] = value.strip()

            publication = written["publication"]
            rows = int(written["rows"])
            parquet = os.path.join(workdir, "places.parquet")
            dictionary = os.path.join(workdir, "dictionary.md")

            session = boto3.session.Session()
            connection = BaseHook.get_connection(S3_CONNECTION)
            client = session.client(
                "s3",
                aws_access_key_id=connection.login,
                aws_secret_access_key=connection.password,
                region_name=(connection.extra_dejson or {}).get("region_name", "ap-northeast-1"),
            )
            # The object names come from the module too, for the same reason as the destination.
            from upto.dataset.export import object_names  # noqa: PLC0415

            parquet_key, dictionary_key = object_names(prefix, publication)
            client.upload_file(parquet, bucket, parquet_key)
            client.upload_file(dictionary, bucket, dictionary_key)
            size = os.path.getsize(parquet)
            print(
                "dataset: uploaded s3://{}/{} — {} rows, {:.1f} MB".format(
                    bucket, parquet_key, rows, size / 1024 / 1024
                )
            )
            return {"publication": publication, "rows": rows, "bytes": size}
        finally:
            # `rmtree(ignore_errors=True)`: the point of this block is that nothing is left behind
            # on the unhappy path, and `os.rmdir` fails on a directory the export half-filled —
            # turning a cleanup into a second failure that hides the first.
            shutil.rmtree(workdir, ignore_errors=True)

    export_and_upload()


upto_dataset_export()
