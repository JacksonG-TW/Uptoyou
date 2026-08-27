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

from sqlalchemy import text

from upto.engine.preference import REASON_VISIBILITY, avoid_contribution
from upto.engine.store import ForecastPin, PinnedContribution, PreferencePin
from upto.engine.weather import rain_contribution


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


async def load_contributions(session, round_id: int) -> list[PinnedContribution]:
    """One round's pool, walked once; returns every pinned record the fold will see."""
    round_row = (
        await session.execute(
            text("select circle_id, target_hour, status from round where id = :r"),
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

    if readings:
        pool_minimum = min(_probability(r.value) for r in readings.values())
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
                    reason_visibility="none",
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
                "  select distinct on (member_id, value) member_id, value, stance, id"
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
                ") latest where stance = 'avoid'"
            ),
            {"c": round_row.circle_id},
        )
    ).all()
    # member_id -> {category: preference_id}. The id is the *version in force*, which is what the
    # contribution pins so a round can be re-read and a used version cannot be erased (D25).
    by_member: dict[int, dict[str, int]] = {}
    for row in avoided_rows:
        by_member.setdefault(row.member_id, {})[row.value] = row.id

    for member_id, avoided in sorted(by_member.items()):
        for row in pool:
            contribution = avoid_contribution(
                next_id, row.place_id, row.category, avoided.keys()
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

    # --- A1 / D103: the private ingredient avoidances of this circle's members ---------------
    #
    # **A separate pass with its own comparison, and it produces nothing today.** No place carries
    # ingredient data — there is no source for it and none planned — so this fetch returns the
    # member's avoidances and there is nothing to compare them against. `GET
    # /circles/{id}/preferences` reports `ingredient_coverage` as zero for exactly this reason.
    #
    # **Why it exists at all rather than being added when a source arrives.** The alternative was to
    # let ingredient rows fall through the category pass above, where they match nothing because
    # 芒果 is not one of D38's ten. That is the right answer reached by type confusion, and it hides
    # the work rather than removing it — see the comment on the `kind` filter above.
    #
    # **What the comparison will be is not decided here.** A place's ingredients are not a single
    # value like its category, so `avoid_contribution`'s shape does not carry over, and the
    # contributor stays category-only until there is data to shape it against. What is settled is
    # D45's absorbing zero: an ingredient a person does not eat is a veto, not a discount.
    #
    # **And this pass may never be applied by speak-for.** One person may roll for a circle, and they
    # may not carry an absent person's ingredient avoidance into a round that person did not join.
    # That is an API rule rather than a schema one, and it lands with the code that reads it.
    ingredient_rows = (
        await session.execute(
            text(
                "select member_id, value, id from ("
                "  select distinct on (member_id, value) member_id, value, stance, id"
                "    from preference"
                "   where kind = 'avoid_ingredient'"
                "     and member_id in (select id from member where circle_id = :c)"
                "   order by member_id, value, valid_from desc, id desc"
                ") latest where stance = 'avoid'"
            ),
            {"c": round_row.circle_id},
        )
    ).all()
    if ingredient_rows:
        # Deliberately not silent. A round whose members avoid ingredients and whose places carry no
        # ingredient data produces no record for them, and a reader of a reveal panel would
        # reasonably wonder why — so the absence is stated once per round rather than inferred.
        print(
            "engine: {} ingredient avoidance(s) in force for this circle and no place carries "
            "ingredient data, so none contributed (D103)".format(len(ingredient_rows)),
            flush=True,
        )

    return pinned
