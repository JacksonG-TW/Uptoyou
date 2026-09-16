"""D105's one flag becomes two: the invite power and the evidence table part company.

Revision ID: 0047
Revises: 0046

*Owner-ruled 2026-09-16 (「拆」, decision-log row 274da9d).*

**What was wrong.** D105 put the role on the credential and not on the person, which is right and
stays. But one boolean — `device_secret.operator` — granted two unrelated powers: minting and
reading a circle's invite link (`POST /circles/{id}/join-ticket` and the two link-status reads), and
seeing D105's evidence table in the reveal payload (`api_common.for_credential`). Since A24 the
self-serve door mints the creator's secret with that flag, so **the first person to tap 開一個圈子
inherited a privilege nobody ruled**: at two seats the evidence table's rows identify whose
preference moved a place.

**The split.** `operator` keeps the invite power and loses the table; the new `evidence` column
carries the table. Two columns rather than a `capabilities` array or a `kind` enum, because there
are exactly two capabilities and a rewrite of every check for a set that has not grown in two
months buys nothing; a third capability is when the array becomes right, and these two fold into it
then.

**The backfill is the whole safety of this migration: `evidence = operator`.** Every credential that
exists — the owner's operator credential, every seat on the box, every fixture — keeps exactly the
powers it had this morning, so nothing a person holds changes meaning when this deploys. The split
bites only the *next* credential issued: `upto.issue --operator` no longer implies the table (it
takes `--evidence` too), and `POST /circles` mints the creator `operator=True, evidence=False`,
which is the ruling.

**Downgrade** drops the column. It cannot restore the distinction — a credential issued afterwards
with one flag and not the other becomes, on downgrade, whatever its `operator` column says. That is
stated rather than worked around: a flag that never existed cannot be remembered.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # `server_default` false so a row inserted by anything that has not learned the column yet is
    # the *narrow* one — a new credential without the flag sees no evidence table, never the
    # reverse. The default stays on the column: the safe value is the one a mistake lands on.
    op.add_column(
        "device_secret",
        sa.Column("evidence", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    # The backfill. Written as one statement over every existing row, before anything reads the
    # column, so there is no window in which an operator's credential has lost its table.
    op.execute(sa.text("update device_secret set evidence = operator"))


def downgrade() -> None:
    op.drop_column("device_secret", "evidence")
