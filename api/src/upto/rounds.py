"""Ticket 19 — the write half's three endpoints: open, propose, roll.

Every endpoint resolves the caller to a member of the round's circle before anything else
(D67), and the two halves of a failed resolution — an unknown token, a circle without a seat
— read identically, so the error is not a probe.

The response shapes the entries already ruled:

- a losing simultaneous open answers **409 carrying the round that won** (D68), so a typed
  hour is never silently dropped;
- a repeat proposal is a **quiet 200** (D70) — a proposal carries no input beyond which
  place, so two requests for the same place cannot disagree;
- rolling a closed round answers **200 with the stored result** (D69) — the retry gets
  exactly the answer it missed, in the same shape a first roll returns it;
- a swept or empty pool answers 409 out loud (D22's shape) rather than resolving to an
  arbitrary winner.

The roll is the whole chain in one transaction: re-resolve a defaulted hour to the hour the
roll stands in (D73, D41), load and pin (D43), fold (D45/D46), apportion 36 outcomes (D72),
two cryptographically random dice, and `write_roll` — which re-folds the records it stores
and refuses the whole write on any mismatch (D15).
"""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from .api_common import (
    closed_body,
    for_credential,
    place_names,
    resolve_credential,
    resolve_member,
    trip_for,
)
from .db import session_factory
from .engine import draw
from .engine.fold import fold
from .engine.load import load_contributions
from .engine.store import write_roll
from .engine.table import EmptyPoolError
from .engine.table import build as build_table
from .engine.table import place_for
from .stream import publish

# Error `detail` strings a person can reach from the surface are product copy — the front end
# prints them verbatim (D96/A10, 2026-08-17): plain 繁體中文, no spec citations. The 422 for a
# malformed target_hour stays English because only a client bug, never a person, produces it.
# No prefix: the proxy strips /api/ before forwarding (upto.conf's rewrite), so the app
# serves /circles/... and the outside world sees /api/circles/... — same convention as
# /weather. A prefix here once produced a proxy-only 404 the tests could not see.
router = APIRouter()

_resolve_member = resolve_member
_resolve_credential = resolve_credential


class OpenRoundBody(BaseModel):
    target_hour: datetime | None = None


@router.post("/circles/{circle_id}/rounds", status_code=201)
async def open_round(circle_id: int, body: OpenRoundBody, request: Request) -> dict:
    typed = body.target_hour is not None
    if typed and body.target_hour.tzinfo is None:
        raise HTTPException(status_code=422, detail="target_hour must carry a UTC offset (H17)")
    # **D108: the seed is drawn HERE, at open, before a single place can be proposed.** That
    # ordering is the whole commitment: the server fixes its randomness while it still does not know
    # what the places will be, so it cannot have aimed at one. Drawn before the insert rather than
    # after, because a round that existed for even one statement without its commitment is a round
    # whose commitment came second.
    seed = draw.new_seed()
    async with session_factory()() as session:
        await _resolve_member(session, request, circle_id)
        try:
            row = (
                await session.execute(
                    text(
                        "insert into round (circle_id, target_hour, target_hour_typed, "
                        "                   outcome_seed, seed_commit, seat_ids) "
                        "values (:c, coalesce(:h, date_trunc('hour', now())), :typed, :seed, :commit, "
                        "        (select array_agg(id order by id) from member "
                        "          where circle_id = :c)) "
                        "returning id, target_hour, target_hour_typed, opened_at, seed_commit"
                    ),
                    {"c": circle_id, "h": body.target_hour, "typed": typed,
                     "seed": seed, "commit": draw.commitment(seed)},
                )
            ).one()
            # **Before the commit, not after — and that is the reverse of what this line said
            # until 2026-09-11.** The old rule («after the commit, never before: an event for a
            # rolled-back write is a lie») was right about the danger and had only one way to
            # avoid it. `pg_notify` inside the transaction is delivered **only if that transaction
            # commits**, measured, so the mechanism now carries what the ordering used to — and it
            # closes the gap the ordering could not: a crash between the commit and the publish
            # used to lose the event silently.
            await publish(
                session,
                circle_id,
                {
                    "type": "round_opened",
                    "round": {
                        "round_id": row.id,
                        "target_hour": row.target_hour.isoformat(),
                        "target_hour_typed": row.target_hour_typed,
                        "opened_at": row.opened_at.isoformat(),
                        "pool": [],
                        # The commitment, from the first event. **Never `outcome_seed`** — a member
                        # holding the seed early can compute the winner and then choose whether to
                        # tap, which is the preference D91 forbids.
                        "seed_commit": row.seed_commit,
                        "rolls": [],
                    },
                },
            )
            await session.commit()
        except IntegrityError:
            # D52's partial unique index fired: someone else's open won. D68: say so, and
            # hand over the winner so the client enters it without a second fetch.
            await session.rollback()
            winner = (
                await session.execute(
                    text(
                        "select id, target_hour, target_hour_typed, opened_at from round "
                        "where circle_id = :c and status = 'open'"
                    ),
                    {"c": circle_id},
                )
            ).one_or_none()
            detail: dict = {"error": "a round is already open in this circle (D68)"}
            if winner is not None:
                detail["open_round"] = {
                    "round_id": winner.id,
                    "target_hour": winner.target_hour.isoformat(),
                    "target_hour_typed": winner.target_hour_typed,
                    "opened_at": winner.opened_at.isoformat(),
                }
            raise HTTPException(status_code=409, detail=detail) from None
    return {
        "round_id": row.id,
        "status": "open",
        "target_hour": row.target_hour.isoformat(),
        "target_hour_typed": row.target_hour_typed,
        "seed_commit": row.seed_commit,
    }


class ProposeBody(BaseModel):
    place_id: int


@router.post("/rounds/{round_id}/proposals", status_code=201)
async def propose(round_id: int, body: ProposeBody, request: Request, response: Response) -> dict:
    async with session_factory()() as session:
        round_row = (
            await session.execute(
                text("select circle_id, status from round where id = :r"), {"r": round_id}
            )
        ).one_or_none()
        if round_row is None:
            raise HTTPException(status_code=404, detail="找不到這一輪。")
        member = await _resolve_member(session, request, round_row.circle_id)
        if round_row.status != "open":
            raise HTTPException(status_code=409, detail="這一輪已經擲過了。")
        place = (
            await session.execute(
                text("select origin, circle_id from place where id = :p"),
                {"p": body.place_id},
            )
        ).one_or_none()
        # A circle-local place of another circle answers exactly like no place at all:
        # what other circles typed is not this circle's to discover (D28's scoping).
        if place is None or (
            place.origin == "circle-local" and place.circle_id != round_row.circle_id
        ):
            raise HTTPException(status_code=404, detail="找不到這家店。")
        try:
            await session.execute(
                text(
                    "insert into proposal (round_id, place_id, member_id) "
                    "values (:r, :p, :m)"
                ),
                {"r": round_id, "p": body.place_id, "m": member},
            )
            names = await place_names(session, [body.place_id])
            # **A19: the mark travels with the place, on the event that puts it in the pool.**
            # 這一餐's list is where a person chooses, so it needs the state before the roll and not
            # only after it — and a list drawn from a wire that lacks the field renders NO mark,
            # which reads as *no allergen here*. §3.0 is satisfied because the value is a fact about
            # the place and about nobody: it is the same string for every member in the room.
            await publish(
                session,
                round_row.circle_id,
                {
                    "type": "pooled",
                    "round_id": round_id,
                    "place": {
                        "place_id": body.place_id,
                        "name": names.get(body.place_id),
                    },
                },
            )
            await session.commit()
        except (IntegrityError, DBAPIError) as failure:
            await session.rollback()
            message = str(getattr(failure, "orig", failure))
            if "uq_proposal_place_per_round" in message:
                # D70: the place is in the pool, which is what the request wanted.
                response.status_code = 200
                return {"round_id": round_id, "place_id": body.place_id, "pooled": True}
            if "3 proposals" in message:
                # **「一個人」, not 「一輪」 — corrected 2026-08-19 on D110.** The trigger is per
                # member per round (`member % already holds 3 proposals in round %`, revision 0008),
                # so the old sentence told a person the round holds three places when a five-member
                # round holds fifteen. D110 then put 「每人最多提 3 家店」 on the home page, and the
                # two statements of one rule contradicted each other — the home page right, the
                # refusal wrong, and the refusal is the one you meet at the moment it matters.
                #
                # **This sentence is the single source: the front end renders the API's `detail`
                # verbatim and keeps no copy** (frontend's rule, 2026-08-19). So a wording change
                # goes here and reaches the screen; there is nothing to keep in sync, and equally
                # nothing else to correct when it is wrong.
                raise HTTPException(
                    status_code=409, detail="一個人最多提三家。"
                ) from None
            raise
    return {"round_id": round_id, "place_id": body.place_id, "pooled": True}


@router.post("/rounds/{round_id}/roll")
async def roll(round_id: int, request: Request) -> dict:
    async with session_factory()() as session:
        round_row = (
            await session.execute(
                text(
                    "select circle_id, status, target_hour_typed, die1, die2, "
                    "winning_place_id, outcome_seed, seed_commit, seat_ids "
                    "from round where id = :r"
                ),
                {"r": round_id},
            )
        ).one_or_none()
        if round_row is None:
            raise HTTPException(status_code=404, detail="找不到這一輪。")
        # The role decides which reveal shape comes back, and it comes from the credential alone —
        # there is no parameter an endpoint could be talked into.
        member, is_operator = await _resolve_credential(session, request, round_row.circle_id)

        if round_row.status == "closed":
            # D69: the retry gets the answer it missed, in the shape a first roll returns.
            stored = (
                await session.execute(
                    text("select place_id, weight from proposal where round_id = :r"),
                    {"r": round_id},
                )
            ).all()
            dice = (
                (round_row.die1, round_row.die2) if round_row.die1 is not None else None
            )
            # The retry answers in the shape a first roll would have returned **to this
            # credential** — D69 promises the answer that was missed, not a different one.
            return for_credential(
                await closed_body(
                    session, round_id, dice, round_row.winning_place_id,
                    {row.place_id: row.weight for row in stored}, viewer=member,
                ),
                operator=is_operator,
            )

        if not round_row.target_hour_typed:
            # D73 through D41: a defaulted hour is re-resolved to the hour the roll stands in.
            await session.execute(
                text("update round set target_hour = date_trunc('hour', now()) where id = :r"),
                {"r": round_id},
            )

        loaded = await load_contributions(session, round_id)
        pinned = loaded.contributions
        pool = (
            (
                await session.execute(
                    text("select place_id from proposal where round_id = :r"), {"r": round_id}
                )
            )
            .scalars()
            .all()
        )
        # **D108's minimum, checked before the tap is recorded.** One place is not a decision, it is
        # a notification — and a member who taps into a one-place round has not spent their tap,
        # because nothing was decided. So this refusal comes first and `member_roll` stays empty.
        if len(pool) < 2:
            raise HTTPException(
                status_code=409, detail="一輪至少要兩家店。一家店不是決定，是通知。"
            ) from None
        # **The tap, recorded and idempotent.** `uq_member_roll_once` makes a second tap the same
        # tap (D69 per person), and `on conflict do nothing` is how that reads without a round trip
        # to find out first. The dice are NOT stored — they are derived from the seed every time, so
        # there is only ever one source for a member's pair.
        await session.execute(
            text(
                "insert into member_roll (round_id, circle_id, member_id) "
                "values (:r, :c, :m) on conflict (round_id, member_id) do nothing"
            ),
            {"r": round_id, "c": round_row.circle_id, "m": member},
        )
        weights = {
            place: fold(
                place, [p.contribution for p in pinned if p.contribution.place_id == place]
            ).weight
            for place in pool
        }
        try:
            table = build_table(weights)
        except EmptyPoolError:
            # **Owner-ruled 2026-08-30: every seat is told, and the round stays open.** The roller
            # learns from the 409 below; the other four learn from here, because a swept pool is
            # not a fact about whoever happened to tap — it is the state of their round, and four
            # people staring at a screen that did nothing is the silence §3.0 is built against.
            #
            # **Type and round id, no text.** The sentence lives in the surface and is rendered for
            # this event *and* for the 409, so one wording has one owner. The 409's `detail` stays
            # as the API's own contract — a curl reader wants it — and no member reads it, which is
            # what stops two sentences for one event drifting apart in two repositories.
            #
            # **The round id is not decoration: it is the clear rule.** The surface clears this
            # notice on the next `pooled` event *for that round*, so an event without it would
            # either never clear or be cleared by a different round's proposal.
            # **`transactional=False`, and D37 is the whole reason.** This path raises the 409
            # below, so its transaction rolls back — and a notification inside a transaction that
            # rolls back is never delivered (measured 2026-09-11). The other four members would
            # learn nothing, and «four people staring at a screen that did nothing is the silence
            # §3.0 is built against». So this one goes on its own connection, unconditionally: the
            # event says the pool was empty, which is true whatever becomes of this request.
            await publish(session, round_row.circle_id,
                          {"type": "pool_swept", "round_id": round_id}, transactional=False)
            raise HTTPException(
                status_code=409,
                detail="池子是空的，或每一家的權重都是零，擲不出結果。",
            ) from None
        # **D108: the dice come from the seed committed at open, never from a fresh draw here.**
        # This is the line the whole mechanism exists to change. `secrets.randbelow` at roll time was
        # honest randomness and unprovable: nobody could check afterwards that it had not been drawn
        # with the places in view. Now the pair is `hmac(seed, "member:<decider>")`, the seed's hash
        # was published before any place existed, and the seed is revealed below — so the claim
        # *this was fixed before anyone saw anything* becomes checkable instead of asserted.
        #
        # **A round that predates revision 0026 has no seed**, and there is no honest way to give it
        # one, so it keeps the old behaviour rather than being refused: a commitment made after the
        # places were known would not be a commitment.
        if round_row.outcome_seed is not None:
            # **The seats pinned at open, never live membership.** Reading `member` here is the bug
            # revision 0027 exists for: the decider moved whenever the circle's membership changed, so
            # a closed round's arithmetic stopped checking out and an open round's decider could change
            # under a member who joined mid-round. A round with a seed and no pinned seats predates
            # 0027 and falls back, because there is nothing honest to reconstruct.
            seat_ids = list(round_row.seat_ids or [])
            if not seat_ids:
                seat_ids = list(
                    (
                        await session.execute(
                            text("select id from member where circle_id = :c order by id"),
                            {"c": round_row.circle_id},
                        )
                    )
                    .scalars()
                    .all()
                )
            dice = draw.deciding_pair(bytes(round_row.outcome_seed), seat_ids)
        else:
            dice = (secrets.randbelow(6) + 1, secrets.randbelow(6) + 1)
        winner = place_for(table, dice[0], dice[1])
        await write_roll(
            session, round_id, pinned, weights, winner, dice,
            forecast_baseline=loaded.forecast_baseline,
        )
        full = await closed_body(session, round_id, dice, winner, weights, viewer=member)
        # **D53's push carries the member shape, because a broadcast has no credential.** One event
        # goes to every subscriber on the circle's channel, so it can only be the shape everyone may
        # see. An operator's extra detail arrives when that operator asks — its own request, its own
        # credential — which is also why the snapshot is per connection (D56).
        await publish(session, round_row.circle_id, {"type": "closed",
                                      "result": for_credential(full, operator=False)})
        await session.commit()
    return for_credential(full, operator=is_operator)

@router.post("/rounds/{round_id}/trip", status_code=201)
async def sign_trip(round_id: int, request: Request, response: Response) -> dict:
    """B2 / item 9 — one member says the group went. 201, or 200 on a retry, or 409 with the signer.

    **§3.0's asymmetry, as an endpoint.** A proposal is anonymous and D14's trigger has already
    erased its author by the time this can be called; a trip is *named*, because "we went" is a fact
    about an outing rather than an opinion about a restaurant. So this is the one place a member's
    identity is recorded and kept.

    **Nothing is published to the stream (D53).** A close is pushed once and then the channel is
    quiet. A trip event would tell four other people the *moment* one person tapped, and §3.0's whole
    argument is that at five people the timing of an event is one guess from a name. D53's own flip
    condition is a measurement of when people actually sign — not an intuition that a live badge
    would be nice — so there is deliberately no `publish` call in this function.

    **The three outcomes are the database's, not this code's.**

    * **201** — the insert succeeded and this member is the signer.
    * **200** — the same member tapped twice. D69's idiom: a retry is not an error, and it returns
      the same trip rather than a conflict, because the second tap usually means the first response
      was lost.
    * **409 with the fact** — somebody else signed first, and the response names *who* and *when*
      (D68). A bare 409 would leave a screen saying "already signed" with no way to show by whom,
      and the nickname is circle-visible information: everyone in the circle knows who is in it.

    **The race is settled by `trip.round_id`'s UNIQUE and not by a `SELECT` first.** Two taps in the
    same instant both pass a check-then-insert; only one passes the index. So the insert is attempted
    and the conflict is *read* afterwards — which also means the 409's facts come from the row that
    actually won rather than from whatever a prior read saw.

    **A signature outside the circle is refused by the composite foreign keys**, not here. See
    revision 0024: `(circle_id, member_id) → member(circle_id, id)` cannot be satisfied by a member
    of another circle, so even a bug in this function cannot store one.
    """
    async with session_factory()() as session:
        round_row = (
            await session.execute(
                text("select circle_id, status, winning_place_id from round where id = :r"),
                {"r": round_id},
            )
        ).one_or_none()
        if round_row is None:
            raise HTTPException(status_code=404, detail="找不到這一輪。")
        member = await _resolve_member(session, request, round_row.circle_id)
        # A trip needs somewhere to have gone. An open round has no winner, so signing one would
        # record an outing to a place nobody has chosen yet.
        if round_row.status != "closed" or round_row.winning_place_id is None:
            raise HTTPException(status_code=409, detail="這一輪還沒擲出結果。")
        try:
            await session.execute(
                text(
                    "insert into trip (round_id, circle_id, member_id) "
                    "values (:r, :c, :m)"
                ),
                {"r": round_id, "c": round_row.circle_id, "m": member},
            )
            await session.commit()
        except IntegrityError:
            await session.rollback()
            existing = (
                await session.execute(
                    text("select member_id from trip where round_id = :r"), {"r": round_id}
                )
            ).one_or_none()
            if existing is None:
                # The insert failed and no trip exists: the composite keys refused it, which means
                # the member does not belong to this round's circle. Re-raised rather than turned
                # into a 409, because it is not a conflict — nothing is there to conflict with.
                raise HTTPException(status_code=403, detail="這一輪不屬於你的圈子。") from None
            trip = await trip_for(session, round_id)
            if existing.member_id == member:
                response.status_code = 200
                return {"trip": trip}
            raise HTTPException(
                status_code=409,
                detail="{}已經在 {} 記下這一趟了。".format(trip["nickname"], trip["signed_at"]),
            ) from None
        return {"trip": await trip_for(session, round_id)}
