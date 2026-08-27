"""D71 as reopened 2026-08-27 — the rain contributor: relative, linear, and pure.

**The rule is about a difference, never about a level (owner-ruled 2026-08-27: 「相對」).**
`gap = this place's township 降雨機率 − the lowest 降雨機率 among the round's pool`, at the round's
target hour; `factor = 1 − gap / 120`. A city-wide 80% gives every place a gap of 0 and produces
**no record at all** (D43), instead of printing the same factor on every row for an effect D72's
apportionment cancels — `table.allocate` shares are `w / total`, so a uniform factor divides out
before it can move anything.

**Both anchors come from the record and neither was invented (D71's 2026-08-27 line ruling).**
Gap 0 → ×1.0, which is D43 saying *no difference, no record*. Gap 60 → ×0.5, where 60 is M13's
largest measured range across the 12 townships in fifteen days and 0.5 is D45's contextual floor.
The divisor 120 is those two anchors and nothing else: `1 − 60/120 = 0.5`. Re-measuring the 60
changes one number here and no part of the design.

**The floor is applied here, and that is not where the ticket expected it.** `Contribution`
refuses an effect outside its channel's range at construction (D45, mirrored from the CHECK), so a
gap above 60 cannot be handed to the fold as ×0.4 and clamped there — it would raise before the
fold saw it, and the database's `ck_contribution_contextual_range` would refuse the row anyway. The
fold's `Clamp` records exist for a *channel product* of several contributions, which one place's
single rain record can never be. So a gap over 60 yields exactly ×0.5, there is no clamp line, and
the panel shows one factor at the floor. Measured possibility, not a theoretical one: M13 saw a
range of 60 and the scale allows 100.

**The function never queries anything (D43) and never sees another candidate (D44).** The pool
minimum is computed by the loader and handed in beside the probability, exactly as `probability`
already was — the contributor still sees one place. The cost D71 accepted for this is that the same
place carries different factors in different rounds, and that the pinned reading set is the whole
pool's rather than one row's.

**The sentence is fixed by the ruling and is not a format decision.** 「這區降雨機率較高（N%）」 with
N the township's own forecast value. The owner struck the gap-naming version (「比池中最乾的區高 20
點」) as too complex — it asks the reader to know what a pool and a gap are. So the sentence states
this township's own number and lets the panel's factor carry the comparison (D20: state, never
advise).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from upto.engine.fold import CHANNEL_BOUNDS, Contribution

CONTRIBUTOR_NAME = "weather"

# The two anchors, as one number. `1 − 60/120 = 0.5`: gap 60 (M13's largest measured range) lands
# exactly on D45's contextual floor. Named because re-measuring the range is a later M13 re-run and
# this is where that one number lands.
GAP_DIVISOR = Decimal("120")

# numeric(4,3), mirrored from the column and from `fold._EFFECT_QUANTUM`.
_QUANTUM = Decimal("0.001")

# D45's contextual bounds, imported rather than restated — a second copy of a bound is how two
# copies disagree.
_FLOOR, _CEILING = CHANNEL_BOUNDS["contextual"]


def rain_contribution(
    contribution_id: int, place_id: int, probability: int, pool_minimum: int
) -> Contribution | None:
    """One place, its township's probability, the pool's lowest — one record or nothing.

    Returns `None` when this place sits in the driest township of the pool (D43: no difference,
    no record, no sentence). Raises on a negative gap, because the only way to produce one is a
    caller that did not take the minimum over the set it is now comparing against — and a silent
    `None` there would hide the bug behind behaviour that looks correct.
    """
    gap = probability - pool_minimum
    if gap < 0:
        raise ValueError(
            f"probability {probability} is below the pool minimum {pool_minimum} — the minimum "
            "must be taken over the same set this place belongs to (D44: the loader's job)"
        )
    if gap == 0:
        return None
    factor = (Decimal(1) - Decimal(gap) / GAP_DIVISOR).quantize(_QUANTUM, rounding=ROUND_HALF_UP)
    # **Quantized again after the clamp, and it is not redundant.** `_FLOOR` is `Decimal("0.5")` —
    # one decimal place — so a clamped factor would carry a different exponent from every
    # unclamped one. `Contribution` accepts both (0.5 == 0.500 numerically), and the panel would
    # print ×0.5 beside ×0.833. One shape for one column.
    factor = min(max(factor, _FLOOR), _CEILING).quantize(_QUANTUM)
    return Contribution(
        id=contribution_id,
        place_id=place_id,
        channel="contextual",
        contributor=CONTRIBUTOR_NAME,
        effect=factor,
        reason=f"這區降雨機率較高（{probability}%）",
    )
