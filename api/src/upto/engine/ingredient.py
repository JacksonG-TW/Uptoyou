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
from typing import Collection, Mapping, Optional

from upto.engine.fold import Contribution

#: D46's stable name. Renaming a contributor rewrites how historical rounds sort, so it is data.
CONTRIBUTOR_NAME = "ingredient"

#: D13 as D20 filled it: the member it speaks for may read the sentence and nobody else. Same as
#: the category avoidance one file over — a reason about a person's own body is not a panel line.
REASON_VISIBILITY = "represented_member"


def veto_contribution(
    contribution_id: int,
    place_id: int,
    declared: Optional[Mapping[str, Collection[str]]],
    avoided: Collection[str],
) -> Contribution | None:
    """One place, one member's avoided ingredients, one record or nothing.

    `declared` maps **each published product** of this place's company to the allergen groups its
    materials name — or is **`None` when the company publishes nothing at all**. `avoided` is the
    groups this member has a preference row in force for.

    **Owner-ruled 2026-08-30 (D103 amended): the veto is per product, not per store.** 全家 publishes
    87 products and one of them names 蛋; zeroing the whole store for that would tell a member they
    cannot go somewhere that sells them something else. So:

    * **every published product names it → ×0.** There is nothing there for this member.
    * **some do and some do not → full weight, and a sentence.** The place participates; the member
      is told 「部分品項含有：蛋」 and chooses for themselves.
    * **none does → no record.** The publisher listed their materials and none is this group.
    * **nothing published → no record**, and the surface must not read that as the line above.

    **"Every" means every *published* product, and that is the sharp edge of the ruling.** A company
    publishing three products, all naming 蛋, is ×0 even if it sells fifty — the other forty-seven
    are *unknown*, never *safe*. The rule cannot do better without data nobody has, and it fails in
    the direction that does not put someone in a place they cannot eat in.

    *Rejected on the record:* whole-store (the 全家 case above); a discount by share (a fraction of
    a dice table is a number about a menu, not about whether a person can eat).

    **The partial case produces a record whose effect is exactly 1, which is a deliberate departure
    from D43** (*no record when nothing changed*). The record exists to carry the **sentence** —
    `my_reasons` is read from `weight_contribution.reason`, so a member cannot be told anything the
    ledger does not hold. It multiplies by one, so the arithmetic is unchanged and `write_roll`'s
    reconciliation still balances.
    """
    if declared is None:
        # Unknown, and unknown produces no record — the same as a company that declared and named
        # nothing. **The difference is not in the arithmetic and must not be**: it is in what the
        # screen is allowed to say, which is why the loader keeps the distinction and this does not
        # invent one.
        return None
    if not declared:
        return None
    wanted = set(avoided)
    naming = {
        product: sorted(set(groups) & wanted)
        for product, groups in declared.items()
        if set(groups) & wanted
    }
    if not naming:
        return None
    hit = sorted({group for groups in naming.values() for group in groups})
    everything = len(naming) == len(declared)
    return Contribution(
        id=contribution_id,
        place_id=place_id,
        channel="private",
        contributor=CONTRIBUTOR_NAME,
        # **`Decimal`, not `0` or `1` — D46, and `Contribution` refused an int on this module's
        # first run.** Zero and one are the two values where a float would never have shown itself
        # in the arithmetic, which is exactly why the type is enforced when the record is built.
        #
        # **Zero is the absorbing one and D45's private bound `[0, 1]` is what permits it**; a
        # contextual factor is clamped to `[0.5, 2]` and could express neither end.
        effect=Decimal(0) if everything else Decimal(1),
        # H8's record, read by the lineage tool and the ledger, and by the member it speaks for. It
        # names the group and never the product: which item it was in is a fact about a menu, not
        # about this round — and naming the item would put a menu on a wire that carries none.
        reason="{}：{}".format(
            "原料含有" if everything else "部分品項含有", "、".join(hit)
        ),
    )
