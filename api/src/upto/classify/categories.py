"""D38's closed list, and the validation D39 makes the whole process rest on.

**Thirteen values since 2026-08-30 (v7)**, declared in D38 and copied here once. **A value outside this tuple is rejected,
never coerced** — D39's condition 2, and the reason the generation step has a test that can
fail at all. Coercing a near-miss ("拉麵" → 麵食) would quietly turn a wrong answer into a
plausible one, which is the H23 shape this whole schema keeps meeting.
"""

from __future__ import annotations

# D38, ruled 2026-08-14; **`便利商店` added 2026-08-30 (owner: 「我認為可以開一類就是便利商店」),
# which is the amendment that took D38 from ten values to eleven and reversed D88's "the ten do
# not move" line.** It came out of rung 1: the 7B answered `法人` on every convenience-store chain
# in the test set, correctly by the prompt's own rule 0 — and the owner ruled the chains are
# neither a legal entity nor 其他, but their own kind of place.
#
# **This list is the CLASSIFIER's, and it is no longer the same list as `preferences.CATEGORIES`.**
# A member may avoid nine kinds and 其他; a place may additionally BE a convenience store. The two
# were identical for two weeks and are now deliberately not, so `test_preference_contributor`
# asserts the direction — preferences ⊆ this tuple, never equality.
#
# The order is the order a scaffold would render them: forms first, then kinds, then the two that
# are about the clock and the cup, then the store, then the fallback.
CATEGORIES: tuple[str, ...] = (
    "麵食",
    "飯食",
    "小吃",
    "火鍋",
    "燒烤",
    "日式",
    "西式",
    "早餐",
    "咖啡飲料",
    "便利商店",
    # **台菜 and 素食, owner-ruled 2026-08-30 「加兩類」 — the twelfth and thirteenth.** They come
    # from a count, not a hunch: `其他` held 15,146 of 27,982 decided rows, and the two largest
    # things inside it that a member could actually act on were drinks (already a value, and the
    # rule was missing from the RAG prompt — fixed in v7) and these.
    #
    # **台菜 is the EXPLICIT words only — 熱炒 · 快炒 · 合菜 · 家常菜 · 台式餐廳/餐館 — and
    # `小館` is NOT one of them** (owner-ruled: a suffix, not a cuisine). Measured before ruling:
    # 211 names carry 小館 against 47 熱炒/快炒 and 24 explicit 台/合菜, and the 小館 rows the
    # model did place went to 小吃, 西式, 火鍋, 日式 and 麵食 — 綵肴客家小館 is Hakka. A value that
    # swallows a shop-type suffix is `中式` under another name, which is the value this one
    # replaced *because* it would have been a residual.
    "台菜",
    # **素食 sits FIRST in the prompt's ladder, above 便利商店 and above 自稱, and that placement
    # is the whole argument for it.** It answers 我不能吃 rather than 我今天不想: 素食麵店
    # self-declares as a 麵店 and any lower rule would take it. **It is also the one value this
    # project cannot score** — ~1% of the city, so the frozen 200-row set holds exactly one row
    # (拾方素食館) and the report prints «insufficient rows» rather than a percentage (M2's shape).
    # Added on the member's constraint, not on a measurement, and that is stated rather than
    # dressed up.
    "素食",
    "其他",
)


def is_valid(value: str) -> bool:
    return value in CATEGORIES
