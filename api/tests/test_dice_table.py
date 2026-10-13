#!/usr/bin/env python3
"""Ticket 17 — D72's table, tested without a network or a database.

Run: python3 app/api/tests/test_dice_table.py
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.engine.table import (  # noqa: E402
    OUTCOMES,
    EmptyPoolError,
    allocate,
    build,
    place_for,
)


def w(**kwargs):
    return {int(k): Decimal(v) for k, v in kwargs.items()}


class TestAllocation(unittest.TestCase):
    def test_counts_sum_to_36_and_follow_weights(self):
        counts = allocate({1: Decimal("0.8"), 2: Decimal("1"), 3: Decimal("1")})
        self.assertEqual(sum(counts.values()), 36)
        # 0.8 : 1 : 1 of 36 → about 10.3 : 12.9 : 12.9.
        self.assertEqual(counts, {1: 10, 2: 13, 3: 13})

    def test_veto_gets_zero_outcomes_never_rounded_up(self):
        counts = allocate({1: Decimal("0"), 2: Decimal("1")})
        self.assertEqual(counts, {1: 0, 2: 36})

    def test_positive_weight_keeps_at_least_one_outcome(self):
        # 0.001 against two heavyweights rounds to zero without the floor; nothing is ever removed,
        # so that is forbidden.
        counts = allocate({1: Decimal("0.001"), 2: Decimal("2"), 3: Decimal("2")})
        self.assertEqual(sum(counts.values()), 36)
        self.assertGreaterEqual(counts[1], 1)

    def test_realised_odds_stay_within_a_slot_of_the_weights(self):
        weights = {1: Decimal("0.8"), 2: Decimal("1"), 3: Decimal("1.5"), 4: Decimal("0.5")}
        counts = allocate(weights)
        total = sum(weights.values())
        for place, weight in weights.items():
            exact = weight / total * 36
            self.assertLessEqual(abs(counts[place] - exact), 1, f"place {place}")

    def test_swept_pool_refuses(self):
        with self.assertRaises(EmptyPoolError):
            allocate({1: Decimal("0"), 2: Decimal("0")})
        with self.assertRaises(EmptyPoolError):
            allocate({})


class TestTable(unittest.TestCase):
    def test_deterministic_and_contiguous(self):
        weights = {7: Decimal("1"), 3: Decimal("1"), 5: Decimal("0.8")}
        t1, t2 = build(weights), build(dict(reversed(list(weights.items()))))
        self.assertEqual(t1, t2, "the same weights must build the same table (D72)")
        self.assertEqual(len(t1), 36)
        # Contiguous runs in place-id order: 3, then 5, then 7.
        self.assertEqual(list(t1), sorted(t1))

    def test_outcomes_are_all_36_pairs_sum_ordered(self):
        self.assertEqual(len(OUTCOMES), 36)
        self.assertEqual(OUTCOMES[0], (1, 1))
        self.assertEqual(OUTCOMES[-1], (6, 6))
        sums = [a + b for a, b in OUTCOMES]
        self.assertEqual(sums, sorted(sums))

    def test_draw_maps_every_roll_to_a_place(self):
        table = build({1: Decimal("1"), 2: Decimal("1")})
        seen = {place_for(table, d1, d2) for d1 in range(1, 7) for d2 in range(1, 7)}
        self.assertEqual(seen, {1, 2})

    def test_draw_rejects_impossible_dice(self):
        table = build({1: Decimal("1")})
        with self.assertRaises(ValueError):
            place_for(table, 0, 3)
        with self.assertRaises(ValueError):
            place_for(table, 1, 7)

    def test_vetoed_place_cannot_be_drawn(self):
        table = build({1: Decimal("0"), 2: Decimal("1"), 3: Decimal("1")})
        for d1 in range(1, 7):
            for d2 in range(1, 7):
                self.assertNotEqual(place_for(table, d1, d2), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
