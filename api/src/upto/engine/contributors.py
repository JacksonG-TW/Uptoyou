"""The canonical list of what can weigh a place, in D46's fold order. One place, one list.

*Written 2026-09-11 for 甲's operator picture (`spec-weights-picture-2026-09-11.md` §5).* The
reveal panel draws one bar per contributor and **four rows always**, because «上次去過 showing
nothing is information» — it says this place was not last week's. A row that is simply absent
when a contributor did not fire would make the client infer silence from an absence, which §4 of
that spec forbids and which is a guess the payload can answer instead.

**Why the list lives here and not in `api_common.panel_for`.** The panel is a *view*. If the list
of what can weigh a place lived in the view, adding a fifth contributor would mean editing a
payload builder to keep a drawing honest, and the drawing would go quietly wrong — three bars
where four belong — for anyone who forgot. Beside the contributors it sits next to the modules
that produce the rows, which is where somebody adding one is already reading.

**The order is not written down here either, and that is the same argument one level down.** D46's
total order is `(channel, contributor, id)` and it lives in `fold.Contribution.sort_key`; this
module sorts by that key rather than restating it, so the pad and the fold cannot disagree about
where a row goes. A list that restated the order would be a second copy of D46 — and the panel's
own comment already says «the panel must never re-sort».

**Three, not four, and the fourth row is 起點.** The picture's first row is the fold's starting
weight of 1, which is not a contribution and has no `weight_contribution` row: `fold()` begins at
`Decimal("1")` and multiplies. So the payload carries it as its own field and the three real
contributors as `factors`. Padding a fabricated 起點 row into `factors` would put a row in that
list that no record backs, in the one payload an operator audits against the database.

**`ingredient` is deliberately absent.** A19's pass was removed on 2026-08-30 (`engine/load.py`
says so in those words: «a contributor that can only ever fire on rows nothing can create is worse
than none»). Listing it here would draw a fourth bar, empty for ever, on every reveal — the exact
shape that argument rejects. When the veto returns, it returns here and the picture gains a row.
"""

from __future__ import annotations

from decimal import Decimal

from .fold import CHANNELS, Contribution
from .preference import CONTRIBUTOR_NAME as PREFERENCE
from .trip import CONTRIBUTOR_NAME as LAST_TRIP
from .weather import CONTRIBUTOR_NAME as WEATHER

#: `(channel, contributor)` for everything that can weigh a place today. **The names are imported
#: from the modules that write them**, so a rename moves both ends at once rather than leaving a
#: pad that silently never matches the rows it is meant to complete.
KNOWN: tuple[tuple[str, str], ...] = (
    ("private", PREFERENCE),
    ("contextual", LAST_TRIP),
    ("contextual", WEATHER),
)

#: What the fold starts at, before any contributor — the picture's 起點 row. Stated here rather
#: than as a literal `1` in the payload so the two cannot part company if the fold's base ever
#: becomes something a ruling chose instead of something arithmetic requires.
BASE = "1"

# `Contribution` validates its effect against the channel's bounds at construction (D45), and
# every channel's range contains 1 — so this is a legal probe row for every entry in `KNOWN`,
# including any added later. It exists only to be handed to `sort_key`.
_ONE = Decimal("1")


def in_fold_order() -> tuple[tuple[str, str], ...]:
    """`KNOWN`, ordered by D46's own key rather than by how it was typed above.

    The id is `0` for every entry because a pad row has no record; it is the tie-break within one
    contributor and no two entries here share a contributor, so it never decides anything.
    """
    return tuple(
        (channel, contributor)
        for channel, contributor in sorted(
            KNOWN,
            key=lambda pair: Contribution(
                id=0, place_id=0, channel=pair[0], contributor=pair[1],
                effect=_ONE, reason="pad",
            ).sort_key,
        )
    )


def pad(real: list[dict]) -> list[dict]:
    """Every known contributor present, at its D46 position, un-fired ones included.

    *甲's operator picture, 2026-09-11 (`spec-weights-picture-2026-09-11.md` §5).* The drawing has
    **four rows always** — 起點 plus one per contributor — because «上次去過 showing nothing is
    information»: it says this place was not last week's. Without the pad the client would have to
    read that from an *absence*, which is an inference the payload can answer instead, and which
    §4 of the spec forbids.

    **`fired` is the field, and it is not decoration.** A padded row and a real one that measured
    no difference both read ×1: the rain factor is `1 − gap/120`, so a township with the pool's
    lowest 降雨機率 stores exactly 1.000 (A12/D71). «Measured, no difference» and «did not run»
    would otherwise be the same three characters on the operator's screen, and they are not the
    same fact. The picture draws a bar for one and an empty track with 「—」 for the other.

    **The pad is a display completion, never an arithmetic one.** Each carries `effect` "1" and a
    null reason, and `fold()` never sees any of it — the weight, the channel products and D45's
    clamp lines are computed from the stored rows alone, above. A padded row multiplied into the
    fold would be harmless today at ×1 and would be a second bookkeeping the moment anything
    about it moved.

    **A stable sort on `(channel, contributor)` and no id**, so real rows keep the order the fold
    already put them in — `folded.contributions` is D46's total order, and the panel must never
    re-sort. A contributor the canonical list does not name (a historical `ingredient` row, say)
    is not dropped: it sorts by its own key like everything else and simply gets no pad.
    """
    present = {(row["channel"], row["contributor"]) for row in real}
    pads = [
        {
            "channel": channel,
            "contributor": contributor,
            "effect": BASE,
            "reason": None,
            "fired": False,
        }
        for channel, contributor in in_fold_order()
        if (channel, contributor) not in present
    ]
    return sorted(
        real + pads,
        key=lambda row: (CHANNELS.index(row["channel"]), row["contributor"]),
    )
