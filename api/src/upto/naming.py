"""D92 — a chain's branches are named in three layers, and the format says which layer answered.

Pure functions, no database: the SQL hands over a base name, its source and the registered
address; this module decides what a person reads. **One:** a storefront sign is shown as it
is — it is the branch's own registered sign and needs no derivation. **Two:** no sign and the
base name (brand or registered) is shared by other sign-less sites of the same company, so the
name is derived from the registered address as `品牌（行政區＋路名＋段）` — the bracket is the
provenance: it says "we derived this from an address the registry records", where a hyphen
would assert an official store name nobody published. **Three:** still colliding, so the house
number joins the parenthetical. Nothing here invents: every character in the bracket is copied
from the stored address (D84's lesson — a plausible branch name is exactly what this surface
must not produce). Owner-ruled 2026-08-18: composed here, in the API, never in the browser —
the same place appears in the search, the pool and the reveal, and only the API holds the set
that says whether a name collides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

# Addresses arrive already normalised by `fda.normalise` (full-width folded, 台→臺, so 段
# numerals are Arabic and the city reads 臺北市). The parse is deliberately shallow: city,
# district, road (up to the road-class suffix), section, lane, alley, house number. Anything
# it cannot read is simply absent — a partial bracket is honest, an invented one is not.
_ADDRESS = re.compile(
    r"^(?:\d{3,6})?\s*"
    r"(?:臺北市)?"
    r"(?P<district>[一-鿿]{1,3}區)?"
    r"(?P<road>[一-鿿\dA-Za-z]+?(?:大道|路|街|道))?"
    r"(?P<section>\d+段)?"
    r"(?P<lane>\d+巷)?"
    r"(?P<alley>\d+弄)?"
    r"(?P<number>\d+(?:之\d+)?號)?"
)


@dataclass(frozen=True)
class Location:
    district: Optional[str]  # 中山區
    road: Optional[str]  # 南京東路
    section: Optional[str]  # 2段
    number: Optional[str]  # 86號 / 88之2號

    @property
    def where_line(self) -> Optional[str]:
        """B6's second line: 區＋路＋段, the place a person recognises. None when nothing parsed."""
        parts = [self.district, self.road, self.section]
        joined = "".join(p for p in parts if p)
        return joined or None

    def bracket(self, with_number: bool) -> Optional[str]:
        """D92's parenthetical: 區 loses its suffix (內湖 not 內湖區), the road keeps its class
        (信義路, so 民生東 does not stand for 民生東路), Arabic 段, then optionally the number."""
        district = self.district[:-1] if self.district and self.district.endswith("區") else self.district
        parts = [district, self.road, self.section]
        if with_number:
            parts.append(self.number)
        joined = "".join(p for p in parts if p)
        return joined or None


# R-6, owner-ruled 2026-08-18: a registry footnote typed into the name field — 「(無市招)」 (no
# sign), 「(重複登錄)」 (registered twice), 「(餐飲業)」 (the trade, no name) — is metadata in the
# wrong column, not part of the name, and is stripped at read time only. Stored strings, join
# keys and lineage never change. The list is closed on purpose: only these leading markers go,
# never "any parenthesis" — D92's derived bracket is full-width and at the end. Measured
# 2026-08-18: 3 rows of 36,499 carry one. If stripping leaves nothing, the string stays as it is
# — nothing is invented.
REGISTRY_FOOTNOTES = ("(無市招)", "(重複登錄)", "(餐飲業)")


def strip_registry_footnote(name: Optional[str]) -> Optional[str]:
    if not name:
        return name
    for marker in REGISTRY_FOOTNOTES:
        if name.startswith(marker):
            rest = name[len(marker):].strip()
            return rest or name
    return name


# H33's first trap, mitigated here 2026-08-18 — and it lives at *read* time, not at the ingest
# boundary, for one reason: the registered name must stay stored exactly as the registry
# published it. D92's three layers and R-6's strip both read the full registered string, and
# 「新加坡商海底撈國際食品有限公司台灣分公司」 is what 商業登記 actually filed. Folding the branch
# label into the stored value would destroy a fact the display layer needs, so this is a
# comparator: it answers "are these two strings the same business", and it never writes.
#
# **The branch strip is deliberately not a regex on the tail.** A pattern like `.{0,8}?分公司$`
# matches leftmost-first and eats into the company name — the 海底撈 string above loses
# 「限公司台灣分公司」 and stops matching its own FDA row. Measured, not theorised: that version
# reported 39 pairs as name disagreements which are the same company (M5, 2026-08-17). The rule
# that works is the one the naming convention actually uses — **a branch label is whatever
# follows the last legal-form token** — so the cut is made there.
#
# **No caller in `src` yet, and that is stated rather than hidden.** The only comparison that
# wants this today is `probes/m5_cross_source.py`, which carries its own copy for the same
# reason `foodtracer` imports `normalise` rather than copying it. Its first real caller arrives
# when M5's cross-source disagreement check moves out of the probe and into the API. It lands
# now because H33 is a measured hazard and a mitigation that exists is findable; one that waits
# for its caller is re-derived from scratch.
_COMPARE_PUNCT = re.compile(r"[\s()（）\[\]【】．。、,，\-‐‑‒–—―ー_·・「」『』/\\&＆'\"“”]+")
_LEGAL_TAIL = re.compile(
    r"(股份有限公司|有限股份公司|兩合公司|無限公司|有限公司|股份公司|公司|"
    r"股份有限|商業有限)$"
)
_LEGAL_ANY = re.compile(r"股份有限公司|有限股份公司|兩合公司|無限公司|有限公司|股份公司|公司")
_STOCK_TOKEN = re.compile(r"\(股\)|（股）|\(有\)|（有）")
_BRANCH = "分公司"


def squeeze(text: Optional[str]) -> str:
    """Normalised (H24's fold, H33's PUA strip) and then stripped of all spacing and punctuation.

    The rung below `core`: it answers "are these the same string once nobody's spacing habits
    are in the way", which is a different question from "are these the same business".
    """
    from .ingest.fda import normalise

    return _COMPARE_PUNCT.sub("", normalise(text or ""))


def core(text: Optional[str]) -> str:
    """`squeeze`, minus any 分公司 branch label, minus the legal form. Never stored.

    Returns `squeeze(text)` unchanged when stripping would leave nothing — a company whose whole
    name is its legal form is not usefully compared to the empty string, and every other such
    company would match it.
    """
    from .ingest.fda import normalise

    value = _COMPARE_PUNCT.sub("", _STOCK_TOKEN.sub("", normalise(text or "")))
    if value.endswith(_BRANCH):
        stem = value[: -len(_BRANCH)]
        # The last legal-form token is where the company name ends and the branch label begins.
        ends = [match.end() for match in _LEGAL_ANY.finditer(stem)]
        if ends:
            stem = stem[: max(ends)]
        value = stem
    value = _LEGAL_TAIL.sub("", value)
    return value or squeeze(text)


def location(address: Optional[str]) -> Location:
    match = _ADDRESS.match(address or "")
    if match is None:
        return Location(None, None, None, None)
    return Location(
        match.group("district"),
        match.group("road"),
        match.group("section"),
        match.group("number"),
    )


def compose(base: str, bracket: Optional[str]) -> str:
    """D92's displayed string: the base, and the parenthetical when there is one.

    **The only place the bracket's punctuation is written.** A16 needs the base and the bracket
    apart as well as together, and two places that know how to join them are two places that can
    come to disagree about the character between them — which is exactly the provenance mark this
    entry rests on, so it is written once.
    """
    return "{}（{}）".format(base, bracket) if bracket else base


def derive_brackets(base: str, addresses: Mapping[str, str]) -> dict[str, Optional[str]]:
    """The parenthetical for each sign-less site that shares one base name — `None` for none.

    `addresses` maps a site key (the registry number) to its stored address. Every site gets
    the layer-two bracket; the sites whose layer-two bracket is still shared move to layer
    three (house number). A site whose address yields nothing gets `None` — a bracket with
    nothing in it would be a lie about provenance.

    **This is the function to call when you need the two parts apart** (A16's headline shortens
    the base and carries the bracket separately). **Never recover the split by searching the
    composed string for `（`**: every character inside that bracket is copied from a stored
    address, and a parser over our own output is how a name eventually gains one that was not.
    """
    if len(addresses) < 2:
        return {key: None for key in addresses}
    located = {key: location(addr) for key, addr in addresses.items()}
    layer_two = {key: loc.bracket(with_number=False) for key, loc in located.items()}
    counts: dict[Optional[str], int] = {}
    for bracket in layer_two.values():
        counts[bracket] = counts.get(bracket, 0) + 1
    out: dict[str, Optional[str]] = {}
    for key, loc in located.items():
        bracket = layer_two[key]
        if bracket is not None and counts[bracket] > 1:
            bracket = loc.bracket(with_number=True)
        out[key] = bracket
    return out


def derive_names(base: str, addresses: Mapping[str, str]) -> dict[str, str]:
    """`derive_brackets`, composed. The shape every caller but A16's headline wants."""
    return {key: compose(base, bracket)
            for key, bracket in derive_brackets(base, addresses).items()}


def where_lines(addresses: Iterable[tuple[str, Optional[str]]]) -> dict[str, Optional[str]]:
    return {key: location(addr).where_line for key, addr in addresses}
