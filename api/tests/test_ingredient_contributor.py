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


class FourStates(unittest.TestCase):
    """Owner-ruled 2026-08-30 (D103 amended). Two of the four produce no record and they are not
    the same absence; two produce one and they are not the same record."""

    def test_every_published_product_names_it(self):
        record = veto_contribution(1, 7, {"a": {EGG}, "b": {EGG, CRUSTACEAN}}, {EGG})
        self.assertEqual(record.effect, Decimal(0))
        self.assertEqual(record.reason, "原料含有：蛋")
        self.assertEqual(record.channel, "private")
        self.assertEqual(record.contributor, CONTRIBUTOR_NAME)

    def test_some_do_and_some_do_not(self):
        """**全家's case: 1 of 87.** The place participates at full weight and the member is told.

        Zeroing a store because one of eighty-seven products names 蛋 would tell somebody they
        cannot go where they can plainly eat something else.
        """
        record = veto_contribution(1, 7, {"a": {EGG}, "b": {CRUSTACEAN}, "c": set()}, {EGG})
        self.assertEqual(record.effect, Decimal(1))
        self.assertEqual(record.reason, "部分品項含有：蛋")

    def test_a_single_published_product_that_names_it_is_still_zero(self):
        """"Every" means every PUBLISHED product, and this is the sharp edge of the ruling: a
        company publishing one product that names 蛋 is ×0 even if it sells fifty. The rest are
        unknown, never safe, and the rule fails in the direction that does not put somebody in a
        place they cannot eat in."""
        record = veto_contribution(1, 7, {"a": {EGG}}, {EGG})
        self.assertEqual(record.effect, Decimal(0))

    def test_declared_and_none_of_them_names_it(self):
        """A real answer: the publisher listed their materials and none is this group."""
        self.assertIsNone(veto_contribution(1, 7, {"a": {CRUSTACEAN}, "b": set()}, {EGG}))

    def test_not_declared_at_all(self):
        """87.6% of the city, so this is the ordinary case rather than the edge."""
        self.assertIsNone(veto_contribution(1, 7, None, {EGG}))

    def test_declared_nothing_is_not_the_same_object_as_undeclared(self):
        """`{}` and `None` both produce no record and mean different things.

        The arithmetic cannot tell them apart and must not try — the difference is in what the
        screen may say, which is why the type carries it out of here rather than a flag.
        """
        self.assertIsNone(veto_contribution(1, 7, {}, {EGG}))
        self.assertIsNone(veto_contribution(1, 7, None, {EGG}))


class TheEffectIsExactlyZero(unittest.TestCase):
    def test_zero_and_not_a_discount(self):
        """D103's reopening made an avoided CATEGORY a discount; an ingredient keeps the veto.

        「不想吃火鍋」 is a preference and a room of five should still be able to land there.
        「不吃甲殼類」 is a statement about what a person can eat.
        """
        record = veto_contribution(1, 7, {"a": {CRUSTACEAN}}, {CRUSTACEAN})
        self.assertEqual(record.effect, Decimal(0))

    def test_both_effects_are_decimals(self):
        """D46. Zero and one are the two values where a float would never have shown itself in the
        arithmetic, which is exactly why the type is enforced when the record is built."""
        for declared in ({"a": {CRUSTACEAN}}, {"a": {CRUSTACEAN}, "b": set()}):
            with self.subTest(declared=declared):
                self.assertIsInstance(veto_contribution(1, 7, declared, {CRUSTACEAN}).effect,
                                      Decimal)

    def test_the_partial_record_multiplies_by_one(self):
        """It exists to carry the SENTENCE, not an effect — a deliberate departure from D43's
        *no record when nothing changed*, because `my_reasons` is read from the ledger and a member
        cannot be told anything the ledger does not hold."""
        record = veto_contribution(1, 7, {"a": {CRUSTACEAN}, "b": set()}, {CRUSTACEAN})
        self.assertEqual(record.effect, Decimal(1))


class TheReason(unittest.TestCase):
    def test_it_names_the_group_and_never_a_product(self):
        """Which item it was in is a fact about a menu, not about this round."""
        record = veto_contribution(1, 7, {"a": {CRUSTACEAN}}, {CRUSTACEAN})
        self.assertEqual(record.reason, "原料含有：{}".format(CRUSTACEAN))

    def test_several_groups_read_in_a_stable_order(self):
        """Sorted, so two runs of the same round produce the same sentence — H8's record is
        compared against itself by the lineage tool."""
        a = veto_contribution(1, 7, {"a": {EGG, CRUSTACEAN}}, {CRUSTACEAN, EGG})
        b = veto_contribution(1, 7, {"a": {CRUSTACEAN, EGG}}, {EGG, CRUSTACEAN})
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
