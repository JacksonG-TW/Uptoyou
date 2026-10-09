"""A round can be void: every seat pinned at its open has left, so it ends with no result (owner, 2026-10-09).

The round waits for every pinned seat that is still in the circle. When none is left, nobody is
waited for and nobody was invited to the result — the owner's words, «the invitation lapsed» — so
the round neither closes nor stays open for ever: it is **voided**. The row stays, with its seed
commitment, because a round that existed is part of the circle's record; it carries no dice and no
winner, and `closed_at` says when it ended. `uq_round_one_open_per_circle` reads only `open`, so
the circle can open its next round at once.

**Authorship is erased on a void exactly as on a close (D14).** The trigger's condition widens from
`open → closed` to `open → closed | void`: the reason proposals lose their author is that the round
is over, and a void round is over.

The API role already writes `round` (roles.API_WRITE), so no grant changes.
"""

from __future__ import annotations

from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_round_status", "round", type_="check")
    op.create_check_constraint("ck_round_status", "round", "status in ('open', 'closed', 'void')")
    op.create_check_constraint(
        "ck_round_void_shape",
        "round",
        "status <> 'void' or (winning_place_id is null and die1 is null and die2 is null "
        "and closed_at is not null)",
    )
    op.execute("drop trigger round_close_erases_authorship on round")
    op.execute(
        """
        create trigger round_close_erases_authorship
        after update of status on round
        for each row
        when (old.status = 'open' and new.status in ('closed', 'void'))
        execute function erase_proposal_authorship()
        """
    )


def downgrade() -> None:
    op.execute("drop trigger round_close_erases_authorship on round")
    op.execute(
        """
        create trigger round_close_erases_authorship
        after update of status on round
        for each row
        when (old.status = 'open' and new.status = 'closed')
        execute function erase_proposal_authorship()
        """
    )
    op.drop_constraint("ck_round_void_shape", "round", type_="check")
    op.drop_constraint("ck_round_status", "round", type_="check")
    op.create_check_constraint("ck_round_status", "round", "status in ('open', 'closed')")
