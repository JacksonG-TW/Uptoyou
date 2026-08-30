"""A1 / item 4 — the private preference contributor, pure.

*Written 2026-08-18, owner-ruled (A1). D17 gives the preference a home, D25 makes it append-only,
D45 gives this channel its range, D43/D44 give this function its shape.*

One rule: if the place's category is one this member avoids, the place's odds fold by **zero**.
Below that — no category, or a category the member said nothing about — **nothing is returned**,
which is D43's no-record-no-effect, so the panel shows nothing for a place the member's
preferences left alone.

**A category is a discount and an ingredient is a veto, and the difference is the whole of D103 as
reopened 2026-08-27.** This paragraph used to argue the opposite for both — *why zero and not a
large reduction* — and the argument was sound for the case it was made about: contributions
multiply, multiplication has an absorbing zero, so a paying restaurant can never cancel a veto, and
`private`'s range `[0, 1]` exists so this channel may zero and may never lift. **That reasoning is
untouched and still governs `avoid_ingredient`.** What the owner reversed is which of the two an
avoided *category* is: a taste is not an allergy, one person's dislike of 火鍋 should cost a 火鍋
place a share of its odds rather than remove it from the room, and the share is the room's own size
— `1 − 1/N`. See `discount_for`. The bought-back objection does not apply, because the bound that
stops a commercial factor lifting a private one is the channel's, not the zero's: `commercial` is
capped at 1.5 and folds after `private` is clamped, so a discount cannot be purchased away either.

**A place with no category produces nothing, and that is neutrality rather than a penalty.** Only
a small share of the reference list carries a category yet — **8.92%, 3,254 rows of 36,499, with
one township classified and a second running (measured 2026-08-18)** — so this contributor is
correct and nearly inert until the backfill covers more. **The number in this sentence is stale
the moment a township lands and is here as an order of magnitude, not as a fact to read from.**
The live figure is `category_coverage` on `GET /circles/{id}/preferences`, computed per request,
and it moved from 6.2% to 8.92% within the same day this paragraph was first written — which is
exactly why no screen may hard-code it. Treating "unknown category" as "not avoided" is the same choice the
loader already makes for a `circle-local` place with no township (D28's ruling, read through
`upto.engine.load`): the absence of a fact is not evidence against the place.

**The function never queries anything (D43) and never sees another candidate (D44).** The loader
hands it one place's category and the set this member avoids; which preference row that set came
from is the loader's pin, not this function's concern.

**Two rules for whoever builds the budget half, because B1's ruling binds it and there is no
other code to write them in yet.** `budget` is stored and produces nothing today (no place carries
a price band), so a budget contributor is a later build — and when it arrives:

1. **An expired band must not contribute** (D25's third amendment, 2026-08-18: *carry = show, not
   act*). A persisted band whose month has ended is pre-filled and flagged on the screen and
   contributes again **only after the member taps once**, which appends a fresh row. Auto-renewing
   was rejected by name: a `persist` flag would become a perpetual constraint nobody re-chose this
   month. So the budget query filters on today — and **`current_date` is the wrong expression
   for it**: that is the database session's date, which is UTC here, while D25's boundary has
   been **Taipei's** since 2026-08-27. Use `upto.preferences._TODAY` (or `month_end_of`)
   rather than writing the comparison again; `IN_FORCE_BUDGET`'s `expired` flag is the shape
   to copy, and it is what the screen already uses to ask for the tap.
2. **A stance does not expire and must not be filtered that way.** `expires_on` is `NULL` on a
   category row by CHECK, and D25 says a stance stands until changed — so the avoided-set query
   deliberately has no date condition, and adding one would silently switch every avoidance off.

**And one that is already true and easy to break: `persist = false` rows still act.** D17 says such
a row is *used for the round in force* and erased afterwards, so the avoided-set query does not
filter on `persist` — the flag governs retention, not effect. Filtering on it would make "do not
remember this" mean "do not apply this", which is a different promise.

**The reason names the category, deliberately.** `reason` exists to explain a number to whoever
may see it (D13), and for a `private` row that is the represented member alone —
`reason_visibility = 'represented_member_panel'` since 2026-08-30 (D13 「縮小」), and the reveal
panel shows channel-only labels for this channel, so the text never reaches another person's
screen. Withholding the category from its
owner would make the column useless to the only reader it has; and it would buy nothing against a
database leak, because the `preference` row itself already states the same fact more plainly.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Collection, Optional

from upto.engine.fold import Contribution

CONTRIBUTOR_NAME = "preference"

# numeric(4,3), mirrored from the column and from `fold._EFFECT_QUANTUM`.
_QUANTUM = Decimal("0.001")


def discount_for(member_count: int) -> Decimal:
    """`1 − 1/N` — what one member's avoidance costs a place, D103 as reopened 2026-08-27.

    **An avoided category is a discount, not a veto (owner-ruled).** It used to be D45's absorbing
    zero: one person avoiding 火鍋 removed every 火鍋 place from the draw for everyone. The rule is
    now proportional to the room — at five people one objection costs a place a fifth of its odds,
    and the place stays genuinely reachable.

    **N is the round's members and it is the loader's to supply (D44, D108).** This function never
    queries and never sees the pool; it is handed one place, one member's set, and the count. The
    count is the seats **pinned at the round's open**, never live membership — reading `member` at
    roll time is the bug revision 0027 exists for.

    **N = 1 gives exactly 0, and that is right rather than a corner to guard.** A round of one
    person is that person's decision, so their avoidance is a veto — the old behaviour, reached by
    the formula instead of by a special case.

    **Two avoiders multiply and the arithmetic is D45's, not this function's.** At five members two
    objections give 0.8 × 0.8 = 0.64, folded by the private channel and clamped into [0, 1] — where
    0.64 already sits, so nothing clamps. Three at five give 0.512, and the channel bound is what
    stops any number of them reaching zero by accident.

    **`avoid_ingredient` is NOT this and stays an absorbing zero.** Somebody who does not eat 甲殼類
    does not eat it at four people or forty; there is no room size that makes a fifth of a shellfish
    acceptable. That pass produces nothing today (no place carries ingredient data — see
    `upto.engine.load`), and when it does it takes the veto, not this discount.
    """
    if member_count < 1:
        raise ValueError(
            "a round has at least one member — N is the seats pinned at open (D108), and a count "
            "of {} means the caller read something other than that".format(member_count)
        )
    return (Decimal(1) - Decimal(1) / Decimal(member_count)).quantize(
        _QUANTUM, rounding=ROUND_HALF_UP
    )

# D13's third column: who may see the reason. `table` is refused for this channel by a CHECK on
# `weight_contribution`, so the value is named here rather than left to a caller's default.
# **`_panel` since 2026-08-30 (D13 amended, owner 「縮小」).** This sentence restates the chip the
# member set themselves and removed nothing — the place still keeps a real share of the dice table
# (D103's reopening made a category a discount, not a veto). The reveal's `my_reasons` is for a fact
# a person cannot see anywhere else, which the ingredient veto is and this is not.
#
# **The new value is on the thing being narrowed, not on the thing being kept**, so `my_reasons`'s
# predicate stays `= 'represented_member'` and never learns a second value: nothing silently joins
# it, and a fifth contributor chooses between two named audiences rather than inheriting the reveal.
# It is still this member's own — the operator's panel shows it to them and to nobody else.
REASON_VISIBILITY = "represented_member_panel"


def avoid_contribution(
    contribution_id: int,
    place_id: int,
    category: Optional[str],
    avoided: Collection[str],
    member_count: int,
) -> Contribution | None:
    """One place, one member's avoided set, one record or nothing (D43, D44).

    `category` is the place's generated category (D39) or `None` when it has not been classified
    and when the place is `circle-local`. `avoided` is the categories this member has a preference
    row in force for — a set, because a member may avoid more than one. `member_count` is the
    round's N (D108's pinned seats) and produces `discount_for`'s `1 − 1/N`.
    """
    if category is None:
        return None
    if category not in set(avoided):
        return None
    return Contribution(
        id=contribution_id,
        place_id=place_id,
        channel="private",
        contributor=CONTRIBUTOR_NAME,
        effect=discount_for(member_count),
        reason="避開的類型：{}".format(category),
    )
