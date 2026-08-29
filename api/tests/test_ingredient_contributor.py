"""A19 / D103 — the ingredient veto, and the three states it must keep apart.

    python3 app/api/tests/test_ingredient_contributor.py

No network, no database. `veto_contribution` is pure: one place's declared groups, one member's
avoided set, one record or nothing (D44 — a contributor never sees the pool).
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.engine.ingredient import (  # noqa: E402
    CONTRIBUTOR_NAME, REASON_VISIBILITY, veto_contribution,
)

CRUSTACEAN = "甲殼類"
EGG = "蛋"


class ThreeStates(unittest.TestCase):
    """**The middle one is the whole point (D112).** Two of the three produce no record, and they
    are not the same absence — the loader keeps them apart so the surface can."""

    def test_declared_and_it_names_the_avoided_group(self):
        record = veto_contribution(1, 7, frozenset({EGG, CRUSTACEAN}), {CRUSTACEAN})
        self.assertIsNotNone(record)
        self.assertEqual(record.effect, Decimal(0))
        self.assertEqual(record.channel, "private")
        self.assertEqual(record.contributor, CONTRIBUTOR_NAME)
        self.assertIn(CRUSTACEAN, record.reason)

    def test_declared_and_it_does_not(self):
        """A real answer: the publisher listed their materials and none names this group."""
        self.assertIsNone(veto_contribution(1, 7, frozenset({EGG}), {CRUSTACEAN}))

    def test_not_declared_at_all(self):
        """87.6% of the city, so this is the ordinary case rather than the edge."""
        self.assertIsNone(veto_contribution(1, 7, None, {CRUSTACEAN}))

    def test_declared_nothing_is_not_the_same_object_as_undeclared(self):
        """`frozenset()` and `None` both produce no record and mean different things.

        The arithmetic cannot tell them apart and must not try — the difference is in what the
        screen may say, which is why the type carries it out of here rather than a flag.
        """
        self.assertIsNone(veto_contribution(1, 7, frozenset(), {CRUSTACEAN}))
        self.assertIsNone(veto_contribution(1, 7, None, {CRUSTACEAN}))


class TheEffectIsExactlyZero(unittest.TestCase):
    def test_zero_and_not_a_discount(self):
        """D103's reopening made an avoided CATEGORY a discount; an ingredient keeps the veto.

        「不想吃火鍋」 is a preference and a room of five should still be able to land there.
        「不吃甲殼類」 is a statement about what a person can eat.
        """
        record = veto_contribution(1, 7, frozenset({CRUSTACEAN}), {CRUSTACEAN})
        self.assertEqual(record.effect, Decimal(0))

    def test_the_effect_is_a_decimal(self):
        """D46: a float or an int here is D46 undone, and zero is the one value where it would
        never have shown. `Contribution` refused an int on this module's first run."""
        record = veto_contribution(1, 7, frozenset({CRUSTACEAN}), {CRUSTACEAN})
        self.assertIsInstance(record.effect, Decimal)


class TheReason(unittest.TestCase):
    def test_it_names_the_group_and_never_a_product(self):
        """Which item it was in is a fact about a menu, not about this round."""
        record = veto_contribution(1, 7, frozenset({CRUSTACEAN}), {CRUSTACEAN})
        self.assertEqual(record.reason, "原料含有：{}".format(CRUSTACEAN))

    def test_several_groups_read_in_a_stable_order(self):
        """Sorted, so two runs of the same round produce the same sentence — H8's record is
        compared against itself by the lineage tool."""
        a = veto_contribution(1, 7, frozenset({EGG, CRUSTACEAN}), {CRUSTACEAN, EGG})
        b = veto_contribution(1, 7, frozenset({CRUSTACEAN, EGG}), {EGG, CRUSTACEAN})
        self.assertEqual(a.reason, b.reason)

    def test_it_is_the_members_own_to_read(self):
        self.assertEqual(REASON_VISIBILITY, "represented_member")


class ItNeverSeesThePool(unittest.TestCase):
    def test_one_place_at_a_time(self):
        """D44. The signature is the assertion: no round, no pool, no session."""
        import inspect

        parameters = list(inspect.signature(veto_contribution).parameters)
        self.assertEqual(parameters, ["contribution_id", "place_id", "declared", "avoided"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
