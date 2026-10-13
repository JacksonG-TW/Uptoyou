"""Ticket 09 — a run leaves a record, including the runs that wrote nothing.

Revision ID: 0005
Revises: 0004
Created: 2026-08-11

**Why this table has to exist before the lineage tool does.** Ticket 09 requires that a model
can ask what a given run wrote *including a run that wrote nothing*, and that a run which
detected no change is "lineage worth pointing at, not an absence". Until now a no-op wrote
literally nothing: item 10 has run about two dozen times and left 1 forecast publication and
6 observation publications, so roughly twenty runs are unrecoverable. D42 made the silent
no-op correct behaviour; it did not make it invisible on purpose, and item 14 is where the
difference starts to matter.

**The publication reference follows D24's pattern rather than inventing one.** D24 pins a
source with a real foreign key and one nullable column per source, because a text column
naming a table is a join nothing can enforce. There are three publication tables, so there are
three nullable columns and a CHECK that at most one is set — and exactly one when the run
stored something.

**What this table is not.** It is not the publication and it does not identify one: D18 and
D35 rule that a publication is identified by its content, and the run stands in only where the
source offers no way to identify one. This records *the attempt* — when it ran, what it found,
and which publication it landed on if any. A run is metadata about our own behaviour; a
publication is a fact about the source.

**Needs a D-number.** The requirement is the ticket's and the shape is this migration's, so
there is no defence entry to point at yet. Recorded as owed rather than left to be
discovered.
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_run",
        sa.Column("id", sa.BigInteger, primary_key=True),
        # The dataset or file this run was about: F-D0047-061, O-A0001-001, or the FDA source.
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        # stored     — the content was new and a publication was written
        # no_change  — the source republished nothing; a success, and the ordinary outcome
        # failed     — the source did not answer usefully. Not the same as no_change, and the
        #              whole reason both are recorded rather than inferred from an absence.
        sa.Column("outcome", sa.Text, nullable=False),
        # **Rows the database accepted as NEW — clarified 2026-08-18, H32's second half.** The
        # name invites a wrong sum and the wrong sum has a name: a rows-only replay rebuilds every
        # row of a table and records `no_change` with 0 here, because the claim short-circuits on
        # a hash it already holds and `ck_ingest_run_rows_only_when_stored` refuses a count on any
        # other outcome. So `sum(rows_written)` reads a backfill as a no-op, and the rebuild lives
        # in `detail`. Ruled 2026-08-18: **this is documented rather than fixed** — a replay is a
        # human recovery action and the human is the reader. **Flip condition:** the day a replay
        # is automated, a separate `rows_rewritten integer` column (NULL, not 0, on runs that
        # replayed nothing) becomes the right answer — not a new `outcome` value, which would make
        # this column answer two independent questions.
        sa.Column("rows_written", sa.Integer, nullable=False, server_default="0"),
        # The verdict the runner printed, stored so the lineage answer quotes the run rather
        # than reconstructing it. Nothing downstream may compute this.
        sa.Column("detail", sa.Text, nullable=True),
        # Who invoked it — 'airflow' or 'cli'. Lineage over a manual run and a scheduled one
        # are different answers to "why does this row exist".
        sa.Column("invoked_by", sa.Text, nullable=True),
        # D24's pattern: a real foreign key per source rather than a table name in a text
        # column, which is a join no constraint can check.
        sa.Column("forecast_publication_id", sa.BigInteger, nullable=True),
        sa.Column("observation_publication_id", sa.BigInteger, nullable=True),
        sa.Column("place_publication_id", sa.BigInteger, nullable=True),
        sa.ForeignKeyConstraint(
            ["forecast_publication_id"], ["forecast_publication.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["observation_publication_id"], ["observation_publication.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["place_publication_id"], ["place_publication.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "outcome in ('stored', 'no_change', 'failed')", name="ck_ingest_run_outcome"
        ),
        sa.CheckConstraint(
            "num_nonnulls(forecast_publication_id, observation_publication_id, "
            "place_publication_id) <= 1",
            name="ck_ingest_run_one_publication",
        ),
        # A stored run without a publication would be a claim with nothing behind it, and a
        # no-op with one would mean the outcome and the row disagree. Both are refused here
        # rather than in code, because the writer that gets this wrong may not be this code.
        sa.CheckConstraint(
            "(outcome = 'stored') = (num_nonnulls(forecast_publication_id, "
            "observation_publication_id, place_publication_id) = 1)",
            name="ck_ingest_run_stored_has_publication",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at", name="ck_ingest_run_finished_after_started"
        ),
        sa.CheckConstraint(
            "(outcome = 'stored') or rows_written = 0", name="ck_ingest_run_rows_only_when_stored"
        ),
    )
    # The two questions asked of this table: what happened to this source lately, and what did
    # this run do.
    op.create_index("ix_ingest_run_source_time", "ingest_run", ["source", "started_at"])


def downgrade() -> None:
    op.drop_table("ingest_run")
