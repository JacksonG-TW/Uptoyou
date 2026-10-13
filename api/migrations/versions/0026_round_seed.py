"""D108's seed commitment, and the tap that reveals it.

Revision 0026, written 2026-08-19 on the owner's ruling (「採用」, `34e8e61`).

**Two columns on `round` and one new table, and the shape of each is an argument.**

`round.seed_commit` — `sha256(seed)` as hex, published from the moment the round opens. This is the
only part of the commitment that may leave the server before close.

`round.outcome_seed` — the 32 bytes themselves. **Server-side only until the round is closed.** A
member holding the seed early can compute the winner and then choose whether to tap, which is
precisely the preference D91 forbids — the same last-revealer attack that ruled out per-member
commit–reveal. The schema cannot enforce that (a column does not know who is reading it); it is
enforced in `api_common`, and the tests assert it over the wire.

**Both nullable, and NULL means the round predates A6.** Nothing is backfilled — the same rule
revision 0021 used for `column_signature`. An old round has no commitment and can never acquire one
honestly, because a commitment made after the places were known is not a commitment.

**`ck_round_seed_pair_whole` keeps the two together.** A `seed_commit` with no seed is a promise
nobody can check; a seed with no commitment is a number nobody promised. Either alone is worse than
neither, so the CHECK is a biconditional rather than two nullable columns that happen to agree.

**`member_roll` stores the tap and NOT the dice, which is the decision worth arguing.**

A member's pair is *derived* from the seed by `upto.engine.draw.pair_for_member`. Storing it as well
would create a second source for the same fact, and the two could disagree — after a restore, after
an edit, after a bug. The round's `die1/die2` are stored because they are the *result* and D69
requires a second roll to return the stored one; a member's own pair is not a result, it is a view of
the seed. So the table records **that** a member tapped and **when**, and the dice come from the
seed every time they are asked for.

Consequence, stated so nobody discovers it: **lose the seed and every pair is gone**, including the
closed rounds'. That is accepted deliberately — the same seed is what makes the round verifiable at
all, so a design that survives losing it would be a design where the dice were never provably fair.

`UNIQUE (round_id, member_id)` makes a second tap idempotent per person, which is D69 applied to a
member rather than to a round. The composite foreign keys are B2's pin: a roll cannot belong to a
member of one circle and a round of another.
"""

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("round", sa.Column("seed_commit", sa.CHAR(64), nullable=True))
    op.add_column("round", sa.Column("outcome_seed", sa.LargeBinary(), nullable=True))
    op.create_check_constraint(
        "ck_round_seed_pair_whole",
        "round",
        "(outcome_seed is null) = (seed_commit is null)",
    )

    op.create_table(
        "member_roll",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("round_id", sa.BigInteger(), nullable=False),
        sa.Column("circle_id", sa.BigInteger(), nullable=False),
        sa.Column("member_id", sa.BigInteger(), nullable=False),
        sa.Column("rolled_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        # **The composite pins, not two independent references.** Without them a roll could name a
        # member of one circle and a round of another, and every anonymity argument rests on
        # a roll belonging to exactly one circle's round. Same shape as `trip`'s (B2).
        sa.ForeignKeyConstraint(
            ["circle_id", "member_id"], ["member.circle_id", "member.id"],
            name="fk_member_roll_member", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["circle_id", "round_id"], ["round.circle_id", "round.id"],
            name="fk_member_roll_round", ondelete="CASCADE",
        ),
        # One tap per member per round. A second tap is the same tap — D69 per person.
        sa.UniqueConstraint("round_id", "member_id", name="uq_member_roll_once"),
    )
    # The seat list is read in member order for every open round, on every snapshot and every
    # reconnect (D56), so it is the one access path worth an index.
    op.create_index("ix_member_roll_round", "member_roll", ["round_id", "member_id"])


def downgrade() -> None:
    op.drop_index("ix_member_roll_round", table_name="member_roll")
    op.drop_table("member_roll")
    op.drop_constraint("ck_round_seed_pair_whole", "round", type_="check")
    op.drop_column("round", "outcome_seed")
    op.drop_column("round", "seed_commit")
