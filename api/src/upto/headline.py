"""A16 / D92 as amended 2026-08-27 — the reveal's winner headline, and nothing else.

**What this is for.** r771's winner rendered 一階堂拉麵餐飲有限公司 and the owner's note was
「名稱的部分可以縮減成一階堂拉麵」. D92's ladder is right — the registered name is what the registry
published and every list keeps it — but the one line a person reads at the moment the dice stop is a
headline, and a headline carrying a legal form is asking them to do the shortening themselves.

**Three boundaries, each of them load-bearing.**

1. **Display only, computed at read (D28).** Nothing here is stored, nothing is a join key, and no
   caller may write the result anywhere. The registered name in the database is untouched.
2. **The winner headline only.** The proposal list, the operator table, the pairs list and the
   search keep the composed name — a list is where a member tells rows apart, and 欣葉 on nineteen
   rows tells them apart from nothing.
3. **The registered rung only.** A sign name (D78) is the branch's own published sign and a brand
   name (D77) is what the company calls its shops; neither is ours to shorten. Only the rung where
   the *registry's* filing is being read gets touched.

**`naming.core` is not this and must not be used here.** `core` is a comparison key: it deletes
spaces and punctuation (`STARBUCKS COFFEE` → `STARBUCKSCOFFEE`), so it can never be shown to a
person. It also strips only the legal form, which measured one token short of the owner's example —
一階堂拉麵餐飲, not 一階堂拉麵. Two functions, two jobs; the entry says why.

**The list below is ours, and that is the cost.** No publisher says 國際 is a business-type token;
we do. It is the second thing in this product no source stands behind, after D113's aliases, and it
follows the same discipline: small, closed, dated, one reason and one measured count per row, in git
where an error can be found and answered for. A name that genuinely ends in 國際 loses it, and the
fix is one dated row — read D92's 2026-08-27 ruling before adding or removing one.
"""

from __future__ import annotations

from typing import Optional

# **Every row: the token, the date it was authored, how many strips it accounts for on the
# registered rung of the latest publication (measured 2026-08-27 — 31,119 rows render from that
# rung; the strip changes 11,939 of them), and why it is a business type rather than a name.**
#
# The counts are evidence that a token is *common*, never that it is *correct* — 投資 at 33 rows
# earns its place on the same argument as 有限公司 at 5,288, and a row would stay here at a count of
# zero if the argument held. They are recorded so the next person can see what each row actually
# does before deciding whether it still should.
BUSINESS_TYPE_TOKENS: tuple[tuple[str, str, int, str], ...] = (
    ("股份有限公司", "2026-08-27", 4610, "a legal form — 公司法's company types, not a name"),
    ("有限公司", "2026-08-27", 5288, "a legal form — the same, one type down"),
    ("管理顧問", "2026-08-27", 65, "the trade the company registered, not what the shop is called"),
    ("餐飲", "2026-08-27", 1878, "the industry itself — the owner's own example ends in it"),
    ("商行", "2026-08-27", 1930, "a sole-proprietor business type, the 商業登記 counterpart of 公司"),
    ("國際", "2026-08-27", 1434, "a scope claim appended to a company name, never the shop's name"),
    ("事業", "2026-08-27", 346, "an enterprise-type token, the same shape as 企業"),
    ("企業", "2026-08-27", 478, "an enterprise-type token"),
    ("食品", "2026-08-27", 557, "the trade — a food company's registration, not its sign"),
    ("實業", "2026-08-27", 283, "an enterprise-type token, older registrations"),
    ("開發", "2026-08-27", 85, "the trade, usually property or franchise development"),
    ("貿易", "2026-08-27", 73, "the trade — an importer that also runs a shop"),
    ("科技", "2026-08-27", 53, "the trade, on companies that also run a shop"),
    ("投資", "2026-08-27", 33, "the trade, on holding companies that own a restaurant"),
    ("行銷", "2026-08-27", 28, "the trade — a marketing company holding the registration"),
)

#: Longest first, so 股份有限公司 is never matched as 有限公司 with 股份 left behind.
_ORDERED = tuple(sorted((row[0] for row in BUSINESS_TYPE_TOKENS), key=len, reverse=True))

# **The stub floor — D92 leaves "nothing or a stub" undefined and this constant is where it is
# defined.** Measured 2026-08-27 over the registered rung: **no row strips to zero characters**, so
# the "leave nothing" case does not exist in today's data and the floor has to be argued at one.
# Two cannot be the line — 欣葉國際餐飲股份有限公司 → 欣葉 is one of D92's own worked examples, and
# 5,159 rows land at that length. Exactly **seven rows strip to one character**, every one a single
# site: 渡 · 悠 · 蓉 · 崧 · 放 · 崤 · 宮.
#
# A one-character headline is indistinguishable from a bug to the person reading it, and the
# headline's whole job is that someone recognises where they are going. Showing the original is
# never *wrong*, only unshortened. Seven rows of 31,119 is what the conservative side costs.
MIN_HEADLINE_LENGTH = 2

#: The rung `compose_names` reports for a name read from the registry's own filing.
REGISTERED = "registered"


def shorten(name: Optional[str]) -> Optional[str]:
    """Strip trailing business-type tokens, repeatedly, until none remains.

    **All-or-nothing, and that is the ruled shape.** D92 says *if the strip would leave nothing or a
    stub, show the original* — the original, not the last safe step. So a name is stripped the whole
    way and the result is either accepted or discarded; 悠國際有限公司 shows whole rather than
    becoming 悠國際, because the rule guards the outcome and not each step.

    Internal spacing and punctuation are preserved (`STARBUCKS COFFEE` keeps its space); only
    whitespace exposed at the end by a strip is removed.
    """
    if not name:
        return name
    value = name
    while value:
        for token in _ORDERED:
            if value.endswith(token):
                value = value[: -len(token)].rstrip()
                break
        else:
            break
    if len(value) < MIN_HEADLINE_LENGTH:
        return name
    return value


def headline(base: Optional[str], name_source: Optional[str]) -> Optional[str]:
    """The winner headline: `shorten` on the registered rung, the name itself everywhere else.

    A circle-local row is a member's own words, a sign is the branch's published sign and a brand is
    the company's own — none of the three is ours to edit.

    **`base`, never the composed name, and this is the defect the A16 gate found (2026-08-28).**
    D92 composes a sign-less site of a multi-site company as `base（行政區＋路名）`, so the string
    ends in `）` and **no business-type token can match its tail** — every chain passed through
    whole, which is to say the rule failed on exactly the names it was written for. The caller holds
    the two halves apart (`api_common.compose_names` sets `base` and `qualifier` beside `name`);
    the bracket travels in its own field and is never re-attached here.

    **Do not "fix" a composed string by splitting on `（`.** Every character inside that bracket is
    copied from a stored address — that is D92's provenance mark — and a parser over our own output
    is how one eventually contains something that was never in an address.
    """
    if name_source != REGISTERED:
        return base
    return shorten(base)
