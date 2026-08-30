#!/usr/bin/env python3
"""A1's private preference contributor — the pure half.

Run: python3 app/api/tests/test_preference_contributor.py    (no network, no database)

The tests worth reading are the two absences. A place with **no category** must produce nothing,
because only 6.2% of the reference list has one today and treating unknown as avoided would zero
most of the city; and a category the member said nothing about must produce nothing rather than a
factor of 1, because D43's no-record-no-effect is what keeps the reveal panel silent about places a
preference never touched.
"""

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.classify.categories import CATEGORIES as classify_categories  # noqa: E402
from upto.engine.fold import fold  # noqa: E402


def _preference_categories() -> tuple:
    """`preferences.CATEGORIES` read from the SOURCE, not imported.

    `upto.preferences` imports FastAPI at module load, which is not installed host-side — and this
    file is host-side on purpose (no network, no database, runs in the pre-commit tempo). Reading
    the literal with `ast` is this repository's own idiom for the same problem: `tools/server_copy.py`
    parses the API's source rather than importing it, for the same reason.
    """
    import ast
    import pathlib

    source = pathlib.Path(
        os.path.dirname(os.path.abspath(__file__)), "..", "src", "upto", "preferences.py"
    ).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "CATEGORIES" for t in node.targets
        ):
            return tuple(ast.literal_eval(node.value))
    raise AssertionError("preferences.py no longer assigns CATEGORIES — this guard is blind")


preference_categories = _preference_categories()
from upto.engine.preference import (  # noqa: E402
    CONTRIBUTOR_NAME,
    REASON_VISIBILITY,
    avoid_contribution,
    discount_for,
)

# The room this file assumes when the size is not the point. D110's supported shape is ten; five is
# the size every worked example in the record uses, so the arithmetic here reads against those.
FIVE = 5


class AnAvoidedCategory(unittest.TestCase):
    def test_it_discounts_the_place_by_one_over_n(self):
        """**D103 as reopened 2026-08-27: a discount, not a veto.** It used to be D45's absorbing
        zero — one person avoiding 火鍋 removed every 火鍋 place from the draw for everyone. The
        cost is now proportional to the room, and the place stays genuinely reachable."""
        record = avoid_contribution(1, 42, "火鍋", {"火鍋"}, FIVE)
        self.assertIsNotNone(record)
        self.assertEqual(record.effect, Decimal("0.800"))

    def test_it_is_a_private_contribution_by_the_named_contributor(self):
        """D46: the contributor's name is data, not a class attribute — renaming it rewrites how
        historical rounds sort."""
        record = avoid_contribution(1, 42, "火鍋", {"火鍋"}, FIVE)
        self.assertEqual(record.channel, "private")
        self.assertEqual(record.contributor, CONTRIBUTOR_NAME)

    def test_the_reason_names_the_category(self):
        """It is read by the represented member and by nobody else, and the preference row already
        states the same fact — so withholding it from its only reader buys nothing."""
        record = avoid_contribution(1, 42, "燒烤", {"燒烤", "火鍋"}, FIVE)
        self.assertIn("燒烤", record.reason)

    def test_the_reason_names_no_member(self):
        """A row that identifies a person is the exposure §3.0 is built against, whatever the
        visibility column says."""
        record = avoid_contribution(7, 42, "燒烤", {"燒烤"}, FIVE)
        self.assertNotIn("7", record.reason)

    def test_it_carries_the_place_and_the_synthetic_id_it_was_given(self):
        record = avoid_contribution(9, 314, "日式", {"日式"}, FIVE)
        self.assertEqual(record.id, 9)
        self.assertEqual(record.place_id, 314)

    def test_one_avoided_category_among_several_still_fires(self):
        record = avoid_contribution(1, 42, "小吃", {"小吃", "西式", "早餐"}, FIVE)
        self.assertIsNotNone(record)

    def test_the_visibility_this_channel_takes_is_the_panel_one(self):
        """`weight_contribution` carries a CHECK listing the four legal values; this names the one
        the contributor writes so the two cannot disagree.

        **Amended 2026-08-30 (D13's 「縮小」 ruling): `represented_member_panel`, not
        `represented_member`.** The two differ in exactly one place — `my_reasons`, the reveal's
        own-reasons list — and the narrower value is the category discount's because that sentence
        restates a chip the member set themselves and took nothing away they did not ask for.
        The ingredient veto keeps `represented_member` and keeps the reveal: a place going to zero
        is news. Both values still reach the operator's panel, and only the member they speak for.
        """
        self.assertEqual(REASON_VISIBILITY, "represented_member_panel")
        self.assertNotEqual(REASON_VISIBILITY, "table")
        self.assertNotEqual(REASON_VISIBILITY, "none")


class TheTwoCategoryListsAreRelatedAndNotEqual(unittest.TestCase):
    """A22/D38's eleventh value: what a place may BE is no longer what a member may AVOID.

    **Added 2026-08-30, and the direction is the whole assertion.** `classify.CATEGORIES` gained
    `便利商店`; `preferences.CATEGORIES` deliberately did not, because the chip row stays at ten
    until after 09-10 and a member cannot avoid a kind of place the screen never offers. The two
    tuples were identical strings for two weeks with **nothing anywhere asserting a relationship**
    — I looked, and there was no guard. Identical-by-accident is fine until the day they differ on
    purpose; from that day a silent divergence stops being a typo and becomes invisible.

    So: **⊆, never equality.** An equality test would go red the moment the eleventh value landed
    and the honest-looking fix would have been to delete the test.
    """

    def test_every_avoidable_category_is_a_category_a_place_can_have(self):
        missing = sorted(set(preference_categories) - set(classify_categories))
        self.assertEqual(missing, [], (
            "a member could avoid something no place can be — the avoidance would match nothing "
            "and read as a working filter", missing))

    def test_the_classifier_list_is_allowed_to_be_wider(self):
        """The other direction is NOT asserted, on purpose. `便利商店` lives only in the
        classifier's list today, and the day the chip row grows this test still passes."""
        self.assertIn("便利商店", classify_categories)
        self.assertNotIn("便利商店", preference_categories)

    def test_the_widening_is_exactly_one_value_today(self):
        """A count, so a second value cannot be added to one list and not the other in silence."""
        self.assertEqual(
            sorted(set(classify_categories) - set(preference_categories)), ["便利商店"])


class TheOneOverNTable(unittest.TestCase):
    """A13 — the arithmetic pinned, the way `test_rain_relative.py` pins D71's.

    Every number below is `1 − 1/N` and nothing else. They are written out rather than computed
    from the formula, because a test that re-derives the thing it checks agrees with any formula.
    """

    def test_the_ruled_sizes(self):
        for members, expected in ((1, "0.000"), (2, "0.500"), (3, "0.667"), (5, "0.800"),
                                  (10, "0.900")):
            with self.subTest(members=members):
                self.assertEqual(discount_for(members), Decimal(expected))

    def test_one_person_alone_is_still_a_veto_and_that_is_the_formula_not_a_case(self):
        """A round of one person is that person's decision. `1 − 1/1 = 0` reaches the old
        behaviour without a special case to keep in step."""
        self.assertEqual(discount_for(1), Decimal("0"))
        self.assertEqual(avoid_contribution(1, 42, "火鍋", {"火鍋"}, 1).effect, Decimal("0"))

    def test_two_avoiders_multiply_and_the_bound_is_the_channels(self):
        """D45's arithmetic, not the contributor's: 0.8 × 0.8 = 0.64 at five, inside [0, 1] so
        nothing clamps. The channel bound is what stops any number of objections reaching zero by
        accident — the contributor never sees the second record."""
        both = [avoid_contribution(i, 42, "火鍋", {"火鍋"}, FIVE) for i in (1, 2)]
        self.assertEqual(fold(42, both).weight, Decimal("0.64"))

    def test_three_avoiders_at_five_still_leave_the_place_reachable(self):
        three = [avoid_contribution(i, 42, "火鍋", {"火鍋"}, FIVE) for i in (1, 2, 3)]
        weight = fold(42, three).weight
        self.assertEqual(weight, Decimal("0.512"))
        self.assertGreater(weight, 0, "a discount that reaches zero is the veto being rebuilt")

    def test_a_count_below_one_raises_rather_than_dividing(self):
        """The only way to produce one is a caller reading something other than the round's pinned
        seats, and a silent answer there would hide it behind arithmetic that looks fine."""
        for bad in (0, -1):
            with self.subTest(members=bad), self.assertRaises(ValueError):
                discount_for(bad)

    def test_the_absorbing_zero_constant_is_gone(self):
        """A constant left behind is a rule somebody re-wires. `avoid_ingredient` keeps the veto,
        and it keeps it in `upto.engine.load`'s own pass — not by a name this module still exports.
        """
        from upto.engine import preference  # noqa: PLC0415

        self.assertFalse(hasattr(preference, "AVOID_EFFECT"))


class TheTwoAbsences(unittest.TestCase):
    def test_a_place_with_no_category_produces_nothing(self):
        """Measured 2026-08-18: 2,267 of 36,499 reference rows carry a category, because one
        township has been classified. Treating unknown as avoided would zero most of the city.
        Same choice the loader already makes for a circle-local place with no township (D28):
        the absence of a fact is not evidence against the place."""
        self.assertIsNone(avoid_contribution(1, 42, None, {"火鍋"}, FIVE))

    def test_a_category_the_member_said_nothing_about_produces_nothing(self):
        """D43's no-record-no-effect. Returning a factor of 1 would be arithmetically identical
        and would put a row on the reveal panel for a place no preference touched."""
        self.assertIsNone(avoid_contribution(1, 42, "火鍋", {"燒烤"}, FIVE))

    def test_an_empty_avoided_set_produces_nothing(self):
        self.assertIsNone(avoid_contribution(1, 42, "火鍋", set(), FIVE))

    def test_no_category_and_no_preferences_produces_nothing(self):
        self.assertIsNone(avoid_contribution(1, 42, None, set(), FIVE))


class TheSetIsTakenAsGiven(unittest.TestCase):
    def test_a_list_works_as_well_as_a_set(self):
        """The loader builds it from a query; forcing it to hand over a set would be this module
        knowing something about the caller."""
        self.assertIsNotNone(avoid_contribution(1, 42, "西式", ["西式", "早餐"], FIVE))

    def test_a_tuple_works_too(self):
        self.assertIsNotNone(avoid_contribution(1, 42, "西式", ("西式",), FIVE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
