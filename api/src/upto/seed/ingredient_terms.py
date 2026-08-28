"""A19 / D103 as amended 2026-08-28 — raw-material names that NAME an allergen.

**The rule, owner-ruled (「算」).** A term matches when **the word itself names the allergen**.
雞蛋 · 水煮蛋 · 蝦仁 · 柴魚 do. **麵包 does not** — its name says nothing of wheat, and knowing that
bread contains wheat is exactly the inference D103 forbids at scale.

**No substring rule, ever.** 蛋糕 and 皮蛋 both contain 蛋 and a machine cannot tell them apart:
one names a cake, the other names an egg. So **every term below is its own authored row**, dated,
with the reason it is here and a `basis` — D113's discipline, and the second body of data in this
product that no publisher stands behind.

**A term that is not in this table concludes NOTHING.** That is the safe direction and it is the
whole design: absence is `unknown`, never `no allergen`. The table may be added to for ever and is
correct at every size — what it must never do is guess.

**Read `doc/defences.md` D103 before adding a row.** The test to apply is not *does this food
contain the allergen* — it is *does this word name it*. A row that needs the first question answered
is a row that does not belong here.

**Scope, stated because the numbers are surprising.** The source is D77's own file (data.taipei
00004058), 38,101 rows, 4,387 distinct 原料名稱. **870 of them contain an allergen word**; the top
fifty cover 61% of those rows and the top hundred 71%. This table starts at the frequent and
unambiguous end. **It is not complete and does not need to be.**
"""

from __future__ import annotations

#: The eleven groups are `upto.preferences.INGREDIENTS`. These are the ones a term can name today;
#: a group with no term simply has none, which is a true statement and not a gap to fill.
EGG = "蛋"
MILK = "牛奶／羊奶"
FISH = "魚類"
SOY = "大豆"
CRUSTACEAN = "甲殼類"
SESAME = "芝麻"
NUTS = "堅果類"
GLUTEN = "含麩質之穀物"
PEANUT = "花生"

#: `(term, group, authored, basis, reason)`.
#:
#: `basis` is `names-it` for every row here and the column exists so a second basis has to argue
#: for itself in a review rather than arrive inside a list — the same reason D113's aliases carry
#: one. A row whose reason needs a fact about the recipe rather than about the word is not
#: `names-it` and does not belong.
TERMS: tuple[tuple[str, str, str, str, str], ...] = (
    # ---- egg -------------------------------------------------------------------------------
    ("蛋", EGG, "2026-08-28", "names-it", "the word is the allergen"),
    ("雞蛋", EGG, "2026-08-28", "names-it", "chicken egg — 蛋 is the head noun, 雞 names the bird"),
    ("洗選蛋", EGG, "2026-08-28", "names-it", "washed-and-graded egg; 蛋 is the head noun"),
    ("蛋黃液", EGG, "2026-08-28", "names-it", "liquid egg yolk — the yolk is the egg"),
    ("蛋白液", EGG, "2026-08-28", "names-it", "liquid egg white — the white is the egg"),
    ("鹹蛋黃", EGG, "2026-08-28", "names-it", "salted egg yolk"),
    ("糖心蛋", EGG, "2026-08-28", "names-it", "soft-yolk egg; 蛋 is the head noun"),
    ("水煮蛋", EGG, "2026-08-28", "names-it", "boiled egg"),
    ("皮蛋", EGG, "2026-08-28", "names-it",
     "century egg — it IS a preserved duck egg. Beside 蛋糕 on purpose: a machine cannot tell "
     "these two apart, which is why neither is decided by a rule"),
    # ---- milk ------------------------------------------------------------------------------
    ("牛奶", MILK, "2026-08-28", "names-it", "the word is the allergen"),
    ("鮮奶", MILK, "2026-08-28", "names-it", "fresh milk"),
    ("鮮乳", MILK, "2026-08-28", "names-it", "fresh milk, the other common spelling"),
    ("牛乳", MILK, "2026-08-28", "names-it", "cow's milk"),
    ("保久乳", MILK, "2026-08-28", "names-it", "shelf-stable milk — 乳 is the head noun"),
    ("奶粉", MILK, "2026-08-28", "names-it", "milk powder"),
    ("煉乳", MILK, "2026-08-28", "names-it", "condensed milk"),
    ("鮮奶油", MILK, "2026-08-28", "names-it", "dairy cream — 鮮奶 is the head, 油 the form"),
    ("奶油", MILK, "2026-08-28", "names-it",
     "butter. **The one row here whose reason is worth reading twice:** 奶油 in Taiwanese usage is "
     "dairy butter, and a margarine is 植物奶油 or 人造奶油 — a different word, not in this table"),
    # ---- fish ------------------------------------------------------------------------------
    ("鮪魚", FISH, "2026-08-28", "names-it", "tuna — 魚 is the head noun"),
    ("鮭魚", FISH, "2026-08-28", "names-it", "salmon — 魚 is the head noun, 鮭 names the species"),
    ("柴魚", FISH, "2026-08-28", "names-it", "dried bonito; the owner named this one in the ruling"),
    ("小魚乾", FISH, "2026-08-28", "names-it", "dried small fish"),
    # ---- soy -------------------------------------------------------------------------------
    ("大豆", SOY, "2026-08-28", "names-it", "the word is the allergen"),
    ("豆漿", SOY, "2026-08-28", "names-it", "soy milk — 豆 here is the soybean, and 漿 the form"),
    ("豆腐", SOY, "2026-08-28", "names-it", "tofu is made of soybean and the word says 豆"),
    # ---- crustacean ------------------------------------------------------------------------
    ("蝦", CRUSTACEAN, "2026-08-28", "names-it", "the owner's own example: 蝦就是甲殼類"),
    ("蝦仁", CRUSTACEAN, "2026-08-28", "names-it", "shelled shrimp — 蝦 is the head noun"),
    ("蟹", CRUSTACEAN, "2026-08-28", "names-it", "crab; the word is a crustacean and nothing else"),
    # ---- sesame ----------------------------------------------------------------------------
    ("芝麻", SESAME, "2026-08-28", "names-it", "the word is the allergen"),
    ("白芝麻", SESAME, "2026-08-28", "names-it", "white sesame — a colour and the allergen"),
    ("黑芝麻", SESAME, "2026-08-28", "names-it", "black sesame"),
    # ---- peanut ----------------------------------------------------------------------------
    ("花生", PEANUT, "2026-08-28", "names-it", "the word is the allergen"),
    # ---- tree nuts -------------------------------------------------------------------------
    ("核桃", NUTS, "2026-08-28", "names-it", "walnut — the word names the nut itself, not a flavour"),
    ("腰果", NUTS, "2026-08-28", "names-it", "cashew — the word names the nut itself"),
    ("開心果", NUTS, "2026-08-28", "names-it", "pistachio — the word names the nut itself"),
    # ---- gluten ----------------------------------------------------------------------------
    ("麵粉", GLUTEN, "2026-08-28", "names-it", "wheat flour — 麵粉 unqualified is wheat flour"),
    ("低筋麵粉", GLUTEN, "2026-08-28", "names-it", "cake flour; 麵粉 is the head noun"),
    ("高筋麵粉", GLUTEN, "2026-08-28", "names-it", "bread flour; 麵粉 is the head noun"),
    ("小麥", GLUTEN, "2026-08-28", "names-it", "wheat — the grain the group is named for"),
)

#: **Terms deliberately NOT here, with the reason — because the absence is the decision.**
#:
#: A reader who meets one of these in the source and wonders why it matched nothing should find the
#: answer here rather than assume an oversight. Every one contains an allergen word and names
#: something else.
REFUSED: tuple[tuple[str, str], ...] = (
    ("麵包", "names a bread. That bread is made of wheat is a fact about the recipe, not the word — "
             "the owner's own counter-example"),
    ("蛋糕", "names a cake. Beside 皮蛋 above: same character, opposite answer, which is why there "
             "is no substring rule"),
    ("蛋糕專用脂", "names a fat sold for cake-making. It is not an egg and may contain none"),
    ("蛋餅皮", "names a wrapper. 蛋餅 is a dish; whether this particular skin contains egg is a "
               "question about the product, and the word does not answer it"),
    ("燕麥奶", "oat milk — 奶 here is a form, not dairy, and 燕麥 is oat rather than a gluten grain"),
    ("蕎麥", "buckwheat: 麥 in the name, and it is not a gluten grain at all"),
    ("豆腐麵", "the 大豆 half is decided by 豆腐 above; 麵 names a noodle, and a noodle being wheat "
               "is a fact about the recipe"),
    ("咖啡豆", "coffee bean — 豆 is a shape word here and names no legume"),
    ("果糖", "fructose; matched only by a character-level search, never by a word"),
)
