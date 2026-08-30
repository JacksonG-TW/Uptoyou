"""D39's prompt, version-controlled — condition 1, and the artifact §6 asks for by name.

**The version string is data, not decoration.** Every generated row records it (D39's
condition 3), so a category can always be traced to the exact instruction that produced it,
and two prompt versions are compared by re-running rather than by argument. **Changing any
text below changes the version**, in the same commit, or the provenance starts lying.

The ladder in the instruction is D39's tie-break, ruled 2026-08-14: D38's list mixes axes on
purpose — 早餐 is a time, 日式 is a cuisine, 麵食 is a form — so a 日式早午餐 shop satisfies
two values and something has to decide. Self-description wins first because it is the signal
the shop itself chose to publish, and it is the one the model can actually see.
"""

from __future__ import annotations

from upto.classify.categories import CATEGORIES

# v4 (owner-ruled 2026-08-14, after round 1): three additions aimed at the measured sign-layer
# failures — branch/company-suffix noise is ignored before judging, drink-first shops get their
# own rung (春水堂-shaped misses), and hotel/banquet dining is named as 其他's example (the
# most-confused gold in the sign layer). Every in-prompt example was checked against the frozen
# set and none appears in it — an example drawn from the exam would teach the exam (D82).
PROMPT_VERSION = "v6-2026-08-30"

# The sentinel is deliberately not one of D38's ten. **Widened in v3 (owner-ruled
# 2026-08-14):** it is what the model says when the string is not a classifiable eatery —
# either a legal-entity name that shows no shop at all (measured 2026-08-14 to be 40.2% of
# the source's rows, D31), or an identifiable business that does not serve food — **supermarkets
# and retail, and since 2026-08-30 NOT convenience stores.** It maps to a stored NULL, which D58
# already rules is a stated absence. **其他 keeps its narrowed meaning**: an eatery whose food does
# not fit the nine — never a row nobody could read, never a shop nobody eats at.
#
# **What changed on 2026-08-30, and why the sentinel is the place to record it.** Rung 1 (the 7B)
# answered 法人 on every convenience-store chain in the test set — 統一超商, 全家, 萊爾富, OK mart,
# 18 rows — and it was RIGHT by this wording, which named 便利商店 as a not-food business. The 2B
# was simply worse at obeying it, which is why the layer looked better. The owner ruled the chains
# are neither a legal entity nor 其他 but their own kind of place, so `便利商店` is now D38's
# eleventh value and the sentinel's second case keeps only 超市 and 零售.
NO_SIGNAL = "法人"

INSTRUCTION = """你是分類器。輸入是食品業者登錄的登記名稱，可能是店名，也可能只是公司的法人名稱。只輸出一個答案，不要解釋、不要標點。

類別（只能是下列其中一個）：
{categories}、{no_signal}

判斷之前，先忽略名稱裡的分店資訊（「-○○店」「○○分店」、地名加編號）和公司字尾（「股份有限公司」「(股)公司」「有限公司」），用剩下的招牌判斷。忽略之後若看得出是哪個品牌，就用那個品牌判斷，即使原字串帶著公司字尾。

判斷順序，依序套用，第一個成立就停：
0. 忽略字尾之後仍然不是可分類的餐飲店，就答「{no_signal}」。兩種情況都算：只是法人或控股公司、看不出是哪一家店（例如「安心食品服務股份有限公司」、「旨王開發有限公司」）；或看得出是一家店、但不是賣吃的店——超市、零售店（例如「頂好超市」）。是賣吃的店就繼續往下。
1. 是便利商店，就是便利商店（例如「統一超商」「7-ELEVEN」「全家便利商店」「萊爾富」「OK mart」）。超市、量販店不算，那是第 0 條。
2. 店名自稱哪一種店，就是哪一類（例如帶「早餐店」就是早餐，即使賣的是日式的）。
3. 主要賣的是飲品——咖啡、茶、手搖飲——就是咖啡飲料（例如「50嵐」）。
4. 沒有自稱，看主食形式：麵食、飯食、火鍋、燒烤。
5. 形式看不出來，看菜系：日式、西式。
6. 看得出是賣吃的店、但不屬於上面任何一類，才是其他——飯店、宴會館、俱樂部附設的餐飲也算這類（例如「晶華酒店」「漢來大飯店」）。

店名：{name}
類別："""


def build(name: str) -> str:
    """The exact text sent to the model for one place."""
    return INSTRUCTION.format(
        categories="、".join(CATEGORIES), no_signal=NO_SIGNAL, name=name
    )


# --- D88: the same instruction, plus retrieved examples ----------------------------------
#
# The version string is data here for the reason the header gives: a row generated under
# retrieval must be traceable to the instruction *and* to the fact that it had cribs, and
# `round_<name>_v5-rag-2026-08-15.json` is a different file from the plain round's by
# construction. Changing any text below changes this version, in the same commit.
#
# **Based on v3, not on v4, and that is the ruling rather than an oversight.** v4 added three
# hand-written rules and measurably lost: qwen 51.0→50.0, gemma 51.5→49.5 on the frozen set.
# The comparison reads absolute accuracy, so retrieval is stacked on the best-measured
# base — otherwise a v5-rag that beat v4 would still be worse than doing nothing, and the
# experiment would have measured retrieval against a handicap it chose itself.
#
# **Every crib comes from the frozen set, and leave-one-out is what makes that legitimate.**
# D82's rule is that an example drawn from the exam teaches the exam; `examples.nearest`
# excludes the asked name (and, through 0018's UNIQUE, every copy of it), so no row ever sees
# its own gold. Without that exclusion this prompt would score the lookup, not the model.
RAG_PROMPT_VERSION = "v6-rag-2026-08-30"

RAG_INSTRUCTION = """你是分類器。輸入是食品業者登錄的登記名稱，可能是店名，也可能只是公司的法人名稱。只輸出一個答案，不要解釋、不要標點。

類別（只能是下列其中一個）：
{categories}、{no_signal}

參考例（人工判定過的類似店名）：
{examples}

判斷順序，依序套用，第一個成立就停：
0. 這個名稱不是可分類的餐飲店，就答「{no_signal}」。兩種情況都算：只是法人或控股公司、看不出是哪一家店（例如「安心食品服務股份有限公司」、「旨王開發有限公司」）；或看得出是一家店、但不是賣吃的店——超市、零售店（例如「頂好超市」）。是賣吃的店就繼續往下。
1. 是便利商店，就是便利商店（例如「統一超商」「7-ELEVEN」「全家便利商店」「萊爾富」「OK mart」）。超市、量販店不算，那是第 0 條。
2. 店名自稱哪一種店，就是哪一類（例如帶「早餐店」就是早餐，即使賣的是日式的）。
3. 沒有自稱，看主食形式：麵食、飯食、火鍋、燒烤。
4. 形式看不出來，看菜系：日式、西式。
5. 看得出是賣吃的店、但不屬於上面任何一類，才是其他。

店名：{name}
類別："""


def _example_line(example) -> str:
    """One crib: 「名稱：類別」, or 「名稱：類別（細分類）」 when the store holds a subtype.

    **The subtype is printed and the layer is not**, and the asymmetry is the ruling. A
    subtype (手搖飲 under 咖啡飲料) is a fact about the shop, which is what the model is being
    taught; the layer is how the *score* is read, and telling the model which layer an example
    came from would teach it the evaluation's own bookkeeping. No distance either — a printed
    distance invites the model to weigh the examples, and the ranking is already the order.

    A two-element example is the frozen set's shape today (0018: `subtype` is NULL there);
    the third slot is where a case book's finer tag arrives, so that arrival needs no change
    here.
    """
    label = example[1]
    subtype = example[2] if len(example) > 2 else None
    return f"{example[0]}：{label}（{subtype}）" if subtype else f"{example[0]}：{label}"


def build_rag(name: str, examples: list[tuple[str, str]]) -> str:
    """The exact text sent to the model for one place, with its retrieved neighbours.

    Nearest first, one line each, and nothing the model has to interpret. `_example_line`
    owns what a line says.
    """
    return RAG_INSTRUCTION.format(
        categories="、".join(CATEGORIES),
        no_signal=NO_SIGNAL,
        examples="\n".join(_example_line(example) for example in examples),
        name=name,
    )
