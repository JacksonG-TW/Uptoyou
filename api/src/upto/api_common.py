"""Shared by the write half (rounds) and the read half (live): the three helpers both need.

`resolve_member` is D67's gate. `place_names` is D28's 2026-08-13 ruling executed at read
time — a reference place carries only its 登錄字號, so its display name comes from the latest
publication's row, never from a copy that would drift. `_result_body` is the one shape a close
has, whether it answers a roll, a retry (D69), or arrives on the stream (D53) — one builder,
so the shapes cannot disagree.
"""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy import bindparam, text

from .engine.table import allocate, board
from .auth import credential_for, member_for
from .engine import contributors as known_contributors
from .engine import draw
from .engine.fold import Contribution, fold


async def resolve_credential(session, request: Request, circle_id: int):
    """`(member_id, operator)` for the bearer token, or 401. D67's one answer for both halves.

    The role comes from the presented secret (D105), so **an endpoint cannot be talked into an
    operator shape by anything in the request** — there is no parameter to send.
    """
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="a bearer token is required (D67)")
    found = await credential_for(session, header[7:].strip(), circle_id)
    if found is None:
        # One answer for both halves: which half failed is not the caller's to learn.
        raise HTTPException(
            status_code=401, detail="the token does not resolve to a member of this circle"
        )
    return found


async def resolve_member(session, request: Request, circle_id: int) -> int:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="a bearer token is required (D67)")
    member = await member_for(session, header[7:].strip(), circle_id)
    if member is None:
        # One answer for both halves: which half failed is not the caller's to learn.
        raise HTTPException(
            status_code=401, detail="the token does not resolve to a member of this circle"
        )
    return member


# The single-brand join, D77's read rule: a company mapped to **exactly one** brand shows the
# brand; a multi-brand company keeps its registered name, because nothing in either source
# says which of its brands this site is (measured 2026-08-14: the rule patches 334 松山區
# rows and forgoes 17). `having count(distinct brand_name) = 1` is the whole rule.
# **The rule itself, as one fragment, so the two forms below cannot drift apart.** `having
# count(distinct brand_name) = 1` IS D77's read rule; everything around it is plumbing. Two
# spellings of one rule is exactly the shape this repository keeps being bitten by, so the
# load-bearing line exists once and both statements interpolate it.
_SINGLE_BRAND_RULE = "having count(distinct br.brand_name) = 1"

# The per-row form: a correlated subquery for one company name, used where the caller already has a
# handful of rows in hand (the reveal, the classifier's batch, the evaluation sample).
SINGLE_BRAND = (
    "select min(br.brand_name) as brand_name from brand_registration br"
    "  where br.company_name = {company}"
    "  and br.publication_id = ("
    "    select id from brand_publication order by detected_at desc, id desc limit 1)"
    "  " + _SINGLE_BRAND_RULE
)

# **The grouped form — D93's amendment, owner-ruled 2026-08-27 (「採用」).** The same rule computed
# **once** over the whole 288-row table and joined on `company_name`, instead of a `LATERAL`
# re-evaluated per candidate row.
#
# **Why it was worth a ruling rather than a tidy-up.** M8 measured the lateral at **35,533
# executions per keystroke** against a 288-row table — an N+1 written in SQL — and **93% of the
# typeahead's 82,300 buffers**. `reference_place`, the table everyone assumed was the cost, was
# ~1%. The grouped join measured **61× fewer buffers and 5–8× faster, with the result set proved
# identical** (`except all` empty both ways over the whole publication). It changes a query in the
# request path, which is why it was put to the owner with the numbers rather than folded in.
#
# **`min()` is not arbitrary and must stay.** The `having` keeps only companies with exactly one
# distinct brand name, so within a surviving group every row's `brand_name` is that one value and
# `min()` is simply how a grouped query names it. A company with two brands produces **no row**
# here and the join leaves `brand_name` NULL, which is D77's rule: nothing in either source says
# which of its brands a given site is, so it keeps its registered name.
SINGLE_BRAND_GROUPED = (
    "select br.company_name, min(br.brand_name) as brand_name from brand_registration br"
    "  where br.publication_id = ("
    "    select id from brand_publication order by detected_at desc, id desc limit 1)"
    "  group by br.company_name "
    + _SINGLE_BRAND_RULE
)

# The storefront join, D78's read rule: site-level, keyed by the registry number itself, and
# it **outranks the brand join** — the brand says what the company calls its shops, this row
# says what this shop's sign says, which is the only thing that can split a multi-brand
# company's sites. No `having`: the source is one row per site (0014's key enforces it).
STOREFRONT = (
    "select sn.name from storefront_name sn"
    "  where sn.registry_no = {registry}"
    "  and sn.publication_id = ("
    "    select id from storefront_publication order by detected_at desc, id desc limit 1)"
)


LATEST_PLACE_PUBLICATION = (
    "select id from place_publication order by detected_at desc, id desc limit 1"
)


async def compose_names(session, rows) -> dict[str, dict]:
    """D92, executed once for every screen. `rows` is an iterable of mappings carrying
    `key` (whatever the caller indexes by), `own` (a circle-local row's own words, or None),
    `sign`, `brand`, `registered`, `company` (the registered company name — the collision
    key), `address`. Returns, per key: `name` (what a person reads), `name_source`
    (`circle-local` · `sign` · `brand` · `registered`), `district` (B6's second line, or None).

    The collision is judged against the whole latest publication, not against the rows on
    screen — so a name is the same in the search, the pool and the reveal (the frontend
    session's "stable per brand"), and a branch does not gain a bracket because a sibling
    happened to be searched for. The key is the registered company name among sign-less
    sites: a signed site never collides (its sign is its name), and the brand is a function
    of the company (D77's single-brand rule), so two sign-less sites of one company always
    share their base name.
    """
    from . import naming  # noqa: PLC0415  (pure module; imported here to keep the header lean)

    rows = list(rows)
    out: dict[str, dict] = {}
    pending: dict[str, list] = {}  # company -> rows that may need a bracket
    for row in rows:
        loc = naming.location(row.get("address"))
        # R-6 (owner-ruled 2026-08-18): a registry footnote at the head of the registered
        # name is read out before anything is composed; the stored row is untouched.
        row = dict(row, registered=naming.strip_registry_footnote(row.get("registered")))
        if row.get("own") is not None:
            out[row["key"]] = {"name": row["own"], "name_source": "circle-local", "district": None,
                               "base": row["own"], "qualifier": None}
        elif row.get("sign"):
            out[row["key"]] = {"name": row["sign"], "name_source": "sign", "district": loc.where_line,
                               "base": row["sign"], "qualifier": None}
        else:
            base = row.get("brand") or row.get("registered")
            # **No base, no rung.** `registered` used to be claimed unconditionally here, so a place
            # whose registry number is in NO publication the database still holds — one that left
            # the source before anything pruned it — came back with `name` null and
            # `name_source = "registered"`, asserting a rung it does not have. Reachable on a host
            # holding a single publication that has not deleted its departed rows; not reproducible
            # on either host today (dev keeps two publications and falls back to the older one; the
            # instance deleted the 532 that left). Found by the reviewer on 2026-09-12 by reading
            # the branch rather than by running it.
            source = ("brand" if row.get("brand") else "registered") if base else None
            # **A16 keeps `base` and `qualifier` beside `name`, rather than recovering them later.**
            # `name` is what every list shows and is unchanged; the headline shortens `base` alone
            # and carries `qualifier` in its own field. Both are held here because this is the one
            # place that has them apart — see `naming.derive_brackets` for why they must not be
            # split out of the composed string afterwards.
            out[row["key"]] = {"name": base, "name_source": source, "district": loc.where_line,
                               "base": base, "qualifier": None}
            if row.get("company") and base:
                pending.setdefault(row["company"], []).append(row)
    if not pending:
        return out
    # One query for every sign-less sibling of every company on screen, in the latest
    # publication — the set that decides whether the base name collides.
    siblings = (
        await session.execute(
            text(
                "select rp.name as company, rp.registry_no, rp.address "
                "from reference_place rp "
                "where rp.publication_id = (" + LATEST_PLACE_PUBLICATION + ") "
                "and rp.name in :companies "
                "and not exists (" + STOREFRONT.format(registry="rp.registry_no") + ")"
            ).bindparams(bindparam("companies", expanding=True)),
            {"companies": list(pending)},
        )
    ).all()
    by_company: dict[str, dict[str, str]] = {}
    for sib in siblings:
        by_company.setdefault(sib.company, {})[sib.registry_no] = sib.address
    for company, company_rows in pending.items():
        addresses = by_company.get(company, {})
        if len(addresses) < 2:
            continue
        base = company_rows[0].get("brand") or company_rows[0].get("registered")
        brackets = naming.derive_brackets(base, addresses)
        for row in company_rows:
            bracket = brackets.get(row.get("registry_no"))
            if bracket:
                out[row["key"]]["name"] = naming.compose(base, bracket)
                out[row["key"]]["qualifier"] = bracket
    return out


async def place_display(session, place_ids) -> dict[int, dict]:
    """Display names with their rung, most specific source first: a circle-local row's own words; the
    storefront sign for the site (D78); the brand when the company names exactly one (D77);
    the registered name from the latest publication — then D92's bracket when that base name
    is shared by other sign-less sites of the same company (`compose_names`)."""
    ids = list(place_ids)
    if not ids:
        return {}
    rows = (
        await session.execute(
            text(
                "select p.id, p.name as own, p.registry_no, "
                "storefront.name as sign, brand.brand_name as brand, "
                "ref.name as registered, ref.name as company, ref.address "
                "from place p "
                "left join lateral ("
                "  select rp.name, rp.address from reference_place rp"
                "  join place_publication pp on pp.id = rp.publication_id"
                "  where rp.registry_no = p.registry_no"
                "  order by pp.detected_at desc limit 1"
                ") ref on true "
                "left join lateral ("
                + STOREFRONT.format(registry="p.registry_no")
                + ") storefront on true "
                "left join lateral (" + SINGLE_BRAND.format(company="ref.name") + ") brand on true "
                "where p.id in :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
    ).all()
    composed = await compose_names(
        session,
        (
            {
                "key": row.id,
                "own": row.own,
                "registry_no": row.registry_no,
                "sign": row.sign,
                "brand": row.brand,
                "registered": row.registered,
                "company": row.company,
                "address": row.address,
            }
            for row in rows
        ),
    )
    return composed


async def place_names(session, place_ids) -> dict[int, str]:
    """Just the strings, for every caller that needs nothing but what a person reads."""
    return {key: value["name"] for key, value in (await place_display(session, place_ids)).items()}


# --- A16 / D92 as amended: the winner's headline --------------------------------------------
#
# **One line of the reveal is shortened and nothing else is.** `places` above keeps the composed
# name for every row including the winner, so the proposal list, the operator table and the panel
# are untouched; this is a separate field because the two strings are genuinely different answers to
# two different questions — *what is this place called* and *what does the headline say*.
#
# **Composed here rather than in the browser**, for D92's own reason: the same place must read the
# same on every screen, and the authored token list belongs in git behind `tools/server_copy.py`'s
# gate rather than in a bundle. `upto.headline` holds the list and the argument.
def winner_headline_for(display: dict, winning_place_id: int) -> tuple:
    """`(headline, qualifier)` for the winner — both, or `(None, None)`.

    **Returned together on purpose.** A qualifier on one wire and not the other is D105's silent
    half, and a headline computed without its qualifier is the defect the A16 gate found: the
    shortening was handed the *composed* name, whose trailing `）` no business-type token can match,
    so every chain — the names A16 exists for — passed through whole. One call, two values, no way
    to obtain one without the other.

    The shortening is given `base`, never `name`. `qualifier` is the bracket's **content**, without
    its parentheses; `null` when the name has none.
    """
    from . import headline as headline_module  # noqa: PLC0415  (pure module, lean header)

    entry = display.get(winning_place_id)
    if entry is None:
        return None, None
    return (headline_module.headline(entry.get("base"), entry.get("name_source")),
            entry.get("qualifier"))
def _result_body(
    round_id: int,
    dice: tuple[int, int] | None,
    winning_place_id: int,
    weights: dict[int, object],
    # **`str | None`, and the `None` is two lines from where it is created** (frontend's catch,
    # 2026-09-12). The caller passes `value["name"]` from `place_display`, and `compose_names`
    # returns `None` there for a place in no publication this database still holds — so the
    # annotation said `str` about a value the function beside it can null. Nothing downstream does
    # string work on it and the member payload carries it straight out, so this was never a runtime
    # fault; it was a description a future reader would have trusted. Same shape as the branch that
    # claimed a rung it did not have, one function over.
    names: dict[int, str | None],
    allocation: dict[int, int],
    cells: tuple[tuple[int, ...], ...],
    winner_headline: str | None = None,
    winner_qualifier: str | None = None,
) -> dict:
    return {
        "round_id": round_id,
        "status": "closed",
        "dice": list(dice) if dice is not None else None,
        "sum": dice[0] + dice[1] if dice is not None else None,
        "winning_place_id": winning_place_id,
        # Strings, not floats: the weights are exact decimals and stay that way (D46).
        "weights": {str(p): str(w) for p, w in weights.items()},
        # The table is the truth of the draw (D72): each place's share of the 36 outcomes.
        # **Operator only** — it is a figure, and the member's form of the same fact is `board`.
        "allocation": {str(p): n for p, n in allocation.items()},
        # Candidate 17, owner-ruled 2026-09-11: the member's 6×6 board, `board[die1-1][die2-1]`.
        # **The picture, not the figure.** It carries one place id per cell and nothing countable —
        # a member sees that one place holds more of the board by looking at it. Derived from the
        # same 36-slot table the draw landed on, so the cell for the rolled pair IS the winner
        # rather than agreeing with it.
        "board": [list(row) for row in cells],
        "places": {str(p): n for p, n in names.items()},
        # A16: the shortened form of the winner's name, for the reveal's one headline line. `None`
        # when the caller did not compute one — a shape the surface must handle by falling back to
        # `places[winning_place_id]`, never by rendering an empty headline.
        "winner_headline": winner_headline,
        # A16: the parenthetical D92 derived from the registered address, as its own value and
        # without its parentheses — `null` when the name has none. The surface joins them; the
        # headline field never carries a bracket.
        "winner_qualifier": winner_qualifier,
        # A19: per place, `declared` or `unknown` — never absent. See `ingredient_data_for`.
        # D105 as amended: this member's own `represented_member` sentences, nothing else.
    }

# --- B2 / item 9: the trip, read the same way everywhere it appears ------------------------
#
# **One helper for three readers, because three copies of this query is three chances to leak a
# column.** The reveal payload, the SSE snapshot and the signing endpoint's own response must all
# describe a trip identically, and what they must never carry is the signer's `member_id` — H3's
# response-shape rule, and §3.0's reason: at five people an id is a name.
#
# `nickname` and `signed_at` only. Not `member_id`, not `place_id` (the winner is read from
# `round.winning_place_id` — D28/D57, derived and never copied), and not a note, because D38 admits
# no free text.
#
# **Nobody is a hole.** An unsigned round returns `None` rather than an empty object, so a screen
# distinguishes "no trip yet" from "a trip with nothing in it" without inspecting fields.
TRIP = """
select m.nickname as nickname, t.signed_at as signed_at
  from trip t join member m on m.id = t.member_id
 where t.round_id = :round_id
"""


async def trip_for(session, round_id: int):
    """`{"nickname", "signed_at"}` for a signed round, or `None`."""
    row = (await session.execute(text(TRIP), {"round_id": round_id})).one_or_none()
    if row is None:
        return None
    return {"nickname": row.nickname, "signed_at": row.signed_at.isoformat()}


# --- D105: two reveal shapes, one builder, chosen by the credential -------------------------
#
# **The member shape is a strict subset of the operator's, produced by removing rather than by
# building.** Two builders drift: the day a field is added to one, the other silently lacks it or
# silently gains it. So the full payload is assembled once and the member's is what survives a
# whitelist — and a new field is therefore **operator-only until someone names it here**, which is
# the safe direction.
#
# **What a member sees: what happened.** The round, the two faces, their sum, which place won, its
# name, and the trip if one is signed. **What a member does not see: how the odds got there** — no
# per-place weights, no share of the 36 outcomes, no channels, no factors, no clamps. D105's line:
# *the operator view audits the arithmetic, not the people.*
#
# **`places` stays whole, and that is a deliberate narrowing of my first attempt.** I trimmed it to
# the winner on the strength of the ticket's *"nothing else"*, and it was over-reach: a member
# proposed from that pool and read those names on their own screen minutes earlier, so withholding
# them protects nothing, and it broke two existing tests that were right. **What "nothing else"
# is about is how the odds got there** — `weights`, `allocation`, `panel` — not what the places are
# called. Withholding a name would also stop a reveal saying "not 巷口麵店 this time", which is a
# thing the screen may honestly say.
async def seats_for(session, round_id: int, seat_ids: list | None, seed: bytes | None,
                    closed: bool) -> list:
    """D108's `rolls[]` — **every seat drawn at open, in member order, in one of two states.**

    *Ordering agreed with the frontend session 2026-08-19, and it is theirs rather than mine.* I
    proposed `rolled_at` order so arrivals could animate without re-sorting. They refused it and were
    right: **that makes the layout reorder itself during the animation**, and D91's zero-shift clause
    binds the whole roll sequence — a seat that jumps because somebody else was quicker is exactly the
    forbidden thing. The list must **fill**, never **grow**.

    **Two states, and the second is the owner's 「要」 (D108, `9765a0d`).**

    * **Open** — a seat shows dice only if that member has tapped. In practice no seat ever fills here,
      because the first tap closes the round; the frontend measured that and it is the deadlock fix
      working rather than a defect.
    * **Closed** — **every** seat's pair is filled, for everyone, regardless of who tapped. A static
      list of all the pairs with the decider marked, beside the commitment. That is what makes a tap
      after close record nothing (D69 stands): there is no seat left for it to fill.

    **The seats come from `round.seat_ids`, pinned at open — never from live membership.** Reading
    `member` here was the bug revision 0027 exists for: the decider is drawn from the seat set, so a
    live read made it move whenever the circle changed. A round predating 0027 has no pin and falls
    back to the current membership, which is wrong in the same way but is the only thing left.

    **Nicknames are looked up and may be absent.** A member erased after the round keeps their seat as
    an id — that is what a verifiable past requires — and their nickname does not come back. `None`
    rather than a placeholder, because inventing 「已離開」 here would put copy in the API that the
    surface should be choosing.
    """
    if seed is None or not seat_ids:
        return []
    names = dict(
        (
            await session.execute(
                text("select id, nickname from member where id = any(:ids)"),
                {"ids": list(seat_ids)},
            )
        ).all()
    )
    tapped = (
        set()
        if closed
        else set(
            (
                await session.execute(
                    text("select member_id from member_roll where round_id = :r"), {"r": round_id}
                )
            )
            .scalars()
            .all()
        )
    )
    decider = draw.deciding_member(seed, list(seat_ids))
    seats = []
    for member_id in sorted(seat_ids):
        show = closed or member_id in tapped
        pair = draw.pair_for_member(seed, member_id) if show else (None, None)
        seats.append({
            "member_id": member_id,
            "nickname": names.get(member_id),
            "die1": pair[0],
            "die2": pair[1],
            "counts": member_id == decider,
        })
    return seats


def deciding_member_for(seats: list) -> dict | None:
    """The decider as its own object, kept **beside** `rolls[]` and not collapsed into it.

    The frontend asked for both and their reason decides it: `deciding_member` exists from open,
    before `rolls[]` has a single tap; `counts` marks a roll that has happened. A screen with only
    `counts` could not name the decider before the first die lands, which is the one thing D91
    requires it to do.
    """
    for seat in seats:
        if seat["counts"]:
            return {"id": seat["member_id"], "nickname": seat["nickname"]}
    return None


MEMBER_KEYS = ("round_id", "status", "dice", "sum", "winning_place_id", "places", "trip",
               # A16: the headline is the member's line before it is anyone's — the operator table
               # reads `places`. Named here because this list is a whitelist and a new field is
               # operator-only until it is.
               "winner_headline", "winner_qualifier",
               # **`ingredient_data` and `my_reasons` left this whitelist on 2026-08-30**, with
               # the ingredient kind. They are the only two fields ever removed from it, and that
               # is worth a line: a whitelist shrinking is as much a payload change as one growing,
               # and frontend was warned before this landed rather than after.
               # D108: the seat list, the decider and the commitment are all member-visible — they
               # are what the fairness claim is made of, so withholding them from a member would
               # leave the claim unverifiable by the only people it is addressed to. The **seed** is
               # not in this list and is not member-visible until close; `revealed_seed` is only ever
               # populated on a closed round, which is where the reveal is safe.
               "rolls", "deciding_member", "seed_commit", "revealed_seed",
               # Candidate 17: the 6×6 board, one place id per cell (owner-ruled 2026-09-11).
               # `allocation` is NOT here and must not be — it is the same fact as a figure, and
               # the ruling gave the member the picture. A count reaching this list would make the
               # board decoration over a number rather than the thing itself.
               "board")


async def closed_body(
    session,
    round_id: int,
    dice: tuple[int, int] | None,
    winning_place_id: int,
    weights: dict[int, object],
    viewer: int | None = None,
    with_panel: bool = True,
) -> dict:
    """The closed round's payload, assembled in ONE place — D108's evidence included.

    **Every path that shows a closed round comes through here, and nothing else can be called**
    — `_result_body` is private as of 2026-09-11 for exactly that reason (the reviewer: this
    docstring claimed «there is nothing else to call» while a module-level `result_body` sat
    beside it with a single caller, so a fifth path could have assembled its own body the way
    the fourth did). A whitelist is structural; a convention is a promise, and the promise is
    what failed here the first time. That is the point rather than a tidiness: the roll response, D69's retry, the SSE close event and the reconnect
    snapshot. The snapshot did not, until 2026-09-11, and so a member who reloaded after the
    reveal got dice, sum, winner and trip with **none of D108's four keys** — no seat list, no
    deciding member, no commitment, no revealed seed — which is the apparatus that makes the
    draw checkable, missing from the one path a member is most likely to take (the reviewer's
    finding). The old comment here already promised «every caller gets them without having to
    remember to»; a fourth caller assembled its own body and the promise was not enforceable
    from inside this function. It is now, because there is nothing else to call.

    `viewer` is the looking member, for D13's own-reason rule.

    **`viewer` is a member id and never reaches the payload** (H3). It is used for one comparison:
    a `represented_member` reason is shown to that member and to nobody else — including to an
    operator, who audits the arithmetic rather than the people.
    """
    # A16: one composition, two readings — `places` keeps every row's composed name, and the
    # headline is the winner's shortened form (registered rung only). Composed here, at the same
    # single assembly point as `trip` and `panel`, so the roll response, D69's retry and the SSE
    # close cannot disagree about what the headline says.
    display = await place_display(session, weights.keys())
    winner_headline, winner_qualifier = winner_headline_for(display, winning_place_id)
    body = _result_body(
        round_id,
        dice,
        winning_place_id,
        weights,
        {key: value["name"] for key, value in display.items()},
        allocate({p: w for p, w in weights.items()}),
        board({p: w for p, w in weights.items()}),
        winner_headline=winner_headline,
        winner_qualifier=winner_qualifier,
    )
    # B2: `None` until somebody signs, and the same shape wherever a trip appears — nickname and
    # time, never the signer's id (H3). Read here rather than assembled, so the reveal, the SSE
    # snapshot and the signing response cannot drift apart.
    body["trip"] = await trip_for(session, round_id)
    # **D108's reveal.** Read here rather than passed in, so every caller of this function — the roll
    # response, D69's retry, the SSE close — gets the seats, the decider, the commitment and the
    # revealed seed without any of them having to remember to. One assembly point is the same reason
    # `trip` and `panel` are read here.
    seed_row = (
        await session.execute(
            text("select circle_id, seed_commit, outcome_seed, status, seat_ids "
                 "from round where id = :r"),
            {"r": round_id},
        )
    ).one()
    seed = bytes(seed_row.outcome_seed) if seed_row.outcome_seed is not None else None
    seats = await seats_for(session, round_id, seed_row.seat_ids, seed,
                            closed=seed_row.status == "closed")
    body["rolls"] = seats
    body["deciding_member"] = deciding_member_for(seats)
    body["seed_commit"] = seed_row.seed_commit
    # **The seed is revealed only on a closed round, and this is the line that decides it.** Before
    # close, a member holding it can compute the winner and choose whether to tap — the preference
    # D91 forbids, and the same last-revealer attack that ruled out per-member commit–reveal. After
    # close there is nothing left to prefer, and the reveal is what turns *this was fixed before
    # anyone saw anything* from a promise into something anyone can check against `seed_commit`.
    body["revealed_seed"] = (
        seed.hex() if seed is not None and seed_row.status == "closed" else None
    )
    # The evidence table lives in `api_common.panel_for`, because the SSE snapshot needs the same
    # thing for a reconnecting operator and two copies of a visibility rule is one copy too many.
    # **`with_panel` exists for the snapshot, and it is a cost rather than a rule.** `for_credential`
    # strips `panel` for a member either way, so building it for one is a query and a fold thrown
    # away. The round endpoints keep it on: there one body serves the operator's response AND the
    # member broadcast, so it has to hold the evidence table before it is stripped. A snapshot is
    # built per connection for one credential, so it can decline the work it would discard.
    if with_panel:
        body["panel"] = await panel_for(session, round_id, weights, viewer)
    return body


def for_credential(body: dict, operator: bool) -> dict:
    """The operator's payload unchanged, or the member's subset of it."""
    if operator:
        return body
    return {key: body[key] for key in MEMBER_KEYS if key in body}


async def panel_for(session, round_id: int, weights, viewer: int | None = None) -> dict:
    """The reveal panel's evidence for one round: every stored factor, re-folded.

    **Extracted from `rounds._closed_body` on 2026-08-19 (D105)** because a reconnecting operator
    needs the same table from the SSE snapshot, and D13's visibility rule must not exist twice —
    two copies is how one of them stops matching the CHECK that backs it.

    `viewer` is a member id, is never emitted, and decides exactly one field: a
    `represented_member` reason is shown to that member and to nobody else, **including to an
    operator**, who audits the arithmetic rather than the people.
    """
    # The reveal panel's evidence: the stored records, re-folded so the clamp lines D45
    # requires are derived from the same rows the audit reads — never a second bookkeeping.
    # A reason travels only at 'table' visibility (D13): this payload is circle-wide, so a
    # represented member's sentence and a 'none' sentence alike stay behind; the factor and
    # its contributor still show, because the *odds* were never the secret.
    rows = (
        await session.execute(
            text(
                "select id, place_id, channel, contributor, effect, reason, "
                "reason_visibility, member_id from weight_contribution "
                "where round_id = :r"
            ),
            {"r": round_id},
        )
    ).all()
    panel: dict[str, dict] = {}
    for place_id in weights:
        contributions = [
            Contribution(
                id=row.id,
                place_id=place_id,
                channel=row.channel,
                contributor=row.contributor,
                effect=row.effect,
                reason=row.reason,
            )
            for row in rows
            if row.place_id == place_id
        ]
        folded = fold(place_id, contributions)
        visibility = {row.id: row.reason_visibility for row in rows}
        # **Whose reason it is, kept out of the payload and used only to decide one field.** D13's
        # third column has three values: `table` is circle-wide, `none` is nobody's, and
        # `represented_member` is exactly one person's — so the same round renders a different
        # sentence to different readers, and an operator is not exempted from that. §3.0: at five
        # people, "member 3 avoids 火鍋" makes the operator the one person who can see everyone's
        # preferences, and D14 erased the proposal authorship of this very round.
        represented = {row.id: row.member_id for row in rows}
        panel[str(place_id)] = {
            # What the fold starts at, before any contributor — 甲's 起點 row. It is NOT a factor
            # and is deliberately not padded into the list below: `factors` mirrors
            # `weight_contribution` rows, and the one payload an operator audits against the
            # database must not carry a row no record backs.
            "base": known_contributors.BASE,
            # D46's total order, straight from the fold — the panel must never re-sort.
            "factors": known_contributors.pad(
                [
                {
                    "channel": c.channel,
                    "contributor": c.contributor,
                    # normalize(): numeric(4,3) reads back as 0.800, and the panel says ×0.8.
                    # Display only — the fold and D15's reconciliation compare values.
                    "effect": str(c.effect.normalize()),
                    # **Both represented-member values, and this line is why the narrowing needed
                    # reading before it was written.** D13's 2026-08-30 amendment moved the category
                    # discount to `represented_member_panel` so it leaves the *reveal*; it did not
                    # take it off the panel, and a predicate matching one exact string would have
                    # removed it from here silently — the operator table would simply have shown one
                    # fewer sentence, with nothing failing.
                    "reason": c.reason if (
                        visibility[c.id] == "table"
                        or (visibility[c.id] in ("represented_member",
                                                 "represented_member_panel")
                            and viewer is not None and represented[c.id] == viewer)
                    ) else None,
                    # A real row, so the picture draws a bar. See `engine.contributors.pad`.
                    "fired": True,
                }
                for c in folded.contributions
                ]
            ),
            # D45: a clamped channel is its own line, or the arithmetic visibly fails.
            "clamps": [
                {
                    "channel": cl.channel,
                    "raw": str(cl.raw.normalize()),
                    "clamped": str(cl.clamped.normalize()),
                }
                for cl in folded.clamps
            ],
        }
    return panel
