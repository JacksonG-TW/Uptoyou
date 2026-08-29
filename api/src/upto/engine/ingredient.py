"""A19 / D103 — an avoided ingredient a brand's own published data names is an absorbing zero.

**Why this one keeps the veto when a category no longer has one.** D103's reopening made an avoided
*category* a discount — 「不想吃火鍋」 is a preference and a room of five should still be able to
land there. **An ingredient is not a preference.** 「不吃甲殼類」 is a statement about what a person
can eat, and a place whose own publisher says it serves 蝦 is not a place that should win 16 of 36
outcomes. So `effect = 0` and D45's private bound `[0, 1]` lets it be exactly zero.

**Three states, and the middle one is the whole point (D112).**

* **declared, and it names the avoided group** — a record, ×0.
* **declared, and it does not** — no record. The publisher listed their materials and none of them
  names this group. That is a real answer.
* **not declared at all** — no record, and **the surface must not read that as either of the
  above**. 87.6% of the city publishes nothing (4,509 of 36,499 places do, measured 2026-08-29), so
  *unknown* is the ordinary case and rendering it as "no allergen here" would be the one dangerous
  thing this feature could do.

**This module decides; the loader supplies.** It is handed one place's declared groups and one
member's avoided set, exactly as `preference.avoid_contribution` is handed one category — D44's
rule that a contributor never sees the pool and never queries.

**`None` for declared is not the same as an empty set**, and the type is what carries that: `None`
means the publisher said nothing, `frozenset()` means they said something and it named no allergen.
A caller that flattens the two has thrown away the distinction the ticket exists to protect.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Collection, Optional

from upto.engine.fold import Contribution

#: D46's stable name. Renaming a contributor rewrites how historical rounds sort, so it is data.
CONTRIBUTOR_NAME = "ingredient"

#: D13 as D20 filled it: the member it speaks for may read the sentence and nobody else. Same as
#: the category avoidance one file over — a reason about a person's own body is not a panel line.
REASON_VISIBILITY = "represented_member"


def veto_contribution(
    contribution_id: int,
    place_id: int,
    declared: Optional[Collection[str]],
    avoided: Collection[str],
) -> Contribution | None:
    """One place, one member's avoided ingredients, one record or nothing.

    `declared` is the set of allergen groups this place's company publishes materials naming, or
    **`None` when the company publishes nothing at all**. `avoided` is the groups this member has a
    preference row in force for.
    """
    if declared is None:
        # Unknown, and unknown produces no record — the same as a place that declared and named
        # nothing. **The difference is not in the arithmetic and must not be**: it is in what the
        # screen is allowed to say, which is why the loader keeps the distinction and this does not
        # invent one.
        return None
    hit = sorted(set(declared) & set(avoided))
    if not hit:
        return None
    return Contribution(
        id=contribution_id,
        place_id=place_id,
        channel="private",
        contributor=CONTRIBUTOR_NAME,
        # **Zero, and D45's private bound is what permits it.** A contextual factor is clamped to
        # [0.5, 2] and could never express this; a private one may reach zero, and this is the
        # second thing in the product that does (the first was the category veto, before D103's
        # reopening took it away).
        #
        # **`Decimal(0)` and not `0` — D46, and `Contribution` refused the int on the first run.**
        # A float or an int here is D46 undone: the fold multiplies exact decimals and the whole
        # reason a member can check the arithmetic is that nothing in the chain is binary floating
        # point. Zero is the one value where it would never have shown, which is exactly why the
        # type is enforced at construction rather than at the multiply.
        effect=Decimal(0),
        # H8's record, read by the lineage tool and the ledger, and by the member it speaks for.
        # It names the group and never the product: 「這家店的原料有 甲殼類」 is what the publisher
        # said; which item it was in is a fact about a menu, not about this round.
        reason="原料含有：{}".format("、".join(hit)),
    )
