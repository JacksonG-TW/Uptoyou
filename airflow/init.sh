#!/bin/bash
# One-shot bootstrap: migrate Airflow's own database, create the admin, and create the two
# Connections the DAG reads.
#
# D33 is the whole point of this file. The CWA key and the application database arrive here
# once, as Connections, Fernet-encrypted in Airflow's metadata database. After this runs, no
# task reads either from the environment — and the only environment variables left are the
# ones that bootstrap Airflow itself, which is the exception D33 names.
set -euo pipefail

echo "airflow-init: migrating the metadata database"
airflow db migrate

echo "airflow-init: setting the admin password"
# `airflow users create` is not this Airflow's command. It belongs to the FAB auth manager of
# Airflow 2; Airflow 3 defaults to the simple auth manager, which has no user table and no
# such subcommand. The call printed the CLI help and created nothing — and because it was
# written as `2>/dev/null || echo "admin already exists"`, the log said the opposite and the
# UI rejected the password in .env for three commits. Nothing here masks a failure any more —
# the two `|| true` below are an expected absence on a first run, not a discarded error, and
# every other command is left to `set -e`.
#
# Under the simple auth manager the *user list* is configuration — core.simple_auth_manager_users,
# which already defaults to `admin:admin` — and only the password is state. The api-server
# reads the file below on start and invents a random password for any listed user missing from
# it, printing it once to its own log. Writing the file first is what makes the password the
# one in .env, and keeps it that way across `docker compose down`.
python - <<'PY'
import json
import os

path = os.environ["AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE"]
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as file:
    json.dump({"admin": os.environ["AIRFLOW_ADMIN_PASSWORD"]}, file)
    file.write("\n")
os.chmod(path, 0o600)
print(f"airflow-init: admin password written to {path}")
PY

# **The four service roles are NOT created here, and that is a correction rather than an omission.**
# A15 first put them in this file; `tools/split_boot_check.sh` failed on the first fresh clone it
# saw, because nothing orders `airflow-init` against the `migrate` service and revision 0032 reached
# its GRANTs before the roles existed. They are created by `migrate`, as the owner, immediately
# before the migration that grants to them — see `api/src/upto/roles.py`. What stays here is this
# file's own job: carrying two of those credentials to the DAGs as Airflow Connections (D33).
echo "airflow-init: creating connections"
# Deleting first makes this idempotent; `add` alone fails on a second run.
airflow connections delete upto_postgres >/dev/null 2>&1 || true
airflow connections add upto_postgres \
    --conn-type postgres \
    --conn-host db \
    --conn-port 5432 \
    --conn-schema "${POSTGRES_DB}" \
    --conn-login "${POSTGRES_USER}" \
    --conn-password "${POSTGRES_PASSWORD}"

# **The pipeline's own connection, and it is not `upto_postgres`.** D115 gives the DAGs
# `upto_ingest`, which cannot read a person. `upto_postgres` stays as the owner's connection for
# anything that legitimately needs it; every ingest DAG reads the one below.
airflow connections delete upto_ingest_postgres >/dev/null 2>&1 || true
airflow connections add upto_ingest_postgres \
    --conn-type postgres \
    --conn-host db \
    --conn-port 5432 \
    --conn-schema "${POSTGRES_DB}" \
    --conn-login upto_ingest \
    --conn-password "${UPTO_INGEST_DB_PASSWORD}"

# **The erasure job's own connection — the narrowest role in the product.** SELECT and DELETE on
# `preference`, SELECT on `weight_contribution` so it can leave a pinned version alone (D24), and
# nothing else at all. Owner-ruled 2026-08-27 against running the job as `upto_api`: a scheduled
# deletion should hold exactly the capability it needs and no more.
airflow connections delete upto_erasure_postgres >/dev/null 2>&1 || true
airflow connections add upto_erasure_postgres \
    --conn-type postgres \
    --conn-host db \
    --conn-port 5432 \
    --conn-schema "${POSTGRES_DB}" \
    --conn-login upto_erasure \
    --conn-password "${UPTO_ERASURE_DB_PASSWORD}"

# **A22's backup role — read everything, change nothing.** `pg_read_all_data` and no write grant
# anywhere (revision 0038). It is NOT the owner: the nightly `pg_dump` runs inside the long-lived
# scheduler, and D115 says only a job that exits may hold the owner. Created unconditionally, the
# same as the other three — an absent bucket turns the *DAG* off (below), and a missing Connection
# would turn it red instead, which is the wrong signal for a stack that simply has no S3.
airflow connections delete upto_backup_postgres >/dev/null 2>&1 || true
airflow connections add upto_backup_postgres \
    --conn-type postgres \
    --conn-host db \
    --conn-port 5432 \
    --conn-schema "${POSTGRES_DB}" \
    --conn-login upto_backup \
    --conn-password "${UPTO_BACKUP_DB_PASSWORD}"

# **A22's destination credential (D61's scoped IAM key), and absent is legal here too.** The bucket
# name is configuration and rides the environment; the key is a secret and rides this Connection,
# read once by this file and by no task afterwards (D33/H16). A stack with no AWS account creates
# nothing and the backup DAG skips on the empty bucket before it ever asks for this.
airflow connections delete upto_backup_s3 >/dev/null 2>&1 || true
if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
    airflow connections add upto_backup_s3 \
        --conn-type aws \
        --conn-login "${AWS_ACCESS_KEY_ID}" \
        --conn-password "${AWS_SECRET_ACCESS_KEY}" \
        --conn-extra "{\"region_name\": \"ap-northeast-1\"}"
    echo "airflow-init: upto_backup_s3 created — the nightly dump has somewhere to go"
else
    echo "airflow-init: no AWS key in the environment, so upto_backup_s3 was NOT created — the nightly backup will skip on its empty bucket (A22: absent is legal)"
fi

airflow connections delete cwa_open_data >/dev/null 2>&1 || true
airflow connections add cwa_open_data \
    --conn-type http \
    --conn-host opendata.cwa.gov.tw \
    --conn-password "${UPTO_CWA_API_KEY}"

# A10's alert channel. **Absent is legal, and that is the whole design of the callback.** A fresh
# clone, and `tools/split_boot_check.sh`'s isolated stack, have no bot — so the two variables are
# read with a default and the Connection is simply not created when either is empty. The callback
# prints a line to the task log and returns; alerting is off on a stack nobody is watching, which
# is correct rather than degraded.
#
# **Rotating the token is three places, the same shape the CWA key carries** — `~/.keys/`, `.env`,
# and this Fernet-encrypted Connection, which keeps the old value until
# `docker compose up airflow-init --force-recreate --no-deps` re-runs this file. Delete-then-add
# is what makes that idempotent.
airflow connections delete telegram_alerts >/dev/null 2>&1 || true
if [[ -n "${UPTO_TELEGRAM_BOT_TOKEN:-}" && -n "${UPTO_TELEGRAM_CHAT_ID:-}" ]]; then
    airflow connections add telegram_alerts \
        --conn-type http \
        --conn-host api.telegram.org \
        --conn-login "${UPTO_TELEGRAM_CHAT_ID}" \
        --conn-password "${UPTO_TELEGRAM_BOT_TOKEN}"
    echo "airflow-init: telegram_alerts created — failed tasks will send one message each"
else
    echo "airflow-init: no telegram token or chat id in the environment, so telegram_alerts was NOT created — failure alerting is off on this stack (A10: absent is legal)"
fi

echo "airflow-init: done — connections are stored encrypted, not in the environment of any task"
