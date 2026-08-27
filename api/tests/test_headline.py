"""A16 / D92 as amended 2026-08-27 — the winner headline's shortening.

Host-side: no network, no database. What it pins is the ruling's own worked examples, the stub
floor as measured, and the three boundaries that make the rule safe (display only, headline only,
registered rung only).

    python3 app/api/tests/test_headline.py
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto import headline as H  # noqa: E402


class RuledExamples(unittest.TestCase):
    """D92's four worked examples, verbatim from the ruling."""

    def test_the_owners_own_case(self):
        self.assertEqual(H.shorten("一階堂拉麵餐飲有限公司"), "一階堂拉麵")

    def test_a_stacked_case_strips_until_none_remains(self):
        # Three tokens deep: 股份有限公司 → 餐飲 → 國際. Strip-once would leave 欣葉國際餐飲,
        # which is the branch D92 rejected on 1,314 measured rows.
        self.assertEqual(H.shorten("欣葉國際餐飲股份有限公司"), "欣葉")

    def test_a_token_deliberately_not_on_the_list_is_untouched(self):
        # 小吃店 is a shop type and reads as part of the name; the ruling says so in as many words.
        self.assertEqual(H.shorten("鼎泰豐小吃店"), "鼎泰豐小吃店")

    def test_a_latin_name_keeps_its_spacing(self):
        # The reason `naming.core` cannot be used on a screen: it would return STARBUCKSCOFFEE.
        self.assertEqual(H.shorten("STARBUCKS COFFEE"), "STARBUCKS COFFEE")


class TheStubFloor(unittest.TestCase):
    """Owner-ruled 2026-08-27: fewer than two characters is a stub, and the original is shown.

    These are not invented inputs. They are **every** row in the latest place publication whose
    registered name strips to one character — seven of 31,119 on the registered rung, each a single
    site, measured the day the rule was ruled.
    """

    ONE_CHARACTER_ROWS = (
        "渡股份有限公司",
        "悠國際有限公司",
        "蓉有限公司",
        "崧有限公司",
        "放餐飲國際股份有限公司",
        "崤餐飲股份有限公司",
        "宮有限公司",
    )

    def test_every_measured_one_character_row_shows_its_original(self):
        for name in self.ONE_CHARACTER_ROWS:
            with self.subTest(name=name):
                self.assertEqual(H.shorten(name), name)

    def test_the_refusal_is_all_or_nothing_never_a_half_strip(self):
        """D92 says *show the original*, not *show the last safe step*.

        悠國際有限公司 could stop at 悠國際, which is neither empty nor a stub. It does not: the
        rule guards the outcome, so the whole shortening is discarded. This is the line that would
        move if the owner ever preferred the partial form.
        """
        self.assertEqual(H.shorten("悠國際有限公司"), "悠國際有限公司")
        self.assertEqual(H.shorten("放餐飲國際股份有限公司"), "放餐飲國際股份有限公司")

    def test_two_characters_is_not_a_stub(self):
        """The floor cannot be three: 欣葉 is one of the ruling's own examples."""
        self.assertEqual(H.shorten("欣葉國際餐飲股份有限公司"), "欣葉")
        self.assertEqual(H.MIN_HEADLINE_LENGTH, 2)

    def test_a_name_that_is_nothing_but_a_token_is_left_alone(self):
        self.assertEqual(H.shorten("有限公司"), "有限公司")
        self.assertEqual(H.shorten("餐飲"), "餐飲")


class OnlyTheRegisteredRung(unittest.TestCase):
    """A sign is the branch's own published sign and a brand is the company's own name.

    Neither is ours to edit — only the rung where the registry's filing is being read.
    """

    NAME = "欣葉國際餐飲股份有限公司"

    def test_registered_is_shortened(self):
        self.assertEqual(H.headline(self.NAME, "registered"), "欣葉")

    def test_sign_brand_and_circle_local_are_untouched(self):
        for source in ("sign", "brand", "circle-local"):
            with self.subTest(source=source):
                self.assertEqual(H.headline(self.NAME, source), self.NAME)

    def test_an_unknown_rung_is_untouched_rather_than_shortened(self):
        """A rung this module has not heard of is left alone — the safe direction."""
        self.assertEqual(H.headline(self.NAME, "something-new"), self.NAME)
        self.assertEqual(H.headline(self.NAME, None), self.NAME)


class TheAuthoredList(unittest.TestCase):
    """D113's discipline: small, closed, dated, one reason per row, in git."""

    def test_every_row_carries_a_date_a_count_and_a_reason(self):
        self.assertTrue(H.BUSINESS_TYPE_TOKENS)
        for token, date, rows, reason in H.BUSINESS_TYPE_TOKENS:
            with self.subTest(token=token):
                self.assertTrue(token)
                self.assertRegex(date, r"^\d{4}-\d{2}-\d{2}$")
                self.assertIsInstance(rows, int)
                self.assertGreaterEqual(len(reason), 10, "a reason, not a label")

    def test_no_token_appears_twice(self):
        tokens = [row[0] for row in H.BUSINESS_TYPE_TOKENS]
        self.assertEqual(len(tokens), len(set(tokens)))

    def test_longer_tokens_are_tried_first(self):
        """股份有限公司 must never be matched as 有限公司 with 股份 left behind."""
        lengths = [len(t) for t in H._ORDERED]
        self.assertEqual(lengths, sorted(lengths, reverse=True))
        self.assertEqual(H.shorten("大三元股份有限公司"), "大三元")

    def test_the_list_is_the_only_thing_that_strips(self):
        """A trailing word that is not on the list stays, however business-like it looks."""
        for name in ("十八巷麵店", "阿宗麵線工作室", "老王牛肉麵館"):
            with self.subTest(name=name):
                self.assertEqual(H.shorten(name), name)


class NothingIsInvented(unittest.TestCase):
    """D28: computed at read, never stored — and the output is always a prefix of the input."""

    def test_the_result_is_always_a_prefix_of_the_stored_name(self):
        cases = list(TheStubFloor.ONE_CHARACTER_ROWS) + [
            "一階堂拉麵餐飲有限公司", "欣葉國際餐飲股份有限公司", "鼎泰豐小吃店",
            "STARBUCKS COFFEE", "福利麵包食品有限公司",
        ]
        for name in cases:
            with self.subTest(name=name):
                self.assertTrue(name.startswith(H.shorten(name)))

    def test_empty_and_none_survive(self):
        self.assertIsNone(H.shorten(None))
        self.assertEqual(H.shorten(""), "")
        self.assertIsNone(H.headline(None, "registered"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
