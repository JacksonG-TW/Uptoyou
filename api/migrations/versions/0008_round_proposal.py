"""Ticket 12 — `round` and `proposal`: the lifecycle half, without the weights.

Revision ID: 0008
Revises: 0007
Created: 2026-08-13

**A room is a round (D52), and the schema says the circle half out loud:** at most one open
round per circle is a partial unique index over unclosed rounds — D52 names the mechanism, this
file writes it. Between rounds a circle simply has no open round; there is no room row anywhere.

**The round carries the meal's hour (D16) and how it was chosen (D41).** A typed hour is fixed;
a defaulted one re-resolves at the roll. The boolean is stored because at roll time the two are
indistinguishable without it, and re-resolving a typed hour silently replaces a fact a person
stated.

**Authorship dies at the close, in the database, in the same transaction (D14).** The close
handler updates a status; the trigger below nulls `proposal.member_id` for that round. It is a
trigger and not application code because a manual close over SQL, a fix-up script, or a second
code path would all leave authorship behind, and none of them would error. D14 admits the
instrument is weaker than a CHECK — a trigger mutates rather than rejects, and Alembic drops
triggers silently on autogenerate, which is why this file is hand-written and read whole.

**The 1–3 cap (a member proposes at most three places a round) is enforced here too, by a constraint
trigger,** because it is the reason authorship exists at all before the close, and D13's standard is
that a rule the application enforces alone is not a rule. Counting rows across a table is beyond
CHECK, so it is the same weaker instrument as the erasure, admitted rather than glossed.

**What is deliberately absent:** the weight contributions and the materialised per-place
weights — D15's snapshot. They arrive with the engine's write half, because the write-time
reconciliation D15 demands is the engine's act, and a table with no writer yet is a promise
(document-architecture's rule, applied to schema). The winner column is here because the
close needs it (D53: a close is pushed once, with its result), with the one CHECK that can
already be written: an open round has no winner and no close time.

**Admitted, application-enforced for now:** the proposing member belongs to the round's
circle. Stating it in the schema needs a composite key duplicated across three tables; the
API resolves the member through the circle on every write anyway (D67), and the integration
test states the gap so it is a recorded debt rather than an assumption.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "round",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("circle_id", sa.BigInteger, nullable=False),
        # The hour the meal happens (D16) — the weights read the record describing this hour.
        sa.Column("target_hour", sa.DateTime(timezone=True), nullable=False),
        # D41: a typed hour is fixed; a defaulted one re-resolves at the roll.
        sa.Column("target_hour_typed", sa.Boolean, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'open'")),
        # D53: the close is pushed once, with its result. The winner is a place row (D28).
        sa.Column("winning_place_id", sa.BigInteger, nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # D54: the boundary is an event, not a duration — closed_at records when, never expiry.
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["circle_id"], ["circle.id"], name="fk_round_circle"),
        sa.ForeignKeyConstraint(["winning_place_id"], ["place.id"], name="fk_round_winner"),
        sa.CheckConstraint("status in ('open', 'closed')", name="ck_round_status"),
        # An open round has no result and no close time. The reverse is not claimed: what a
        # close without a roll means (a cancel) is unruled, and this CHECK leaves it open.
        sa.CheckConstraint(
            "status <> 'open' or (winning_place_id is null and closed_at is null)",
            name="ck_round_open_shape",
        ),
        sa.CheckConstraint(
            "status <> 'closed' or closed_at is not null",
            name="ck_round_closed_has_time",
        ),
    )
    # D52's mechanism, verbatim: at most one open round per circle, said by the schema.
    op.create_index(
        "uq_round_one_open_per_circle",
        "round",
        ["circle_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )

    op.create_table(
        "proposal",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("round_id", sa.BigInteger, nullable=False),
        sa.Column("place_id", sa.BigInteger, nullable=False),
        # Nullable is the retention rule stated in the schema (D14): null for any closed round.
        sa.Column("member_id", sa.BigInteger, nullable=True),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["round_id"], ["round.id"], name="fk_proposal_round"),
        sa.ForeignKeyConstraint(["place_id"], ["place.id"], name="fk_proposal_place"),
        sa.ForeignKeyConstraint(["member_id"], ["member.id"], name="fk_proposal_member"),
        # D70: the pool holds one entry per place; a repeat proposal is the API's quiet success.
        sa.UniqueConstraint("round_id", "place_id", name="uq_proposal_place_per_round"),
    )

    # D14: closing a round erases its proposals' authorship, in the same transaction.
    op.execute(
        """
        create function erase_proposal_authorship() returns trigger
        language plpgsql as $$
        begin
            update proposal set member_id = null where round_id = new.id;
            return new;
        end
        $$
        """
    )
    op.execute(
        """
        create trigger round_close_erases_authorship
        after update of status on round
        for each row
        when (old.status = 'open' and new.status = 'closed')
        execute function erase_proposal_authorship()
        """
    )

    # The cap: one member proposes at most three places in a round. A count across rows is
    # beyond CHECK, so it is a trigger — D13's standard held with D14's admitted instrument.
    op.execute(
        """
        create function enforce_proposal_cap() returns trigger
        language plpgsql as $$
        begin
            if new.member_id is not null and (
                select count(*) from proposal
                where round_id = new.round_id and member_id = new.member_id
            ) >= 3 then
                raise exception 'member % already holds 3 proposals in round % (§3.0)',
                    new.member_id, new.round_id;
            end if;
            return new;
        end
        $$
        """
    )
    op.execute(
        """
        create trigger proposal_cap
        before insert on proposal
        for each row
        execute function enforce_proposal_cap()
        """
    )


def downgrade() -> None:
    op.drop_table("proposal")
    op.drop_table("round")
    op.execute("drop function if exists erase_proposal_authorship()")
    op.execute("drop function if exists enforce_proposal_cap()")
