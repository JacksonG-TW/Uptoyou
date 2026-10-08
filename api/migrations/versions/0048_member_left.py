"""A seat can be left: `member.has_left`, a flag and nothing more (named `has_left` because LEFT is an SQL keyword) (owner 「可以」, 2026-10-08).

When a device moved to another circle its old seat stayed for ever — one of the old circle's ten,
in its seat list, and in the way of the person's own return if that circle was full. Leaving
marks the seat; it deletes nothing. Past rounds, rolls, trips and proposals keep pointing at the
row, which is what a verifiable past needs, and the person's principal and key are untouched
because one principal can sit in several circles.

**A boolean, not a timestamp.** «When this person left this circle» would be a new fact recorded
about a person, and nothing needs it: the cap, the seat list and the next round's seats only ask
whether the seat is taken. The owner's privacy class — what is recorded about people — is why the
column says the least that works.

The API role already writes `member` (roles.API_WRITE), so no grant changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "member",
        sa.Column("has_left", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("member", "has_left")
