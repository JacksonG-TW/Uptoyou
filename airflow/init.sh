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

# A15 / D115 — the four service roles, created here because a role needs a password and a
# migration cannot hold one. Same delete-then-add idempotence as the Connections below; the GRANTs
# are revision 0032, which runs afterwards and fails with a sentence naming this file if a role is
# missing.
#
# **`upto` stays the owner and no service connects as it.** These four are login roles with no
# rights until 0032 grants them, so creating one changes nothing on its own — the grant is the
# boundary and this is only the identity.
#
# **`ALTER ... WITH PASSWORD` on every run, not just on create.** That is what makes a rotated
# password in `.env` actually take effect, the same property the Connections have: re-running
# `docker compose up airflow-init --force-recreate --no-deps` is the rotation, for a role as much
# as for the CWA key.
echo "airflow-init: creating the four service database roles (D115)"
python - <<'PY'
import os
import psycopg2

ROLES = {
    "upto_api": os.environ["UPTO_API_DB_PASSWORD"],
    "upto_ingest": os.environ["UPTO_INGEST_DB_PASSWORD"],
    "upto_lineage": os.environ["UPTO_LINEAGE_DB_PASSWORD"],
    "upto_erasure": os.environ["UPTO_ERASURE_DB_PASSWORD"],
}
connection = psycopg2.connect(
    host="db", port=5432, dbname=os.environ["POSTGRES_DB"],
    user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
)
connection.autocommit = True
with connection.cursor() as cursor:
    for name, password in ROLES.items():
        if not password:
            raise SystemExit(
                "airflow-init: no password for {} in the environment. Every name in "
                ".env.example must carry a value; a role without a password cannot log "
                "in and revision 0032 would grant to an identity nobody can use.".format(name)
            )
        cursor.execute("select 1 from pg_roles where rolname = %s", (name,))
        if cursor.fetchone() is None:
            cursor.execute('create role "{}" with login password %s'.format(name), (password,))
            print("airflow-init: created role {}".format(name))
        else:
            cursor.execute('alter role "{}" with login password %s'.format(name), (password,))
            print("airflow-init: role {} already existed — password set from .env".format(name))
connection.close()
PY

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
