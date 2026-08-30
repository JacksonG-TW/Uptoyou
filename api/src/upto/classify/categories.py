"""D38's closed list, and the validation D39 makes the whole process rest on.

**Eleven values since 2026-08-30**, declared in D38 and copied here once. **A value outside this tuple is rejected,
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
    "其他",
)


def is_valid(value: str) -> bool:
    return value in CATEGORIES
