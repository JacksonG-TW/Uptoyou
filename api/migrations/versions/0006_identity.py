"""Ticket 01's identity tables — `circle`, `principal`, `member`.

Revision ID: 0006
Revises: 0005
Created: 2026-08-12

**Three tables, where the ticket names two, and the third is not a convenience.** Ticket 01
asks for `principal` and `member` "with `member.principal_id` as the only link between them".
D12 defines `member` as *one principal's seat in one circle* and rests its entire cost-benefit
on this sentence: "one device holds one secret covering every circle its owner belongs to;
collapsing the two tables would mean a separate secret per circle — **more** data held, not
less." That argument is true only if one principal can hold several member rows, one per
circle, and the thing that says "one per circle" is `UNIQUE (principal_id, circle_id)`. Without
a `circle_id` there is no such constraint to write, and H10's rule is that a constraint goes in
hand-written with the table that carries it. **A constraint that cannot be written yet is not
deferred; it is absent.** Ruled 2026-08-12, three tables, with `circle` as `id · name ·
created_at`.

**`circle`'s columns were chosen here, not taken from a decision entry.** The project's plan
recorded the node as "Schema 1 — identity and circles · closed — D12", but D12's body only ever
describes `principal` and `member`; the circle appears in it as a phrase. The closure covered the
*split*, not the circle's shape.

**This is not the baseline migration, and D12 says it is.** The build order put ingest first, so
identity arrives at 0006 behind five ingest revisions. Alembic is linear and nothing is wrong
with the schema, but D12's "a separation that would mean rewriting later goes in from the first
migration" is now literally false about this repository and is owed an amendment.

**What is deliberately absent.** Device secrets, account bindings and invite tokens — D12
describes all three (hashed, never plaintext · `UNIQUE(provider, provider_subject_id)` ·
single-use enforced by a conditional update rather than in application code). They are D7's
surface, ticket 01 does not list them, and they are a separate decision rather than the
obvious next step of this one.

**H19 is a property of this file.** Its mitigation reads "no domain table carries a foreign key
to `principal`; `member` is the only one." Every later migration is bound by that, and this is
the file that makes it true to begin with.
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A circle is the durable unit that holds a round (the open room question defers to it),
    # and it is the scope of everything the product domain can see at once.
    op.create_table(
        "circle",
        sa.Column("id", sa.BigInteger, primary_key=True),
        # What the table at the table calls itself. Personal-adjacent by the compliance constraints'
        # standard, so it is the circle's own label and there is no second name column anywhere for
        # a person.
        sa.Column("name", sa.Text, nullable=False),
        # server_default rather than an application default: H10's threat model is "I connect to
        # your database directly", and a row inserted over SQL still has to carry a creation
        # time. timestamptz throughout — H17 forbids a stamp whose zone has to be guessed.
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_circle_name_not_blank"),
    )

    # The authenticated subject, and **it holds no personal data at all** — D12, and the reason
    # H19 can be a structural guarantee rather than a promise. If a column carrying anything
    # about a person is ever proposed here, that is the moment D12 is being reversed, and it is
    # a decision rather than a migration.
    op.create_table(
        "principal",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # One principal's seat in one circle. The nickname lives here, which is what makes it
    # circle-scoped: there is no global display name, so there is no cross-circle correlator —
    # D12's "not a promise that is made but a path that does not exist".
    op.create_table(
        "member",
        sa.Column("id", sa.BigInteger, primary_key=True),
        # No ON DELETE CASCADE on either reference, and that is a choice with a cost. Cascading
        # would make deleting a principal silently erase that person's seats — and a round's
        # snapshot (D15) references members, so the erasure would reach recorded history. With
        # RESTRICT (the default) a delete fails loudly until a deliberate flow exists. **How
        # erasure actually works is unwalked**, and this leaves it open rather than answering it
        # by default.
        sa.Column("principal_id", sa.BigInteger, sa.ForeignKey("principal.id"), nullable=False),
        sa.Column("circle_id", sa.BigInteger, sa.ForeignKey("circle.id"), nullable=False),
        sa.Column("nickname", sa.Text, nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        # The constraint that earns the second table. One seat per circle per principal: several
        # rows for one principal is the multi-circle support D12 calls load-bearing, two rows in
        # the *same* circle is a returning user who was minted twice, which D12 names as the
        # consequence easiest to get wrong — "and nothing errors". After this, something errors.
        sa.UniqueConstraint("principal_id", "circle_id", name="uq_member_one_seat_per_circle"),
        sa.CheckConstraint("length(btrim(nickname)) > 0", name="ck_member_nickname_not_blank"),
    )

    # "Who is at this table" is the domain's most common question and the unique index above
    # cannot serve it — that index leads with `principal_id`, and a principal-leading index is
    # useless for a circle-scoped scan.
    op.create_index("ix_member_circle", "member", ["circle_id"])


def downgrade() -> None:
    op.drop_index("ix_member_circle", table_name="member")
    op.drop_table("member")
    op.drop_table("principal")
    op.drop_table("circle")
