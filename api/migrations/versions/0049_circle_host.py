"""A circle has a host: `circle.host_member_id`, the seat that may remove another and holds the link (owner 「A」, 2026-10-09).

The host is the creator's seat, and when that seat leaves the role passes to the earliest-joined
seat still in the circle (`circles.release_seat`). It is stored on the circle, per circle, and
**not** as `device_secret.operator`: a secret belongs to a principal, a principal can sit in
several circles (the operator CLI's `--principal`), and flipping an heir's flag would make them host
in every one of them. The operator flag keeps meaning what it meant for CLI operators.

**Backfill: the seat the creator query already names** — the seat whose operator key was minted
in the circle's own creating transaction and has not left (`circles.creator_nickname`). A circle
made by the CLI has no such seat and starts with no host; its operator credential still works.

`on delete set null`: a seat erased with its row takes the role with it rather than blocking the
erasure. The API role already writes `circle` (roles.API_WRITE), so no grant changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("circle", sa.Column("host_member_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_circle_host_member", "circle", "member", ["host_member_id"], ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "update circle c set host_member_id = ("
        "  select m.id from member m "
        "  join device_secret d on d.principal_id = m.principal_id "
        "  where m.circle_id = c.id and not m.has_left and d.operator "
        "    and d.created_at = c.created_at "
        "  order by m.id limit 1)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_circle_host_member", "circle", type_="foreignkey")
    op.drop_column("circle", "host_member_id")
