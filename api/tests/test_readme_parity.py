#!/usr/bin/env python3
"""The two READMEs must state the same numbers — a gate, because a translation drifts silently.

Run: python3 app/api/tests/test_readme_parity.py    (no network, no database)

`README.md` is canonical and `README.zh-TW.md` is its Traditional Chinese copy. The failure mode
this file exists for is not a mistranslation of prose — a reader can see that — it is the English
being **updated** and the Chinese being left behind, so the public front page carries two different
measurements of the same thing and nothing complains. That happened to decision 8 in one language
before the second existed: it still claimed 12–19 s a name, which was the CPU-only figure, an order
of magnitude off, for as long as nobody re-read it.

So the check is on the part a reader cannot verify by eye: **every number, as a multiset.** Prose
may be rephrased freely; a figure may not appear in one file and not the other, and a figure may not
change in one file alone.

**Three things are deliberately excluded, and each exclusion is a decision rather than a
convenience:**

- **Fenced code blocks.** They hold commands, ports and model tags that are identical by design;
  translating them would break them, and comparing them adds nothing this does not already cover.
- **Structure is checked separately and coarsely** — same number of `##` sections, same number of
  numbered decisions, same number of tables. Not heading text, which is translated.
- **Notation that legitimately differs between the languages**, listed in `ALLOWED_NOTATION` with
  the reason. Today that is one entry: English writes `~1.69M` where Chinese writes 約 169 萬,
  because 萬 is the natural unit in Chinese and `1.69M` is not. The list is deliberately explicit —
  a rule clever enough to normalise units automatically would also normalise a real disagreement.
"""

import io
import os
import re
import unittest
from collections import Counter

APP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
EN = os.path.join(APP, "README.md")
ZH = os.path.join(APP, "README.zh-TW.md")

# A number, not swallowing trailing punctuation: `D77,` must read as 77 and not as "77,".
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

# (English token, Chinese token, why they differ). Both sides are removed from their file's tally
# before the comparison, so an entry here excuses exactly one occurrence each.
ALLOWED_NOTATION = [
    ("1.69", "169", "English ~1.69M against 約 169 萬 — 萬 is the Chinese unit and M is not"),
]


def read(path: str) -> str:
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def numbers(path: str) -> Counter:
    text = read(path)
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # commands are identical by design
    found = Counter()
    for token in NUMBER.findall(text):
        found[token.rstrip(",")] += 1
    return found


def structure(path: str) -> dict:
    text = read(path)
    return {
        "sections": len(re.findall(r"^## ", text, re.M)),
        "subsections": len(re.findall(r"^### ", text, re.M)),
        "decisions": len(re.findall(r"^\*\*\d\. ", text, re.M)),
        "tables": text.count("|---"),
    }


class TheTwoReadmesAgree(unittest.TestCase):
    def test_every_number_appears_in_both(self):
        english, chinese = numbers(EN), numbers(ZH)
        for en_token, zh_token, _why in ALLOWED_NOTATION:
            if english[en_token] and chinese[zh_token]:
                english[en_token] -= 1
                chinese[zh_token] -= 1
        english += Counter()  # drop zero counts so the diff below reads cleanly
        chinese += Counter()
        missing_from_chinese = english - chinese
        missing_from_english = chinese - english
        self.assertFalse(
            missing_from_chinese or missing_from_english,
            "the two READMEs state different numbers — the English is canonical, so a figure only "
            "in English means the Chinese was not updated, and a figure only in Chinese means it "
            "was invented\n  only in README.md:       {}\n  only in README.zh-TW.md: {}".format(
                dict(missing_from_chinese), dict(missing_from_english)
            ),
        )

    def test_the_same_shape(self):
        self.assertEqual(
            structure(EN), structure(ZH),
            "one README has sections, decisions or tables the other does not — the Chinese copy is "
            "the same document in another language, not a summary of it",
        )

    def test_each_points_at_the_other_and_says_which_is_canonical(self):
        english, chinese = read(EN), read(ZH)
        self.assertIn("README.zh-TW.md", english, "README.md does not mention the Chinese copy")
        self.assertIn("README.md", chinese, "README.zh-TW.md does not link back to the English")
        self.assertIn(
            "canonical", english.split("## Stack")[0],
            "README.md's opening does not say it is canonical — which one wins has to be stated "
            "where a reader arrives, not inferred from filenames",
        )
        # Before the first `##` section, mirroring the English check rather than counting
        # paragraphs. The paragraph-index version broke the moment the head grew a language
        # switcher and a badge row — a check that depends on how many paragraphs precede a
        # sentence is a check that fails on formatting.
        self.assertIn(
            "英文版為準", chinese.split("\n## ")[0],
            "README.zh-TW.md does not say the English is authoritative before the first section",
        )

    def test_the_check_can_fail(self):
        """A tally that differs must be caught — otherwise this file is decoration."""
        self.assertTrue(Counter({"66.0": 1}) - Counter({"60.5": 1}))


if __name__ == "__main__":
    unittest.main(verbosity=1)
