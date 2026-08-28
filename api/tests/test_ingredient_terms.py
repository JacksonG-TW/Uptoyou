"""A19 / D103 as amended — a term matches when the word NAMES the allergen.

    python3 app/api/tests/test_ingredient_terms.py

No network, no database. What it pins is the authored table's shape and the ruled line, including
the three ways a term must conclude nothing.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.seed.ingredient_terms import REFUSED, TERMS  # noqa: E402


def endpoint_groups():
    """`upto.preferences.INGREDIENTS`, read with `ast` rather than imported.

    That module pulls in FastAPI, which this host does not have and this check has no use for —
    the same reason `test_web_surface` reads the closed lists as text. Parsing the literal the
    module defines is stronger than a copy of it here, which would agree with itself for ever.
    """
    import ast

    source = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                               "src", "upto", "preferences.py"), encoding="utf-8").read()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "INGREDIENTS" for t in node.targets
        ):
            return [e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    raise AssertionError("INGREDIENTS is not assigned in upto/preferences.py")

LOOKUP = {term: group for term, group, _d, _b, _r in TERMS}


class TheRuledExamples(unittest.TestCase):
    """The owner's own words, and the counter-example he gave with them."""

    def test_the_words_he_named(self):
        for term, group in (("雞蛋", "蛋"), ("水煮蛋", "蛋"), ("蝦仁", "甲殼類"), ("柴魚", "魚類")):
            with self.subTest(term=term):
                self.assertEqual(LOOKUP.get(term), group)

    def test_麵包_concludes_nothing(self):
        """His counter-example. The name says nothing of wheat; knowing bread contains it is the
        inference D103 forbids."""
        self.assertIsNone(LOOKUP.get("麵包"))

    def test_蛋糕_and_皮蛋_land_on_opposite_sides(self):
        """The pair that makes a substring rule impossible: same character, opposite answers."""
        self.assertEqual(LOOKUP.get("皮蛋"), "蛋")
        self.assertIsNone(LOOKUP.get("蛋糕"))


class ThreeWaysToConcludeNothing(unittest.TestCase):
    def test_a_compound_name_that_names_something_else(self):
        for term in ("蛋糕專用脂", "蛋餅皮", "燕麥奶"):
            with self.subTest(term=term):
                self.assertIsNone(LOOKUP.get(term))

    def test_a_sauce_or_a_form_word(self):
        for term in ("美乃滋", "奶精", "奶精粉", "奶蓋粉"):
            with self.subTest(term=term):
                self.assertIsNone(LOOKUP.get(term))

    def test_a_brand_only_name(self):
        """`原料品牌` values and branded raw materials name a company, not a food."""
        for term in ("瑞穗鮮乳(悠旅生活事業專用)", "CITY CAFE專用乳", "Let's Cafe 經典豆"):
            with self.subTest(term=term):
                self.assertIsNone(LOOKUP.get(term))

    def test_an_unknown_term_is_unknown_and_not_safe(self):
        """The whole design in one assertion: absence is `None`, never a group and never a
        statement that the food is free of anything."""
        self.assertIsNone(LOOKUP.get("這個原料不在表裡"))


class TheTableIsAuthoredNotGenerated(unittest.TestCase):
    """D113's discipline: small, closed, dated, one reason per row, in git."""

    def test_every_row_carries_a_date_a_basis_and_a_reason(self):
        self.assertTrue(TERMS)
        for term, group, authored, basis, reason in TERMS:
            with self.subTest(term=term):
                self.assertTrue(term)
                self.assertRegex(authored, r"^\d{4}-\d{2}-\d{2}$")
                self.assertEqual(basis, "names-it",
                                 "a second basis must argue for itself, not arrive in a list")
                self.assertGreaterEqual(len(reason), 10, "a reason, not a label")

    def test_every_group_is_one_the_endpoint_accepts(self):
        """A term pointing at a group `upto.preferences` does not know would match a preference
        nobody can express."""
        groups = endpoint_groups()
        self.assertTrue(groups, "parsed nothing from preferences.py")
        for term, group, *_ in TERMS:
            with self.subTest(term=term):
                self.assertIn(group, groups)

    def test_no_term_appears_twice(self):
        terms = [t[0] for t in TERMS]
        self.assertEqual(len(terms), len(set(terms)))

    def test_nothing_is_both_authored_and_refused(self):
        self.assertFalse({t[0] for t in TERMS} & {r[0] for r in REFUSED})

    def test_every_refusal_says_why(self):
        """The absence IS the decision, so it carries a reason like the presences do."""
        self.assertTrue(REFUSED)
        for term, reason in REFUSED:
            with self.subTest(term=term):
                self.assertGreaterEqual(len(reason), 20, "a refusal is a decision, not a line")


class NoSubstringRuleEverCreepsBackIn(unittest.TestCase):
    """The rule is a lookup, and this is the assertion that fails if somebody makes it a scan."""

    def test_the_lookup_is_exact(self):
        # Every authored term is a key; nothing longer that contains one is.
        self.assertIn("蛋", LOOKUP)
        for longer in ("蛋糕", "皮蛋糕", "鮮奶油蛋糕"):
            if longer not in LOOKUP:
                with self.subTest(term=longer):
                    self.assertIsNone(LOOKUP.get(longer))

    def test_a_term_containing_an_authored_one_is_not_matched_by_it(self):
        self.assertIn("牛奶", LOOKUP)
        self.assertIsNone(LOOKUP.get("牛奶糖風味粉"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
