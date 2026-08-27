#!/usr/bin/env python3
"""A12 / D71 as reopened 2026-08-27 — the rain factor is a difference, tested without a database.

Run: python3 app/api/tests/test_rain_relative.py

**D71's worked example is the test, because the example is the decision.** Four places at
20 / 20 / 40 / 80 with equal base weights must reach ×1.00 · 1.00 · 0.83 · 0.50 and D72's table
must hand them 11 · 11 · 9 · 5 of the 36 outcomes. If a future change makes the arithmetic look
right and the apportionment wrong, that is the half a member actually rolls against.

**The uniform hour is the other half and it is the one the reopening was about.** A city-wide 80%
must produce *no record anywhere* — not a record with factor 1.0, not a sentence, nothing — and
the table must equal the base weights' apportionment. D43's rule, and the reason the retired
≥70 → ×0.8 step was wrong: it printed an effect on every row that `table.allocate` then cancelled,
because shares are `w / total`.
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.engine import fold  # noqa: E402
from upto.engine.table import allocate  # noqa: E402
from upto.engine.weather import GAP_DIVISOR, rain_contribution  # noqa: E402


def weights_for(probabilities: list) -> dict:
    """The pool as the loader would hand it over: one minimum, one record per place or none."""
    minimum = min(probabilities)
    weights = {}
    for index, probability in enumerate(probabilities, start=1):
        contribution = rain_contribution(index, index, probability, minimum)
        weights[index] = fold(index, [] if contribution is None else [contribution]).weight
    return weights


class TheLine(unittest.TestCase):
    def test_the_two_anchors_are_the_divisor(self):
        """Gap 0 → no record; gap 60 → the floor. 120 is those two and nothing else."""
        self.assertIsNone(rain_contribution(1, 1, 40, 40))
        self.assertEqual(rain_contribution(1, 1, 60, 0).effect, Decimal("0.500"))
        self.assertEqual(GAP_DIVISOR, Decimal("120"))

    def test_the_ruled_points_on_the_line(self):
        for gap, expected in ((20, "0.833"), (30, "0.750"), (10, "0.917"), (1, "0.992")):
            with self.subTest(gap=gap):
                self.assertEqual(
                    rain_contribution(1, 1, gap, 0).effect, Decimal(expected)
                )

    def test_a_gap_past_sixty_stops_at_the_floor(self):
        """**No clamp line, and that is not an omission.** `Contribution` refuses an out-of-range
        effect at construction (D45), and the fold's `Clamp` records are for a channel *product*
        of several contributions — which one place's single rain record can never be. So the floor
        is applied in the contributor and the panel shows one factor at 0.500."""
        for probability in (70, 90, 100):
            with self.subTest(probability=probability):
                contribution = rain_contribution(1, 1, probability, 0)
                self.assertEqual(contribution.effect, Decimal("0.500"))
                self.assertEqual(fold(1, [contribution]).clamps, ())

    def test_the_clamped_factor_keeps_the_column_s_shape(self):
        """0.5 and 0.500 are equal numerically and print differently on a panel."""
        self.assertEqual(str(rain_contribution(1, 1, 100, 0).effect), "0.500")

    def test_a_negative_gap_raises_rather_than_returning_nothing(self):
        with self.assertRaises(ValueError):
            rain_contribution(1, 1, 10, 40)


class TheSentence(unittest.TestCase):
    def test_it_is_exactly_as_ruled_and_names_this_township_s_own_value(self):
        contribution = rain_contribution(1, 1, 80, 20)
        self.assertEqual(contribution.reason, "這區降雨機率較高（80%）")

    def test_it_never_names_the_gap_or_the_pool(self):
        """The owner struck the gap-naming sentence: it asks the reader to know what a pool is."""
        reason = rain_contribution(1, 1, 80, 20).reason
        for word in ("池", "最乾", "點", "60", "20"):
            self.assertNotIn(word, reason, reason)


class TheWorkedExample(unittest.TestCase):
    """D71's own four places: 大安 20 / 大安 20 / 信義 40 / 士林 80, equal base weights."""

    def test_the_factors(self):
        self.assertEqual(
            list(weights_for([20, 20, 40, 80]).values()),
            [Decimal("1"), Decimal("1"), Decimal("0.833"), Decimal("0.500")],
        )

    def test_the_thirty_six_outcomes(self):
        """**D71's line says 11 · 11 · 9 · 5. The shipped table gives 11 · 10 · 9 · 6, and the
        code is right.** The ruling's example apportions 36 by plain largest remainder;
        `table.allocate` first gives every positive place one guaranteed slot (§3.0 — a place with
        real odds rounded to 0/36 would be removed in the only sense that matters) and shares the
        remaining 32. That floor lifts the *lightest* place, which here is the wettest one, from 5
        to 6 — D72 admits it in as many words as "a small distortion of the heaviest places'
        shares". The factors, which are what the ruling actually decided, match exactly.

        Escalated to orchestrator 2026-08-27: the example's second half needs amending, or the
        floor needs re-ruling. This test asserts what a member would actually roll against."""
        table = allocate(weights_for([20, 20, 40, 80]))
        self.assertEqual([table[i] for i in (1, 2, 3, 4)], [11, 10, 9, 6])
        self.assertEqual(sum(table.values()), 36)

    def test_the_ruling_s_own_numbers_under_the_arithmetic_it_used(self):
        """The same weights by plain largest remainder do give D71's 11 · 11 · 9 · 5 — so the
        discrepancy is §3.0's floor and nothing else. Pinned here so the next reader does not have
        to re-derive which of the two rules moved the number."""
        weights = weights_for([20, 20, 40, 80])
        total = sum(weights.values())
        shares = {p: w / total * 36 for p, w in weights.items()}
        counts = {p: int(s) for p, s in shares.items()}
        leftover = 36 - sum(counts.values())
        order = sorted(weights, key=lambda p: (shares[p] - int(shares[p]), -p), reverse=True)
        for place in order[:leftover]:
            counts[place] += 1
        self.assertEqual([counts[i] for i in (1, 2, 3, 4)], [11, 11, 9, 5])

    def test_the_driest_places_carry_no_record_at_all(self):
        minimum = 20
        self.assertIsNone(rain_contribution(1, 1, 20, minimum))
        self.assertIsNone(rain_contribution(2, 2, 20, minimum))


class TheUniformHour(unittest.TestCase):
    """A city-wide 80%: the case the reopening was about."""

    def test_no_record_anywhere(self):
        for probability in (0, 20, 80, 100):
            with self.subTest(probability=probability):
                self.assertIsNone(rain_contribution(1, 1, probability, probability))

    def test_and_the_table_is_the_base_weights_apportionment(self):
        uniform = allocate(weights_for([80, 80, 80, 80]))
        base = allocate({1: Decimal("1"), 2: Decimal("1"), 3: Decimal("1"), 4: Decimal("1")})
        self.assertEqual(uniform, base)
        self.assertEqual(sorted(uniform.values()), [9, 9, 9, 9])

    def test_and_a_uniform_factor_would_have_cancelled_anyway(self):
        """Why the retired step was wrong rather than merely noisy: `allocate` takes `w / total`,
        so ×0.8 on every place produces the identical table. It printed an effect it did not have."""
        every_place_nudged = allocate({i: Decimal("0.8") for i in (1, 2, 3, 4)})
        self.assertEqual(
            every_place_nudged, allocate({i: Decimal("1") for i in (1, 2, 3, 4)})
        )


class TheRetiredStep(unittest.TestCase):
    def test_the_threshold_and_its_constant_are_gone_from_the_module(self):
        """A constant left behind is a rule somebody re-wires. Asserted in source."""
        from upto.engine import weather  # noqa: PLC0415

        self.assertFalse(hasattr(weather, "RAIN_THRESHOLD"))
        self.assertFalse(hasattr(weather, "RAIN_EFFECT"))

    def test_seventy_percent_is_no_longer_a_boundary(self):
        """No step anywhere on the line: one point of gap is one step of 1/120, everywhere.

        Measured against a pool minimum of 30 rather than 0 on purpose — from 0 the gaps at 69 and
        70 are both past 60 and both sit on the floor, which would prove the clamp rather than the
        absence of a step."""
        below = rain_contribution(1, 1, 69, 30).effect
        at = rain_contribution(2, 2, 70, 30).effect
        self.assertGreater(below, Decimal("0.5"), "the floor would hide the point being made")
        # **One point of gap is 1/120 = 0.00833, and numeric(4,3) cannot hold that**, so
        # consecutive points differ by 0.008 or 0.009 depending on where the rounding falls. The
        # property is that the step is one quantum-sized notch and never a cliff — asserting a
        # single fixed difference would be asserting the rounding, and it fails on half the pairs.
        self.assertIn(below - at, (Decimal("0.008"), Decimal("0.009")), (below, at))
        steps = [
            rain_contribution(g, g, 30 + g, 30).effect - rain_contribution(
                g + 1, g + 1, 31 + g, 30).effect
            for g in range(1, 59)
        ]
        self.assertTrue(all(s in (Decimal("0.008"), Decimal("0.009")) for s in steps), steps)


if __name__ == "__main__":
    unittest.main(verbosity=2)
