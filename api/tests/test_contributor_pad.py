#!/usr/bin/env python3
"""甲's operator picture: the panel carries every contributor, fired or not, in D46's order.

*Written 2026-09-11 with candidate 16, for `spec-weights-picture-2026-09-11.md` §5.* The drawing
has four rows always — 起點 plus one per contributor — because «上次去過 showing nothing is
information»: it says this place was not last week's. If the payload omitted a silent contributor
the client would infer that from an absence, which §4 of the spec forbids.

**Host-side, and that is the point of where the code lives.** `engine.contributors` imports
nothing but `decimal` and its sibling engine modules, so the rule this file asserts needs no
database, no FastAPI and no image. The wiring — that `panel_for` actually calls it and that the
key reaches the operator's wire and not a member's — is `test_api_rounds_integration`'s and
`test_operator_view_integration`'s, and neither file is sufficient without the other.

    python3 app/api/tests/test_contributor_pad.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from upto.engine import contributors  # noqa: E402
from upto.engine.fold import CHANNELS  # noqa: E402


def real(contributor: str, channel: str, effect: str, reason=None) -> dict:
    return {"channel": channel, "contributor": contributor, "effect": effect,
            "reason": reason, "fired": True}


class TheListIsInTheFoldsOwnOrder(unittest.TestCase):
    """D46's total order is `(channel, contributor, id)` and lives in `Contribution.sort_key`.

    **Asserted against that key rather than against a written-down list**, because a written-down
    list is a second copy of D46 — and the panel's own comment says it must never re-sort.
    """

    def test_the_order_is_private_then_contextual_by_name(self):
        self.assertEqual(
            contributors.in_fold_order(),
            (("private", "preference"), ("contextual", "last_trip"), ("contextual", "weather")),
        )

    def test_every_entry_sorts_where_the_fold_would_put_it(self):
        keys = [(CHANNELS.index(ch), name) for ch, name in contributors.in_fold_order()]
        self.assertEqual(keys, sorted(keys))

    def test_the_withdrawn_ingredient_pass_is_NOT_listed(self):
        """A19's pass left on 2026-08-30. Listing it would draw an empty bar for ever — the exact
        shape `engine/load.py` rejects in «a contributor that can only ever fire on rows nothing
        can create is worse than none»."""
        self.assertNotIn("ingredient", [name for _, name in contributors.KNOWN])


class ThePadCompletesTheDrawingAndNothingElse(unittest.TestCase):
    def test_an_empty_round_still_carries_every_contributor(self):
        rows = contributors.pad([])
        self.assertEqual([r["contributor"] for r in rows],
                         ["preference", "last_trip", "weather"])
        self.assertTrue(all(r["fired"] is False for r in rows))
        self.assertTrue(all(r["effect"] == contributors.BASE for r in rows))
        self.assertTrue(all(r["reason"] is None for r in rows))

    def test_a_real_row_keeps_its_own_values_and_the_rest_are_padded(self):
        rows = contributors.pad([real("weather", "contextual", "0.79", "雨")])
        self.assertEqual([r["contributor"] for r in rows],
                         ["preference", "last_trip", "weather"])
        weather = rows[-1]
        self.assertEqual((weather["effect"], weather["reason"], weather["fired"]),
                         ("0.79", "雨", True))
        self.assertTrue(all(r["fired"] is False for r in rows[:-1]))

    def test_a_padded_row_is_distinguishable_from_a_real_one_that_measured_no_difference(self):
        """**The line `fired` exists for.** The rain factor is `1 − gap/120`, so the township with
        the pool's lowest 降雨機率 stores exactly 1.000 (A12/D71). «Measured, no difference» and
        «did not run» would read the same without this field, and they are not the same fact."""
        rows = contributors.pad([real("weather", "contextual", "1")])
        weather = [r for r in rows if r["contributor"] == "weather"]
        self.assertEqual(len(weather), 1)
        self.assertTrue(weather[0]["fired"])
        self.assertTrue(all(not r["fired"] for r in rows if r["contributor"] != "weather"))

    def test_several_rows_of_one_contributor_are_all_kept_in_their_given_order(self):
        """Three members avoiding a category is three `preference` rows, not one. The pad must not
        collapse them, and must not re-order them — the fold already did that (D46)."""
        rows = contributors.pad([
            real("preference", "private", "0.8", "a"),
            real("preference", "private", "0.8", "b"),
            real("preference", "private", "0.8", "c"),
        ])
        self.assertEqual([r["contributor"] for r in rows],
                         ["preference", "preference", "preference", "last_trip", "weather"])
        self.assertEqual([r["reason"] for r in rows[:3]], ["a", "b", "c"])

    def test_a_contributor_the_list_does_not_name_is_kept_rather_than_dropped(self):
        """A historical `ingredient` row is real history — D24 pins rows that reference it. The pad
        completes a drawing; it is not a filter, and an operator auditing an old round must still
        see what actually weighed that place."""
        rows = contributors.pad([real("ingredient", "private", "0")])
        self.assertIn("ingredient", [r["contributor"] for r in rows])
        self.assertEqual(len(rows), 4)

    def test_the_pad_never_changes_the_arithmetic(self):
        """**A display completion, never an arithmetic one.** Every padded row is ×1 by
        construction, so nothing here can move a weight even if something did multiply it."""
        for row in contributors.pad([]):
            self.assertEqual(row["effect"], "1")

    def test_the_base_is_not_padded_into_the_factors(self):
        """起點 is the fold's starting weight, not a contribution — `fold()` begins at `Decimal(1)`
        and multiplies. It travels as its own field, because `factors` mirrors
        `weight_contribution` rows and the payload an operator audits must carry no row that no
        record backs."""
        self.assertNotIn("base", [r["contributor"] for r in contributors.pad([])])
        self.assertNotIn("起點", [r["contributor"] for r in contributors.pad([])])


if __name__ == "__main__":
    unittest.main(verbosity=2)
