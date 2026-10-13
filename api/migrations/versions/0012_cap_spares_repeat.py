"""Ticket 19 — the cap trigger steps aside for a repeat proposal.

Revision ID: 0012
Revises: 0011
Created: 2026-08-13

Found by ticket 19's endpoint test, not by reading: a member holding three proposals who
proposes a place **already in the pool** hit the cap trigger before the unique constraint —
BEFORE INSERT runs first — so D70's quiet success read as a violation of the three-places cap. The
two rules collided in the one case where both apply, and the cap won by execution order alone.

The fix is in the trigger, not the endpoint: when the (round, place) pair already exists,
the trigger lets the row through to the unique constraint, which rejects it with the name
the API maps to 200. The cap still counts only genuinely new proposals, which is what the cap
meant — a repeat adds nothing to anyone's share of the pool.
"""

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

FIXED = """
create or replace function enforce_proposal_cap() returns trigger
language plpgsql as $$
begin
    if exists (
        select 1 from proposal
        where round_id = new.round_id and place_id = new.place_id
    ) then
        -- The pair is already pooled: this insert is D70's repeat, and the unique
        -- constraint owns its rejection. The cap judges only new proposals.
        return new;
    end if;
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

ORIGINAL = """
create or replace function enforce_proposal_cap() returns trigger
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


def upgrade() -> None:
    op.execute(FIXED)


def downgrade() -> None:
    op.execute(ORIGINAL)
