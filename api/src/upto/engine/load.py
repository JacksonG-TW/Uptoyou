"""Ticket 15 — the engine's load half: fetch what the contributors will be handed.

D43 gives this module the queries and the contributors none of them. It walks the round's
pool, resolves each place's township, finds the rain reading for the meal's hour, and calls
the contributor once per place (D44) — collecting records and pinning each with the exact
reading row it was computed from, because only this module knows which row that was.

**Two passes, and the unit differs between them (A1, 2026-08-18).** The weather pass is one
record per *place*. The preference pass is one record per *(member, place)*: five people avoiding
the same category produce five records on one place, each pinned to that member's own preference
version — because D13's channel rule is about *who may see the reason*, and one shared record
could not answer that. Each preference record pins the **version in force** (`PreferencePin`), so
a round can be re-read and a version some round used cannot be erased (D24, D25).

**How a place reaches a township.** A `reference` place carries the 登錄字號 and nothing
else (D28's 2026-08-13 ruling): the township comes from the **latest** publication's
`reference_place` row for that number — D57's latest-wins, reused. A `circle-local` place has
no township and produces nothing, which D28 rules is neutrality rather than a penalty.

**How an hour reaches a reading.** 降雨機率 is three-hourly, so the reading is the slot that
*covers* the target hour, from the latest forecast publication that has one (D57). The loader
reads the round's stored `target_hour` as it stands: re-resolving a defaulted hour at the
roll is the roll endpoint's job (D41), not this module's.

Contribution ids here are synthetic (1..n, assigned in pool order): the database assigns the
durable ids at write time. D46's display order is re-derived from the stored rows, and the
fold's product is order-independent, so the synthetic ids never leak into anything durable.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

# **D25 as amended 2026-08-28: the same in-force predicate the GET uses.** Two reads that derive
# "in force" separately are two answers waiting to disagree — a lapsed `persist = false` row must
# be invisible to the engine on exactly the terms it is invisible to the screen, which is why this
# is imported rather than restated.
from upto.preferences import IN_FORCE_PREDICATE
from upto.engine.preference import REASON_VISIBILITY, avoid_contribution

#: material name → allergen group, built once from the authored table (A19). A dict
#: rather than a scan: the rule is a lookup and a substring rule is forbidden (D103).
from upto.engine.store import (
    # `BrandPin` is no longer imported: nothing here writes one since A19's pass was removed.
    # It stays in `store.py` with its dispatch branch, because `weight_contribution` rows already
    # carry `brand_publication_id` and the writer must still describe what is in the table.
    ForecastPin, PinnedContribution, PreferencePin, TripPin,
)
from upto.engine.weather import REASON_VISIBILITY as WEATHER_VISIBILITY
from upto.engine.trip import REASON_VISIBILITY as TRIP_VISIBILITY
from upto.engine.trip import last_trip_contribution
from upto.engine.weather import rain_contribution


# A14 / D114 — the circle's most recently **signed** trip, and the place it names.
#
# **The place is the signed round's stored winner and never a copy (D106).** `trip` carries no
# `place_id` on purpose, so this joins `round` for it; a column here would be the drift D28 refuses.
#
# **Ordered by `signed_at`, which is the signature and not the meal.** A round rolled long ago and
# signed this morning is the circle's last trip, because what D114 leans on is the act of saying
# «we went», not the hour the dice fell.
#
# **The roll's previous winner is not here and cannot be reached from here.** A round can be rolled
# and never signed — nobody went, or nobody said so — and a roll that produced no meal is not
# evidence about where the circle has been. This query starts at `trip`, so an unsigned round is
# invisible to it by construction rather than by a filter someone could relax.
LAST_TRIP = """
select t.id, r.winning_place_id,
       (t.signed_at at time zone 'Asia/Taipei')::date as went_on
  from trip t
  join round r on r.id = t.round_id
 where t.circle_id = :circle_id
 order by t.signed_at desc, t.id desc
 limit 1
"""


def _probability(value) -> int | None:
    """A 降雨機率 reading as an integer, or `None` if it will not parse.

    **Never coerced to 0.** The values are stored as text and a reading that will not parse read
    as 0% is a dry township this loader invented — and under a relative rule an invented dry
    township becomes the pool minimum and moves every other place.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class LoadedRound:
    """What one round's walk produced: the records, and the reading they were measured against.

    **The baseline is not a contribution and could not be carried as one.** Since D71 became
    relative (A12) every rain factor is a gap from the pool's lowest 降雨機率, and the place
    standing on that lowest reading produces no record at all (D43). So the reading the whole round
    was measured against is named here and stored by `write_roll` in `round_forecast_baseline`
    (revision 0030) — D24's pin for a row that has no contribution to hang from.

    **`forecast_baseline` is `None` when no comparison happened** — no reference place, no township,
    no reading for the hour, or a publication that carries none of the pool's townships. That is a
    different fact from *a comparison happened and every township matched*, which records a baseline
    and produces no contributions. D112: the two must not collapse into one absence.
    """

    contributions: tuple[PinnedContribution, ...]
    forecast_baseline: "ForecastPin | None"


async def load_contributions(session, round_id: int) -> LoadedRound:
    """One round's pool, walked once; returns every pinned record the fold will see."""
    round_row = (
        await session.execute(
            text("select circle_id, target_hour, status, seat_ids from round where id = :r"),
            {"r": round_id},
        )
    ).one_or_none()
    if round_row is None or round_row.status != "open":
        raise ValueError(f"round {round_id} is not an open round")
    target_hour = round_row.target_hour

    pool = (
        await session.execute(
            text(
                "select p.place_id, pl.origin, pl.registry_no, pl.category "
                "from proposal p join place pl on pl.id = p.place_id "
                "where p.round_id = :r order by p.place_id"
            ),
            {"r": round_id},
        )
    ).all()

    pinned: list[PinnedContribution] = []
    next_id = 1

    # --- D71 as reopened 2026-08-27 (A12): the rain pass, relative and therefore two-phase ------
    #
    # **The factor is a difference now, so no place can be decided alone.** `gap = this township's
    # 降雨機率 − the lowest in the pool`, and the lowest is not known until every pool place has
    # been resolved. D44 still holds — the *contributor* sees one place — so the minimum is computed
    # here and handed in beside the probability, exactly as `probability` already was.
    #
    # **One publication for the whole pool, and this is new.** Under the old absolute step each
    # township's reading could come from whichever publication was latest for it; comparing two
    # readings taken at different times was harmless because nothing was compared. A relative rule
    # cannot afford it: a gap assembled from two publications is partly an artifact of when each
    # was ingested, and the panel would print it as weather. So one publication is chosen for the
    # round — D57's latest-wins, unchanged — and every reading comes from it.
    #
    # **A township that publication does not carry gets no record**, the same neutrality D28 gives
    # a `circle-local` place. M13 measured this as real rather than theoretical: 24.5% of rain
    # groups hold fewer than 12 townships, so a publication missing a pool township is ordinary.
    # The alternative — reaching into an older publication for the missing one — is the mixing this
    # comment exists to refuse.
    townships: dict[int, str] = {}
    for row in pool:
        if row.origin != "reference":
            continue  # D28: no township, no reading, no record — neutral.
        township_code = (
            await session.execute(
                text(
                    "select rp.township_code from reference_place rp "
                    "join place_publication pp on pp.id = rp.publication_id "
                    "where rp.registry_no = :no order by pp.detected_at desc limit 1"
                ),
                {"no": row.registry_no},
            )
        ).scalar_one_or_none()
        if township_code is None:
            continue  # An address that never parsed costs its row a nudge and nothing else.
        townships[row.place_id] = township_code

    readings: dict[int, object] = {}
    if townships:
        codes = sorted(set(townships.values()))
        publication_id = (
            await session.execute(
                text(
                    "select fp.id from forecast_publication fp "
                    "join forecast_reading fr on fr.publication_id = fp.id "
                    "where fr.measure = 'ProbabilityOfPrecipitation' "
                    "and fr.township_code = any(:codes) "
                    "and fr.slot_start <= :hour "
                    "and (fr.slot_end is null or fr.slot_end > :hour) "
                    "group by fp.id, fp.detected_at "
                    "order by fp.detected_at desc, fp.id desc limit 1"
                ),
                {"codes": codes, "hour": target_hour},
            )
        ).scalar_one_or_none()
        if publication_id is not None:
            rows = (
                await session.execute(
                    text(
                        "select fr.publication_id, fr.township_code, fr.element, fr.measure, "
                        "fr.slot_start, fr.value from forecast_reading fr "
                        "where fr.publication_id = :pub "
                        "and fr.measure = 'ProbabilityOfPrecipitation' "
                        "and fr.township_code = any(:codes) "
                        "and fr.slot_start <= :hour "
                        "and (fr.slot_end is null or fr.slot_end > :hour) "
                        "order by fr.township_code, fr.slot_start desc"
                    ),
                    {"pub": publication_id, "codes": codes, "hour": target_hour},
                )
            ).all()
            # Narrowest slot first per township — `slot_end is null` rows can overlap a real one,
            # and the later `slot_start` is the one that actually covers the hour.
            by_code: dict = {}
            for reading in rows:
                by_code.setdefault(reading.township_code, reading)
            for place_id, code in townships.items():
                reading = by_code.get(code)
                if reading is None:
                    continue  # This publication does not carry that township. Neutral.
                if _probability(reading.value) is None:
                    continue  # A value that will not parse is not a dry township we invented.
                readings[place_id] = reading

    baseline: ForecastPin | None = None
    if readings:
        pool_minimum = min(_probability(r.value) for r in readings.values())
        # **The baseline reading, named once and pinned even though nothing points at it.** Ties are
        # ordinary — M13 measured the 12 townships holding one value in 56.4% of hours — so the
        # choice among equal readings is made by township code, deterministically. Any of them is
        # the same number; a stable rule is what lets a replay name the same row twice.
        cheapest = min(
            (r for r in readings.values() if _probability(r.value) == pool_minimum),
            key=lambda r: r.township_code,
        )
        baseline = ForecastPin(
            publication_id=cheapest.publication_id,
            township_code=cheapest.township_code,
            element=cheapest.element,
            measure=cheapest.measure,
            slot_start=cheapest.slot_start,
        )
        for place_id in sorted(readings):
            reading = readings[place_id]
            contribution = rain_contribution(
                next_id, place_id, _probability(reading.value), pool_minimum
            )
            if contribution is None:
                continue  # D43: this place sits in the driest township — no difference, no record.
            pinned.append(
                PinnedContribution(
                    contribution=contribution,
                    pin=ForecastPin(
                        publication_id=reading.publication_id,
                        township_code=reading.township_code,
                        element=reading.element,
                        measure=reading.measure,
                        slot_start=reading.slot_start,
                    ),
                    reason_visibility=WEATHER_VISIBILITY,
                )
            )
            next_id += 1

    # --- A14 / D114: the place the circle went to last time --------------------------------
    #
    # **One row at most, on one place, and only when that place is in this round's pool.** The
    # contributor is handed a yes-or-no (D44) — it never sees the pool and cannot tell a trip from a
    # winner, which is the point: only this query knows, and it starts at `trip`.
    #
    # **The date is Taipei's** (D25's 2026-08-27 amendment): the record says which day the circle
    # went, and which day is a question about the people rather than about the session's timezone.
    last_trip = (
        await session.execute(text(LAST_TRIP), {"circle_id": round_row.circle_id})
    ).one_or_none()
    if last_trip is not None and last_trip.winning_place_id is not None:
        for row in pool:
            contribution = last_trip_contribution(
                next_id,
                row.place_id,
                row.place_id == last_trip.winning_place_id,
                last_trip.went_on,
            )
            if contribution is None:
                continue  # D43: every other place in the pool, and there is nothing to say.
            pinned.append(
                PinnedContribution(
                    contribution=contribution,
                    pin=TripPin(trip_id=last_trip.id),
                    reason_visibility=TRIP_VISIBILITY,
                )
            )
            next_id += 1

    # --- A1: the private preferences of this circle's members -------------------------------
    #
    # **A second pass rather than a second loop inside the first, because the unit differs.** The
    # weather pass is one record per *place*; this one is one record per *(member, place)* — five
    # people avoiding the same category produce five records on one place, each pinned to its own
    # member's own preference version, because D13's channel rule is about *who may see the
    # reason* and one shared record could not answer that.
    #
    # The avoided sets are fetched once for the whole circle. D44 still holds: the contributor is
    # called once per place and is handed one place's category and one member's set — it never
    # sees the pool and never queries.
    avoided_rows = (
        await session.execute(
            text(
                "select member_id, value, id from ("
                "  select distinct on (member_id, value) member_id, value, stance, id,"
                "         persist, valid_from"
                "    from preference"
                # **`kind` named explicitly, never by omission.** Revision 0023 added
                # `avoid_ingredient`, which carries a stance and a value from a different closed
                # list; a query that selected every stance-bearing row would compare an ingredient
                # against `place.category` and match nothing — right today, and right by *type
                # confusion* rather than by design. The day a place carries ingredient data, whoever
                # wires it up would find a contributor that had been comparing the wrong column for
                # months, and the natural fix — widen the set — would start matching ingredients
                # against categories. Owner-ruled 2026-08-18 (D103): the ingredient pass is its own,
                # below, and inert for a stated reason instead of an accidental one.
                "   where kind = 'avoid_category'"
                "     and member_id in (select id from member where circle_id = :c)"
                "   order by member_id, value, valid_from desc, id desc"
                # D25 as amended: the latest row per key is taken first, and if THAT row is a
                # lapsed `persist = false` the key has nothing in force — nothing older is
                # consulted, so a lapsed `allow` never uncovers a kept `avoid`.
                ") latest where stance = 'avoid' and " + IN_FORCE_PREDICATE
            ),
            {"c": round_row.circle_id},
        )
    ).all()
    # member_id -> {category: preference_id}. The id is the *version in force*, which is what the
    # contribution pins so a round can be re-read and a used version cannot be erased (D25).
    by_member: dict[int, dict[str, int]] = {}
    for row in avoided_rows:
        by_member.setdefault(row.member_id, {})[row.value] = row.id

    # **N for D103's discount: the seats pinned at the round's open, never live membership.** An
    # avoided category costs a place `1 − 1/N` (A13), so N is arithmetic the round's result depends
    # on — and reading `member` here is the bug revision 0027 exists for, one table over: the
    # discount would move whenever the circle's membership changed, so a closed round's weights
    # would stop reconciling and an open round's odds would shift under a member who joined
    # mid-round. A round with no pinned seats predates 0027 and falls back, because there is
    # nothing honest to reconstruct — the same fallback, and the same reason, as the roll's.
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
    member_count = len(seat_ids)

    for member_id, avoided in sorted(by_member.items()):
        for row in pool:
            contribution = avoid_contribution(
                next_id, row.place_id, row.category, avoided.keys(), member_count
            )
            if contribution is None:
                continue
            pinned.append(
                PinnedContribution(
                    contribution=contribution,
                    pin=PreferencePin(preference_id=avoided[row.category]),
                    reason_visibility=REASON_VISIBILITY,
                    member_id=member_id,
                )
            )
            next_id += 1

    # --- A19's ingredient pass was removed on 2026-08-30 -------------------------------------
    #
    # **The surface left, so the read left with it (owner: 「覆蓋率太小了，沒有意義」 — 12.4% of the
    # city declares anything).** `POST /circles/{id}/preferences` refuses `avoid_ingredient` from
    # today, so no new row of that kind can be written; the 81 already stored stay, and this loader
    # no longer looks at them. **A contributor that can only ever fire on rows nothing can create
    # is worse than none** — it reads as live code to whoever meets it next.
    #
    # **What stayed, and it is most of the work:** the ingest, `product_material`, the brand
    # publication, `upto.seed.ingredient_terms`, `upto.engine.ingredient` and its unit test, the
    # `weight_contribution` rows already written (history — D24's pins reference them), and
    # `pool_swept`, which is the guard for the next ×0 anyone rules. Re-adding the pass is a query
    # and a loop, not a feature.
    return LoadedRound(contributions=tuple(pinned), forecast_baseline=baseline)
