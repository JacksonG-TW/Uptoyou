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

**The downgrade REFUSES while any credential holds one flag and not the other**, and that is the
reviewer's finding (2026-09-16) answered the way this codebase answers the rest of them: fail
closed. Dropping the column destroys the distinction, and the next `upgrade head` re-runs the
backfill — so down-then-up is a **widening**: every self-serve creator's credential would come back
carrying the evidence table, and an audit-only credential would lose it. A privilege that returns
by itself during a ten-minute rollback is exactly the defect the owner's 「拆」 ruling exists to
remove, and a runbook sentence is read by somebody who is already in trouble.

**The rollback is not blocked, it is made deliberate.** The refusal names how many rows disagree and
the one statement that resolves them — decide what those credentials should be, write it, then roll
back:

    update device_secret set evidence = operator;   -- every mixed credential keeps its INVITE flag's
                                                    -- answer; re-issue the ones that should differ

A database where no credential holds a mixed pair (every row before this migration, and any stack
that has issued none since) downgrades with no ceremony at all.
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
    mixed = op.get_bind().execute(
        sa.text("select count(*) from device_secret where operator <> evidence")
    ).scalar_one()
    if mixed:
        raise RuntimeError(
            "{} device secret(s) hold the invite power and the evidence table differently, and "
            "dropping `evidence` would destroy that distinction — the next `upgrade head` re-runs "
            "`evidence = operator`, so those credentials would come back with the WRONG powers (a "
            "self-serve creator carrying the evidence table again, owner-ruled 2026-09-16 「拆」). "
            "Decide what they should be and write it first, then downgrade:\n"
            "    update device_secret set evidence = operator;\n"
            "and re-issue whichever credential should have differed.".format(mixed)
        )
    op.drop_column("device_secret", "evidence")
