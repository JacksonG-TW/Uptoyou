"""D114 / A14 — the place the circle went to last time is ×0.5, and nothing else is.

**One record, on one place, and only when that place is in the round's pool.** The circle's most
recently **signed** `trip` names a place (D106: a trip's place is the stored winner of the round it
signs, never a copy); if that place is proposed again, it carries a single contextual factor of 0.5.
Every other place carries nothing at all — D43's no-record-no-effect, so the panel says nothing about
a place last week did not touch.

**The previous *winner* counts for nothing, and that is the whole of D114's shape.** A round can be
rolled and never signed — nobody went, or nobody said they went — and a roll that produced no meal
is not evidence about where the circle has been. Only a signature makes a trip, so only a signature
moves a weight. The cost the ruling accepted: a circle that never signs never gets the variety this
buys, and the fix for that is people signing rather than the engine guessing.

**0.5 is D45's contextual floor, and whether a clamp line appears depends on what else landed on
the place.** This record **alone** cannot produce one: one factor is its own channel product, and a
product equal to the floor is not clamped. But the contextual channel now has two contributors, and
a place that is both the last trip's and the wettest in its pool folds `0.5 × 0.583 = 0.2915`, which
**is** clamped back to 0.5 and **does** carry D45's clamp line — the panel would otherwise show two
factors whose product is not the weight beside them. The evaluator gates that composition as LT-11.
`Contribution` refuses an effect below the floor at construction, so a future edit that tried to
push a single record under it fails where it was written rather than at the fold.

**The date in the reason is Taipei's, like every other calendar a person reads here (D25's
2026-08-27 amendment).** `signed_at` is a `timestamptz`; the record says which day the circle went,
and «which day» is a question about the people, not about the server's session timezone.

**The reason reaches no screen and still has to be right.** `REASON_VISIBILITY` is `none`, so
`api_common` nulls it for member and operator alike — it is H8's record and what `explain_round`
reads back. `tools/server_copy.py` reads the constant below to decide the sentence is not member
copy, so these characters are deliberately outside the shipped font subset.

**The function never queries anything (D43) and never sees another candidate (D44).** Whether this
place is the last trip's place is the loader's answer, handed in the way `probability` and the pool
minimum already are.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from upto.engine.fold import CHANNEL_BOUNDS, Contribution

CONTRIBUTOR_NAME = "last_trip"

# D45's contextual floor, and D114's chosen value — they are the same number and that is a
# coincidence worth naming rather than leaning on: if the ruling ever moves off 0.5 this stays a
# legal effect only while it stays inside the channel's range.
LAST_TRIP_EFFECT = Decimal("0.500")

# D13's third column, declared beside the sentence it governs. `none` is nobody's: a contextual
# reason reaches no screen. `tools/server_copy.py` reads this to decide whether the strings in this
# module are member-facing copy — see `upto.engine.weather` for the same declaration.
REASON_VISIBILITY = "none"

_FLOOR, _CEILING = CHANNEL_BOUNDS["contextual"]


def last_trip_contribution(
    contribution_id: int, place_id: int, is_last_trip_place: bool, went_on: date | None
) -> Contribution | None:
    """One place, one yes-or-no, one record or nothing.

    `is_last_trip_place` is the loader's answer to *is this the place the circle's most recently
    signed trip named*. `went_on` is that trip's date in Taipei, and it is required when the answer
    is yes: a record that cannot say **when** the circle went is a factor with no sentence, which
    H8 refuses.
    """
    if not is_last_trip_place:
        return None
    if went_on is None:
        raise ValueError(
            "the last trip's place was named without its date — a contribution carries one human "
            "sentence or it does not exist (H8), and 「上次去過」 with no day is not one"
        )
    if not _FLOOR <= LAST_TRIP_EFFECT <= _CEILING:  # pragma: no cover — a guard on a constant
        raise ValueError(
            "D114's effect {} is outside the contextual range [{}, {}] (D45)".format(
                LAST_TRIP_EFFECT, _FLOOR, _CEILING
            )
        )
    return Contribution(
        id=contribution_id,
        place_id=place_id,
        channel="contextual",
        contributor=CONTRIBUTOR_NAME,
        effect=LAST_TRIP_EFFECT,
        reason="上次去過（{}）".format(went_on.isoformat()),
    )
