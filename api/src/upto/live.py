"""Ticket 20 — the read half: the circle's stream, and the places a proposal needs.

**The snapshot is the stream's first event (D56), and there is no endpoint beside it** — a
reconnecting client and a fresh one run the same code path, which is the whole reason D56
ruled it this way. The subscription opens *before* the snapshot is built: an event landing in
that window is delivered twice — once inside the snapshot, once as itself — and a duplicate
is the safe direction, because the client applies events idempotently (a pooled place it
already shows, a close it already drew) while a gap would be a fact it never learns.

**Nothing on this stream carries a member (D55).** The pool is places; the close is a result;
authorship exists only inside an open round's table rows and dies at the close (D14). A trip
is never on the stream (D53) — it is signed hours later, when nobody is watching a channel.

**The propose flow is D28's:** the typeahead searches this circle's own rows and the latest
publication's reference rows; a name nothing matches is submitted as it stands and becomes a
circle-local row. Creating a place that exists is a quiet success — the name (or the 登錄字號)
is the only input, so two requests cannot disagree, which is D70's argument one table over.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .api_common import (
    SINGLE_BRAND_GROUPED,
    STOREFRONT,
    compose_names,
    place_display,
    place_names,
    for_credential,
    deciding_member_for,
    panel_for,
    seats_for,
    resolve_credential,
    resolve_member,
    result_body,
    ingredient_data_for,
    winner_headline_for,
    trip_for,
)
from .db import session_factory
from .engine.table import allocate
from .stream import subscribe

# No prefix — the proxy strips /api/ before forwarding, same as rounds.py explains.
router = APIRouter()


async def _snapshot(session, circle_id: int, viewer=None, operator: bool = False) -> dict:
    """The circle's current state: an open round with its pool, else the last result (D54)."""
    open_row = (
        await session.execute(
            text(
                "select id, target_hour, target_hour_typed, opened_at, seed_commit, "
                "outcome_seed, seat_ids from round where circle_id = :c and status = 'open'"
            ),
            {"c": circle_id},
        )
    ).one_or_none()
    if open_row is not None:
        pool_ids = (
            (
                await session.execute(
                    text("select place_id from proposal where round_id = :r order by place_id"),
                    {"r": open_row.id},
                )
            )
            .scalars()
            .all()
        )
        names = await place_names(session, pool_ids)
        # **D108, and this is the half D56 makes load-bearing.** The seat list and the commitment are
        # in the snapshot, so a member who reloads or reconnects mid-round meets the same decider and
        # the same seats they left — RP-4 is *the chosen member does not change on reload*, and a
        # snapshot that omitted them would make the browser reconstruct a fairness claim it cannot
        # verify. The seats come from `api_common.seats_for`, the same function the reveal uses, so
        # the stream and the response cannot drift.
        seed = bytes(open_row.outcome_seed) if open_row.outcome_seed is not None else None
        seats = await seats_for(session, open_row.id, open_row.seat_ids, seed, closed=False)
        open_round = {
            "round_id": open_row.id,
            "target_hour": open_row.target_hour.isoformat(),
            "target_hour_typed": open_row.target_hour_typed,
            "opened_at": open_row.opened_at.isoformat(),
            "pool": [{"place_id": p, "name": names.get(p)} for p in pool_ids],
            "seed_commit": open_row.seed_commit,
            "rolls": seats,
            "deciding_member": deciding_member_for(seats),
            # **Never on an open round.** The seed is what a member would use to compute the winner
            # and then decide whether to tap — the preference D91 forbids. Present and null, rather
            # than absent, so a gate can assert the key is null instead of asserting an absence.
            "revealed_seed": None,
        }
        return {
            "type": "snapshot",
            "open_round": open_round,
            "last_result": None,
        }
    last = (
        await session.execute(
            text(
                "select id, die1, die2, winning_place_id from round "
                "where circle_id = :c and status = 'closed' "
                "order by closed_at desc limit 1"
            ),
            {"c": circle_id},
        )
    ).one_or_none()
    last_result = None
    if last is not None:
        stored = (
            await session.execute(
                text("select place_id, weight from proposal where round_id = :r"),
                {"r": last.id},
            )
        ).all()
        weights = {row.place_id: row.weight for row in stored}
        dice = (last.die1, last.die2) if last.die1 is not None else None
        # A16: the snapshot carries the same headline the roll response did — one composition,
        # read twice, so a reconnecting client's reveal reads identically to the live one.
        display = await place_display(session, weights.keys())
        winner_headline, winner_qualifier = winner_headline_for(display, last.winning_place_id)
        ingredient_data = await ingredient_data_for(session, weights.keys())
        last_result = result_body(
            last.id,
            dice,
            last.winning_place_id,
            weights,
            {key: value["name"] for key, value in display.items()},
            allocate(weights) if weights else {},
            winner_headline=winner_headline,
            winner_qualifier=winner_qualifier,
            ingredient_data=ingredient_data,
        )
        # **B2, and this is the half D56 makes necessary.** Nothing is pushed when a trip is signed
        # (D53), so a client that was not connected at the moment — or that reconnected since — would
        # otherwise never learn of it. The snapshot *is* the stream's first event, so carrying the
        # trip here is what makes a silent signing observable at all. Same shape as everywhere else:
        # nickname and time, never the signer's id.
        last_result["trip"] = await trip_for(session, last.id)
        # The evidence table, for an operator only. Built here rather than always, because it costs
        # a query and a fold that a member's snapshot would immediately discard.
        if operator:
            last_result["panel"] = await panel_for(session, last.id, weights, viewer)
        # **D105/D56: the snapshot is per connection, so it is the one broadcast-shaped thing that
        # can be role-aware.** A pushed event goes to every subscriber and must therefore be the
        # member shape; a snapshot is built for the credential that opened *this* stream, so an
        # operator's reconnect restores the evidence table rather than losing it.
        last_result = for_credential(last_result, operator=operator)
    return {"type": "snapshot", "open_round": None, "last_result": last_result}


@router.get("/circles/{circle_id}/stream")
async def stream(circle_id: int, request: Request) -> StreamingResponse:
    async with session_factory()() as session:
        viewer, is_operator = await resolve_credential(session, request, circle_id)

    async def events():
        async with subscribe(circle_id) as queue:
            # Subscribe first, snapshot second: the overlap duplicates, never drops.
            async with session_factory()() as session:
                snapshot = await _snapshot(session, circle_id, viewer, is_operator)
            yield "data: " + json.dumps(snapshot, ensure_ascii=False) + "\n\n"
            while True:
                event = await queue.get()
                yield "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get("/circles/{circle_id}/places")
async def search_places(
    circle_id: int,
    request: Request,
    q: str = Query(..., min_length=1, description="a fragment of the place's name"),
) -> dict:
    async with session_factory()() as session:
        await resolve_member(session, request, circle_id)
        local = (
            await session.execute(
                text(
                    "select id, name from place "
                    "where origin = 'circle-local' and circle_id = :c "
                    "and name ilike '%' || :q || '%' order by name limit 10"
                ),
                {"c": circle_id, "q": q},
            )
        ).all()
        latest_pub = (
            await session.execute(
                text("select id from place_publication order by detected_at desc limit 1")
            )
        ).scalar_one_or_none()
        reference = []
        if latest_pub is not None:
            # The name patches run here too (D77/D78): the query matches the registered
            # name, the single brand, OR the storefront sign, and shows the most specific —
            # typing 摩斯 must find the row whose FDA name is 安心食品服務股份有限公司, or
            # the patch fixes the reveal and not the search.
            reference = (
                await session.execute(
                    text(
                        "select rp.registry_no, "
                        "coalesce(storefront.name, brand.brand_name, rp.name) as name, "
                        "storefront.name as sign, brand.brand_name as brand, "
                        "rp.name as registered, rp.address, "
                        "p.id as place_id "
                        "from reference_place rp "
                        "left join place p on p.registry_no = rp.registry_no "
                        "  and p.origin = 'reference' "
                        "left join lateral ("
                        + STOREFRONT.format(registry="rp.registry_no")
                        + ") storefront on true "
                        # **D93's grouped join, owner-ruled 2026-08-27 — the request path's
                        # only rewrite.** This was a `LATERAL` re-evaluated once per candidate
                        # row: M8 measured 35,533 executions per keystroke against a 288-row
                        # table and 93% of the query's buffers. It is now one grouped scan of
                        # that table, joined on `company_name`. The rule is unchanged and lives
                        # in `_SINGLE_BRAND_RULE`, shared with the per-row form, so the two
                        # spellings cannot drift.
                        #
                        # **The filter still sits above this join**, which is why D93's trigram
                        # index stays rejected: `brand.brand_name ilike …` in the `where` below
                        # reads a join output, not a base column, so no index on `rp.name` is
                        # reachable. This rewrite removes the N+1, not the scan — and the scan
                        # was never the cost.
                        "left join ("
                        + SINGLE_BRAND_GROUPED
                        + ") brand on brand.company_name = rp.name "
                        "where rp.publication_id = :pub "
                        "and (rp.name ilike '%' || :q || '%' "
                        "  or brand.brand_name ilike '%' || :q || '%' "
                        "  or storefront.name ilike '%' || :q || '%' "
                        # **D113's authored alias, and it is in the `where` and nowhere else.**
                        # A member typing 星巴克 must reach 悠旅生活事業股份有限公司 — no
                        # publisher has ever written those three characters, so no rung of the
                        # ladder can match them. This clause is the whole of that fix.
                        #
                        # **It widens the match and touches no name.** The `select` above is
                        # `coalesce(storefront.name, brand.brand_name, rp.name)` and stays that
                        # way: D113's first iron law is match-only, never displayed, so a row
                        # found through an alias is *shown* under whatever the publisher calls
                        # it. Putting `search_alias.alias` in that coalesce would be the one
                        # edit that breaks the ruling, which is why the two live four lines
                        # apart with this comment between them.
                        #
                        # **A known property, measured 2026-08-20, deliberately not "fixed".** The
                        # alias is matched as a *substring*, like the three rungs above it, so a
                        # one-character `q=7` does put `7-11` and `7-ELEVEN` in the match set and
                        # therefore 統一超商's hundreds of rows. It does not *surface*: `order by 2
                        # limit 10` sorts by the composed name under this database's **C collation**,
                        # so digits and Latin sort ahead of 統, and `q=7` returns ten real places
                        # with a 7 in the name and **zero** chain rows (measured; `q=11` and `q=-`
                        # likewise). **That is ordering doing the work, not design.** If the ordering
                        # ever becomes relevance-ranked, short queries will start surfacing the
                        # chain and an alias-specific rule — minimum length, or prefix rather than
                        # substring — becomes necessary. No threshold is invented here today,
                        # because none has been measured; this comment is the trigger.
                        "  or rp.name in ("
                        "    select registered_name from search_alias "
                        "    where alias ilike '%' || :q || '%')) "
                        # D81: a 統編 the registry records as dead — an explicitly dead row
                        # and no 核准設立 row anywhere under the number — is hidden from
                        # this search and only this search. Proposals by hand (circle-local)
                        # stay open: a person's knowledge outranks the roster's. The alive
                        # exception is mandatory, not caution: 統編 reuse is measured real,
                        # and an unrecognised status defaults to visible.
                        "and not exists ("
                        "  select 1 from business_status_row dead "
                        "  where dead.business_no = rp.business_no "
                        "  and dead.publication_id = ("
                        "    select id from business_status_publication "
                        "    order by detected_at desc, id desc limit 1) "
                        "  and dead.status in ('歇業／撤銷', '停業', '廢止', '遷他縣市', "
                        "    '撤銷設立登記') "
                        "  and not exists ("
                        "    select 1 from business_status_row alive "
                        "    where alive.publication_id = dead.publication_id "
                        "    and alive.business_no = dead.business_no "
                        "    and alive.status = '核准設立')) "
                        "order by 2 limit 10"
                    ),
                    {"pub": latest_pub, "q": q},
                )
            ).all()
        # D92, composed here and nowhere else (owner-ruled 2026-08-18): the bracket says the
        # name was derived from the registered address, and the collision that earns a
        # bracket is judged against the whole publication, so the same site reads the same in
        # this list, the pool and the reveal. `district` is B6's second line.
        composed = await compose_names(
            session,
            [{"key": ("local", row.id), "own": row.name} for row in local]
            + [
                {
                    "key": ("ref", row.registry_no),
                    "own": None,
                    "registry_no": row.registry_no,
                    "sign": row.sign,
                    "brand": row.brand,
                    "registered": row.registered,
                    "company": row.registered,
                    "address": row.address,
                }
                for row in reference
            ],
        )
    return {
        "candidates": [
            {
                "kind": "circle-local",
                "place_id": row.id,
                "name": composed[("local", row.id)]["name"],
                "name_source": "circle-local",
                "district": None,
            }
            for row in local
        ]
        + [
            {
                "kind": "reference",
                "place_id": row.place_id,
                "registry_no": row.registry_no,
                "name": composed[("ref", row.registry_no)]["name"],
                "name_source": composed[("ref", row.registry_no)]["name_source"],
                "district": composed[("ref", row.registry_no)]["district"],
            }
            for row in reference
        ]
    }


class CreatePlace(BaseModel):
    name: str | None = None
    registry_no: str | None = None


@router.post("/circles/{circle_id}/places", status_code=201)
async def create_place(
    circle_id: int, body: CreatePlace, request: Request, response: Response
) -> dict:
    if (body.name is None) == (body.registry_no is None):
        raise HTTPException(
            status_code=422, detail="exactly one of name or registry_no (D28's two doors)"
        )
    async with session_factory()() as session:
        await resolve_member(session, request, circle_id)
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="a place needs a name")
            try:
                place_id = (
                    await session.execute(
                        text(
                            "insert into place (origin, circle_id, name) "
                            "values ('circle-local', :c, :n) returning id"
                        ),
                        {"c": circle_id, "n": name},
                    )
                ).scalar_one()
                await session.commit()
            except IntegrityError:
                # The circle already typed this name: same row, quiet success (D28's moat —
                # credit accumulates against one row, so a second typing must not split it).
                await session.rollback()
                place_id = (
                    await session.execute(
                        text(
                            "select id from place where origin = 'circle-local' "
                            "and circle_id = :c and name = :n"
                        ),
                        {"c": circle_id, "n": name},
                    )
                ).scalar_one()
                response.status_code = 200
            return {"place_id": place_id, "name": name}
        known = (
            await session.execute(
                text("select 1 from reference_place where registry_no = :no limit 1"),
                {"no": body.registry_no},
            )
        ).scalar_one_or_none()
        if known is None:
            raise HTTPException(status_code=404, detail="no reference place with that 登錄字號")
        try:
            place_id = (
                await session.execute(
                    text(
                        "insert into place (origin, registry_no) "
                        "values ('reference', :no) returning id"
                    ),
                    {"no": body.registry_no},
                )
            ).scalar_one()
            await session.commit()
        except IntegrityError:
            await session.rollback()
            place_id = (
                await session.execute(
                    text(
                        "select id from place where origin = 'reference' "
                        "and registry_no = :no"
                    ),
                    {"no": body.registry_no},
                )
            ).scalar_one()
            response.status_code = 200
        names = await place_names(session, [place_id])
        return {"place_id": place_id, "name": names.get(place_id)}
