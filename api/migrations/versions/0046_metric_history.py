"""A28 question 1 — `metric_history`, and the read-only check role's grants.

Revision ID: 0046
Revises: 0045

*Owner-ruled 2026-09-15 (decision-log «A28 question 1, value-level anomaly checks — the light
option» and «A28's checks read through a new read-only check role, not `upto_ingest`»).*

**The table.** One row per metric per check run: which source, which metric, the value the
statement returned, the line it was held against, the verdict (`ok` · `alert` · `recorded` — the
last for a value that carries no line, such as a count A10 already alerted on), and a sentence.
≈ 315 rows a night (the weather pair records six metrics an hour) at 169 bytes each with the index,
≈ 19 MB a year, measured on a scratch table
2026-09-15 (`idea & img/research/human-facing-governance-research.md` §1.3). It is owned by the
owner like every table; the check role may insert into it and may NOT read it (no statement
reads it, the insert returns nothing); nobody reads it yet — it is `roles.OWNER_ONLY`'s one entry.

**The role.** `upto_check` is a LOGIN role created by `upto.roles.ensure()` from
`UPTO_CHECK_DB_PASSWORD` — the entrypoint runs `ensure()` before `alembic upgrade`, so on an
existing database the role exists when this revision grants to it, and on a fresh database
revision 0032 has already granted it SELECT on every table in `roles.CHECK_READ` that existed then.
This revision issues the whole list again (GRANT is idempotent) so the two paths end in the same
state, and adds the one table 0032 could not know: `metric_history`, with USAGE on the sequence
its `bigserial` needs (USAGE alone: `nextval` is all an insert calls). **SELECT on exactly
`CHECK_READ`, INSERT on `metric_history` and nothing else there, no UPDATE or DELETE anywhere** — `tests/test_role_grants.py` asserts it in both directions, and
`tests/test_value_check_integration.py` proves the refusals as the role itself.

**Why the role is in `SERVICE_ROLES` and the sweeper is not.** The sweeper (0045) is NOLOGIN and
owns functions; its grants are its own day's list. The check role logs in like the other four and
its reach is a table list, which is exactly what `roles.grants()` and the coverage test are for.

**Downgrade** revokes everything this revision granted to the role and drops the table; the role
stays (a role is cluster-wide and revision 0032's rule is that migrations never create or drop
one).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None


def _roles():
    """`upto.roles`, the same way revision 0032 reads it — the list of the day the migration runs."""
    import sys

    sys.path.insert(0, "/srv/src")
    from upto import roles as role_map  # noqa: PLC0415

    return role_map


def upgrade() -> None:
    role_map = _roles()
    connection = op.get_bind()

    op.create_table(
        "metric_history",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("metric", sa.Text, nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("publication_id", sa.BigInteger, nullable=True),
        # NULL when the statement had nothing to return (a source with no publication yet): an
        # absence is recorded as an absence, never as 0.
        sa.Column("value", sa.Float, nullable=True),
        sa.Column("threshold", sa.Float, nullable=True),
        sa.Column("verdict", sa.Text, nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.CheckConstraint("verdict in ('ok', 'alert', 'recorded')", name="ck_metric_history_verdict"),
    )
    op.create_index("ix_metric_history_source_metric_time", "metric_history", ["source", "metric", "observed_at"])

    role = role_map.CHECK
    exists = connection.execute(
        sa.text("select 1 from pg_roles where rolname = :n"), {"n": role}
    ).scalar_one_or_none()
    if exists is None:
        raise RuntimeError(
            "the role {} does not exist. It is created by `upto.roles.ensure()` from "
            "UPTO_CHECK_DB_PASSWORD in app/.env (the migrate entrypoint runs it first); add the "
            "name to .env, then re-run `docker compose run --rm migrate`.".format(role)
        )
    op.execute(sa.text('grant usage on schema public to "{}"'.format(role)))
    for table, privileges in sorted(role_map.grants()[role].items()):
        if connection.execute(
            sa.text("select to_regclass(:t)"), {"t": "public." + table}
        ).scalar_one_or_none() is None:
            continue
        op.execute(sa.text('grant {} on "{}" to "{}"'.format(", ".join(privileges), table, role)))
    op.execute(sa.text('grant usage on sequence "metric_history_id_seq" to "{}"'.format(role)))


def downgrade() -> None:
    role_map = _roles()
    role = role_map.CHECK
    op.execute(sa.text('revoke all on all tables in schema public from "{}"'.format(role)))
    op.execute(sa.text('revoke all on all sequences in schema public from "{}"'.format(role)))
    op.execute(sa.text('revoke usage on schema public from "{}"'.format(role)))
    op.drop_index("ix_metric_history_source_metric_time", table_name="metric_history")
    op.drop_table("metric_history")
