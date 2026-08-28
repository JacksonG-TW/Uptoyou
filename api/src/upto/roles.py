"""A15 / D115 — which role may do what to which table, as one map.

**This module is the only place the boundary is written down.** The migration that issues the
GRANTs and the test that checks their coverage both import it, so the two cannot disagree — the
same reason `_SINGLE_BRAND_RULE` exists one file over. A boundary spelled twice is a boundary that
drifts, and a permissions boundary that drifts is one nobody notices has moved.

**H10's rule extends to grants (D115's cost paragraph):** a new table ships with its constraint
*and* with its line here, or it is unreachable by every service and the coverage test says so. That
test is the mechanism — a table added without a line below turns it red rather than leaving a
silent hole, which is the whole reason the map is data and not prose.

**The three boundaries are the record's, not new ones.**

- `upto_api` — the product's own tables, and read-only on everything the pipeline publishes. It may
  not do DDL and may not `TRUNCATE`; H32's triggers stay as the second line for the owner.
- `upto_ingest` — publications, the ledger, the reference rows and the classifier's columns. It may
  touch **nothing** that names a person: §3.0 and D14 say the pipeline never sees one, and since
  A15 the database says it too.
- `upto_lineage` — SELECT on exactly what `lineage.queries.READABLE_TABLES` names. H20's boundary
  was a Python list; it is a GRANT now and the list is the second line.

**`upto` stays the owner and no service connects as it** — Alembic, the build-and-drop tests and an
operator's psql, and that is all.
"""

from __future__ import annotations

API = "upto_api"
INGEST = "upto_ingest"
LINEAGE = "upto_lineage"
ERASURE = "upto_erasure"

#: Every login role this file grants to. `upto` is deliberately absent: it owns the tables.
SERVICE_ROLES = (API, INGEST, LINEAGE, ERASURE)

WRITE = ("select", "insert", "update", "delete")
READ = ("select",)
APPEND = ("select", "insert")

# **The product's tables: a person, a circle, a round, and what a round produced.** `circle` carries
# no writer in the application today — no endpoint creates one — and is granted anyway because
# D115's row says so; the absence is recorded here rather than silently narrowing the ruling.
API_WRITE = (
    "circle",
    "principal",
    "member",
    "member_roll",
    "device_secret",
    "preference",
    "round",
    "proposal",
    "weight_contribution",
    "round_forecast_baseline",
    "trip",
)

# **`place` is INSERT-and-SELECT for the API and D115's first table said SELECT** — corrected on
# 2026-08-27 from the code rather than from the ruling's prose: `live.py` inserts a `circle-local`
# place when a member proposes somewhere the reference list has never heard of, and inserts a
# `reference` place row the first time one is proposed. **Never UPDATE** — the classifier's category
# columns are the pipeline's, on the same table, under a different role's grant (D28's two origins).
API_APPEND = ("place",)

# What the API reads and never writes: everything the pipeline publishes, plus the ledger. A member
# picks from these; nothing on a request path may change them.
REFERENCE_TABLES = (
    "place_publication",
    "reference_place",
    "forecast_publication",
    "forecast_reading",
    "observation_publication",
    "observation_reading",
    "brand_publication",
    "brand_registration",
    "storefront_publication",
    "storefront_name",
    "business_status_publication",
    "business_status_row",
    "business_tax_publication",
    "business_tax_row",
    "search_alias",
    "township_station",
    # A19: the pipeline writes it, the request path reads it, and nobody else touches it — the same
    # shape as every other thing a publication carries.
    "product_material",
)

# The pipeline writes what it publishes, the ledger that records the writing, and the crib.
INGEST_WRITE = REFERENCE_TABLES + ("ingest_run", "place", "example_embedding")

# **The pipeline may not name a person.** Listed rather than derived as "everything else", because a
# deny list that is a subtraction stops being checkable the moment a table is added — this one is
# asserted against the map's own totals by the coverage test.
INGEST_DENIED = (
    "circle",
    "principal",
    "member",
    "member_roll",
    "device_secret",
    "preference",
    "round",
    "proposal",
    "weight_contribution",
    "round_forecast_baseline",
    "trip",
)

# Alembic's own bookkeeping. **The one exception in this file, and it is short on purpose:** a second
# entry has to be argued for, because "the coverage test skips it" is how a table becomes invisible.
OWNER_ONLY = ("alembic_version",)


# **`upto_erasure` — the narrowest role here, and it needs one table more than its ruling names.**
# Owner-ruled 2026-08-27 as *SELECT and DELETE on `preference` and nothing else*, for
# `upto_preference_erasure` (D17/D25/H22). **The job cannot run on that alone.** `privacy.erase`'s
# `UNPINNED` clause is
#
#     not exists (select 1 from weight_contribution wc where wc.preference_id = preference.id)
#
# and it is not decoration: D24 makes a preference version a round pinned undeletable, and the job
# **filters those rows out itself** rather than letting the delete fail — a job that raised on the
# first pinned row would erase nothing after it, turning a partial privacy obligation into none.
# So this role reads `weight_contribution` and can do nothing else to it.
#
# **Read as an inference and flagged as one:** the ruling's own Done line asks that **UPDATE** on
# `weight_contribution` be refused for this role, not SELECT, which is what a reading that intended
# SELECT to be available would say. Sent to orchestrator on landing as the one grant here taken from
# the Done line's wording plus the code rather than from the rule's sentence. One line to correct.
# **Two weather tables added 2026-08-28 (D42's retention amendment).** The 90-day job runs as this
# role and not as `upto_ingest`, which already holds DELETE on both — because its `UNPINNED` filter
# must read `weight_contribution`, and D115 gives the pipeline **nothing** there: §3.0 and D14 say
# the pipeline never sees a person. Granting that SELECT to widen the ingest role would undo the
# exact line A15 was built to draw, so the job comes to the role that already holds it.
#
# *Cost, recorded rather than assumed away:* this role's reach grows from one person-bearing table
# to two pipeline tables, and a weather reading is **not re-fetchable** — CWA publishes the current
# file, not an archive — so a bad line in that DAG destroys something a re-run cannot restore.
# *Rejected:* a fifth role — one more password and D115's own warning that the next role must argue
# better than the fourth did, spent to protect data from the job whose purpose is deleting it.
ERASURE_GRANTS = {
    "preference": ("select", "delete"),
    "weight_contribution": READ,
    "observation_reading": ("select", "delete"),
    "forecast_reading": ("select", "delete"),
    # The 90-day filter reads this to know a forecast reading is a round's pinned baseline
    # (A12/D71, revision 0030). SELECT only: this role may never touch a round's own rows.
    "round_forecast_baseline": READ,
    # The window is the publication's `detected_at`, so the job joins to both publication tables.
    # SELECT only — publication rows are the ledger and stay for ever (M2 reads them).
    "observation_publication": READ,
    "forecast_publication": READ,
}


def grants() -> dict:
    """`{role: {table: (privilege, ...)}}` — what the migration issues and the test checks."""
    api = {t: WRITE for t in API_WRITE}
    api.update({t: APPEND for t in API_APPEND})
    api.update({t: READ for t in REFERENCE_TABLES})
    # D115: SELECT on the ledger and no more — the API may read what an ingest wrote, never write it.
    api["ingest_run"] = READ

    ingest = {t: WRITE for t in INGEST_WRITE}

    # The lineage tool's reach, taken from the tool's own declaration so the two cannot part company.
    from .lineage.queries import READABLE_TABLES  # noqa: PLC0415 — avoids an import cycle at module load

    lineage = {t: READ for t in sorted(READABLE_TABLES)}
    return {API: api, INGEST: ingest, LINEAGE: lineage, ERASURE: dict(ERASURE_GRANTS)}


# ---------------------------------------------------------------------------
# Creating the roles, and why it happens HERE rather than in `airflow/init.sh`.
#
# **A15 first put role creation in `init.sh`, and `split_boot_check.sh` caught it on the first
# fresh clone it ever saw.** `migrate` waits only on `db`, `airflow-init` waits only on `db`, and
# nothing orders the two — so on a stack that had never run before, revision 0032 reached its GRANTs
# before the roles existed and the whole boot failed with `service "migrate" didn't complete
# successfully: exit 1`. On the developer's machine it had worked, because the roles had been
# created by hand minutes earlier. **That is the gate doing exactly its job**, and the fix is not an
# ordering edge between the product's schema and Airflow's bootstrap — it is putting the roles where
# they belong.
#
# So: the **owner** creates them, in the same one-shot service that owns database bootstrap and
# immediately before the migration that grants to them. `init.sh` keeps what is actually its own —
# the Airflow Connections that carry two of these credentials to the DAGs.
#
# **Idempotent, and `alter` on every run is the point:** a rotated password in `.env` takes effect
# on the next `up`, the same property the Connections have.

_PASSWORD_VARS = {
    API: "UPTO_API_DB_PASSWORD",
    INGEST: "UPTO_INGEST_DB_PASSWORD",
    LINEAGE: "UPTO_LINEAGE_DB_PASSWORD",
    ERASURE: "UPTO_ERASURE_DB_PASSWORD",
}


def ensure() -> int:
    """Create or re-password the four login roles. Run as the owner, before the grants.

    **asyncpg, not psycopg2, and not because it is tidier.** H1 rules the synchronous driver out of
    this codebase entirely, and the api image carries only `asyncpg` — the first version of this
    function used `psycopg2` (copied from `init.sh`, where the *Airflow* image happens to have it)
    and `split_boot_check.sh` failed a second time with `ModuleNotFoundError` inside `migrate`. Two
    fresh-clone failures from one ruling, both invisible on a machine where the work had already
    been done by hand.

    **The password is quoted by the server, not by us.** PostgreSQL does not accept bind parameters
    in `CREATE ROLE` — it is a utility statement, so a real prepared statement fails, which is why
    the psycopg2 version appeared to work (that driver interpolates client-side). `quote_literal`
    is Postgres's own escaping, asked of the server and pasted back; the role names are this
    module's own constants and never come from outside.
    """
    import asyncio
    import os
    import sys

    import asyncpg

    from .db import DATABASE_URL_VAR

    url = os.environ.get(DATABASE_URL_VAR)
    if not url:
        print("roles: {} is not set".format(DATABASE_URL_VAR), file=sys.stderr)
        return 1

    async def run() -> int:
        # asyncpg speaks libpq's URL; SQLAlchemy's driver suffix is not part of it.
        connection = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            for name, variable in _PASSWORD_VARS.items():
                password = os.environ.get(variable)
                if not password:
                    print(
                        "roles: no password for {} in {}. Every name in .env.example must carry a "
                        "value — a role without one cannot log in, and revision 0032 would grant "
                        "to an identity nobody can use.".format(name, variable),
                        file=sys.stderr,
                    )
                    return 1
                quoted = await connection.fetchval("select quote_literal($1)", password)
                exists = await connection.fetchval(
                    "select 1 from pg_roles where rolname = $1", name
                )
                verb = "alter" if exists else "create"
                await connection.execute(
                    '{} role "{}" with login password {}'.format(verb, name, quoted)
                )
                print(
                    "roles: {} {}".format(
                        name,
                        "already existed — password set from the environment"
                        if exists
                        else "created",
                    )
                )
            return 0
        finally:
            await connection.close()

    return asyncio.run(run())


if __name__ == "__main__":
    import sys

    sys.exit(ensure())
