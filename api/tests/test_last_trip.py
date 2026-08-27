#!/usr/bin/env python3
"""A14 / D114 — the last signed trip's place is ×0.5, tested without a database.

Run: python3 app/api/tests/test_last_trip.py

**The assertion that matters most is an absence, and it is not the obvious one.** A place that is
not the last trip's produces nothing — that is D43 and it is easy. The one worth reading is that
the previous *winner* produces nothing either: a round can be rolled and never signed, and a roll
that produced no meal is not evidence about where the circle has been. Only a signature makes a
trip. That distinction lives in the loader's question, so this file asserts the contributor cannot
answer it on its own — it is handed a yes or a no and has no way to confuse the two sources.
"""

import os
import sys
import unittest
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.engine.fold import CHANNEL_BOUNDS, fold  # noqa: E402
from upto.engine.trip import (  # noqa: E402
    CONTRIBUTOR_NAME,
    LAST_TRIP_EFFECT,
    REASON_VISIBILITY,
    last_trip_contribution,
)
from upto.engine.weather import rain_contribution  # noqa: E402

WENT = date(2026, 8, 20)


class TheRecord(unittest.TestCase):
    def test_it_is_half(self):
        record = last_trip_contribution(1, 42, True, WENT)
        self.assertEqual(record.effect, Decimal("0.500"))
        self.assertEqual(record.effect, LAST_TRIP_EFFECT)

    def test_it_is_contextual_and_names_its_contributor(self):
        """D46: the contributor's name is data — renaming it rewrites how historical rounds sort."""
        record = last_trip_contribution(1, 42, True, WENT)
        self.assertEqual(record.channel, "contextual")
        self.assertEqual(record.contributor, CONTRIBUTOR_NAME)

    def test_the_sentence_says_when(self):
        record = last_trip_contribution(1, 42, True, WENT)
        self.assertEqual(record.reason, "上次去過（2026-08-20）")

    def test_it_names_nobody(self):
        """A trip has a signer (D106) and the record must not carry them: §3.0's exposure is a
        person's name beside a fact, whatever the visibility column says."""
        self.assertNotIn("member", last_trip_contribution(1, 42, True, WENT).reason)

    def test_the_reason_reaches_no_screen_and_says_so(self):
        self.assertEqual(REASON_VISIBILITY, "none")

    def test_a_date_is_required_when_the_answer_is_yes(self):
        """H8: a contribution carries one human sentence or it does not exist, and 「上次去過」 with
        no day is not one."""
        with self.assertRaises(ValueError):
            last_trip_contribution(1, 42, True, None)


class TheAbsences(unittest.TestCase):
    def test_any_other_place_produces_nothing(self):
        self.assertIsNone(last_trip_contribution(1, 42, False, WENT))

    def test_a_circle_with_no_signed_trip_produces_nothing(self):
        """The loader answers `False` for every place when there is no trip at all — there is no
        third state here, and a contributor that had one could disagree with the loader."""
        self.assertIsNone(last_trip_contribution(1, 42, False, None))

    def test_the_unsigned_previous_winner_is_indistinguishable_from_any_other_place(self):
        """**D114's shape, asserted where it can be.** A rolled-but-unsigned round produced no
        meal, so it is not evidence about where the circle has been. The contributor is handed a
        yes or a no and cannot tell a winner from a trip — which is the point: only the loader
        knows, and it asks `trip`, never `round.winning_place_id` on its own."""
        self.assertIsNone(last_trip_contribution(1, 42, False, WENT))


class TheFold(unittest.TestCase):
    def test_alone_it_does_not_clamp(self):
        """One factor is its own channel product, and a product equal to the floor is not clamped."""
        folded = fold(42, [last_trip_contribution(1, 42, True, WENT)])
        self.assertEqual(folded.weight, Decimal("0.5"))
        self.assertEqual(folded.clamps, ())

    def test_with_a_rain_row_the_product_clamps_and_says_so(self):
        """**LT-11.** A place that is both the last trip's and the wettest in its pool folds
        0.5 × 0.583 = 0.2915, below D45's contextual floor. The clamp is its own panel line, or the
        two factors on screen do not multiply to the weight beside them."""
        records = [
            last_trip_contribution(1, 42, True, WENT),
            rain_contribution(2, 42, 80, 30),
        ]
        folded = fold(42, records)
        self.assertEqual(folded.channel_products["contextual"], Decimal("0.2915"))
        self.assertEqual(folded.weight, Decimal("0.5"))
        self.assertEqual(len(folded.clamps), 1)
        self.assertEqual(folded.clamps[0].channel, "contextual")
        self.assertEqual(folded.clamps[0].raw, Decimal("0.2915"))
        self.assertEqual(folded.clamps[0].clamped, Decimal("0.5"))

    def test_the_effect_sits_inside_the_channel_it_declares(self):
        """A guard on the constant rather than on a call: the day D114's number moves, it must stay
        legal for the channel or `Contribution` refuses every record this module makes."""
        low, high = CHANNEL_BOUNDS["contextual"]
        self.assertTrue(low <= LAST_TRIP_EFFECT <= high)


if __name__ == "__main__":
    unittest.main(verbosity=2)
