"""A1 / item 4 — the private preference surface: write silently, read what is in force.

*Written 2026-08-18, owner-ruled (A1). Table: revision 0022. Contributor: `upto.engine.preference`.*

**Two endpoints, and the asymmetry between them is the design.** The write says nothing back and
appears nowhere; the read is a deliberate act by the member on their own device, and D25 requires
it — *「Re-confirmation shows the value, it does not ask the question again… the screen arrives with
it filled in.」* Asking afresh every round would be the exact pressure the product exists to remove.

**The write is silent, and "silent" is stronger than "anonymous" (§3.0).** `204`, empty body, and —
the part that matters most — **nothing is published to the circle's stream.** Not a count, not an
anonymous "someone updated a preference", nothing. At five people the *timing* of an event is one
guess from a name, and once guessed the person must either own it or publicly correct it, which is
the exposure their silence was buying. D55 already refuses authorship in the snapshot for the same
reason; this refuses the event itself. **The response also does not echo the value**, so a device
left on a table after the fact tells a passer-by nothing.

**Nothing is edited (D25).** Every write appends a row. Changing a budget appends a new band;
un-avoiding a category appends `stance='allow'`. "The value in force" is therefore a *query* — the
latest row per key — and resolving it **server-side** is not a convenience: a client applying
latest-wins would put the convention in the browser, which is what D5 and D13 exist to refuse.

**`persist` defaults to `false`.** D17: persistence is opt-in per preference and *the default is not
to keep*. A `persist=false` row is still written and still used for the round in force, then erased
by the scheduled job — so "do not remember this" is a fact with provenance rather than an absence,
and the screen's choice is not a no-op.

**No aggregate, and no other member, ever (H3, §3.0).** Both endpoints read `member_id` from the
device secret and touch nothing else. There is no circle-wide summary here and there is no column
to build one from — `preference` has no circle column at all.

**Error copy follows the rounds router's convention.** A person can reach nothing here but their own
screen, and both 400s are produced only by a client sending outside the closed list — a client bug,
never a person — so they stay English and name the list. The 401 is D67's one answer for both halves.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text

from .api_common import resolve_member
from .db import session_factory

# D38's ten and §4C-2's two bands, mirrored from revision 0022's CHECKs. **Two copies on purpose,
# and the duplication is the cheaper half:** the database refuses a bad value whatever the API
# believes (D39's condition 2), and this list exists only so the refusal is a 400 naming the list
# rather than a 500 carrying a constraint name. The integration test asserts they agree.
# **Eleven since 2026-08-30 — `便利商店` is D38's new value (revision 0039 widens the CHECK).**
# `其他` stays last: the order is the row a screen renders, and the fallback belongs at the end.
# This list is the SCREEN's, and `test_preference_contributor` asserts it is a subset of the
# classifier's — never equality, because the classifier's may legitimately run ahead again.
CATEGORIES = ("麵食", "飯食", "小吃", "火鍋", "燒烤", "日式", "西式", "早餐", "咖啡飲料",
              "便利商店", "其他")
# 衛福部's eleven food-label allergen groups, mirrored from revision 0023's CHECK for the same
# reason as the ten above. **D103: the list is these groups because that is what Taiwanese packaging
# already prints — and no copy on any surface may contain the word 過敏.** The API records 「不吃 X」;
# *why* is health information about an identified person and this product does not hold it.
INGREDIENTS = (
    "甲殼類", "芒果", "花生", "牛奶／羊奶", "蛋", "堅果類",
    "芝麻", "含麩質之穀物", "大豆", "魚類", "亞硫酸鹽類",
)
BUDGET_BANDS = ("tight", "easy")
STANCES = ("avoid", "allow")

KIND_BUDGET = "budget"
KIND_AVOID = "avoid_category"
KIND_INGREDIENT = "avoid_ingredient"

# The two kinds that carry a stance, and the one place that fact is written on this side. Both are
# reversible by appending `allow`; neither expires.
AVOIDANCES = (KIND_AVOID, KIND_INGREDIENT)

# **Known, stored, and refused on the wire since 2026-08-30.** They are still legal values of
# `ck_preference_kind` and 9 + 81 rows hold them; what changed is that nothing can create another.
# Named as a set rather than tested as "not the one good kind", so the 422's message can be true.
RETIRED_KINDS = (KIND_BUDGET, KIND_INGREDIENT)

# Which closed list each avoidance draws from. A dict rather than two branches, so adding a fourth
# kind is a line here instead of an `elif` somewhere a reader has to find.
VALUES_FOR = {KIND_AVOID: CATEGORIES, KIND_INGREDIENT: INGREDIENTS}

# No prefix: the proxy strips /api/ before forwarding, so the app serves /circles/… — the same
# convention the rounds and live routers keep, and a prefix here once produced a proxy-only 404.
router = APIRouter()

_resolve_member = resolve_member

# **The month boundary is Taipei's, owner-ruled 2026-08-27 (D25's amendment).** It used to be the
# database session's, which is UTC — so a band written in Taipei at 00:30 on the first of a month
# was stamped as if it were still the previous month, and for the eight hours before each UTC month
# end the server and the member disagreed about which month it was. D25's reason for a monthly
# boundary is 「salary is monthly」, which is a fact about a person in Taipei and not about a server.
# **Existing rows are not migrated** — they heal as members re-affirm.
#
# **This is D83's one stated exception and it is not a contradiction of it.** D83 rules that every
# *cron* here is UTC, and every cron still is: a schedule is machine time. A month boundary is a
# calendar a person reads, and reading it in the server's timezone is the same class of error as a
# client deriving its own.
#
# **Defined once, as an expression each query interpolates.** Two copies of a boundary is how two
# copies disagree — the failure this whole field exists to stop, one layer down.
TIMEZONE = "Asia/Taipei"

# The first instant of the current month, as a naive local timestamp. Everything below is built
# from this and nothing re-derives it.
_MONTH_START = "date_trunc('month', now() at time zone '{}')".format(TIMEZONE)

# Today, in Taipei. `current_date` is the session's — UTC — and using it to decide `expired` would
# reintroduce the same eight-hour skew inside the answer that reports the boundary.
_TODAY = "(now() at time zone '{}')::date".format(TIMEZONE)


def month_end_of(instant_sql: str) -> str:
    """The last day of the **Taipei** month that a timestamptz expression falls in.

    D25: salary is monthly, so a budget statement expires at the end of its own month — computed at
    write time and stored, because a boundary four readers each re-derive is how two of them
    disagree. Exported because `upto.fixture` builds a back-dated row and must land on this same
    boundary; a fixture with its own month arithmetic is a second clock by another name.

    **Pass a parenthesised expression, and this is a real trap rather than a style note.** The
    argument is interpolated straight into `{} at time zone …`, and `at time zone` binds tighter
    than arithmetic — so `now() - interval '13 months'` reassociates to
    `now() - (interval '13 months' at time zone 'Asia/Taipei')` and Postgres refuses with
    *function pg_catalog.timezone(unknown, interval) does not exist*. Measured 2026-08-28 while
    back-dating a fixture. `(now() - interval '13 months')` is right. A bare `now()` or a column
    name needs nothing.
    """
    return (
        "(date_trunc('month', {} at time zone '{}') + interval '1 month' - interval '1 day')::date"
    ).format(instant_sql, TIMEZONE)


# **The month the server's own expiry boundary falls in, `YYYY-MM`** — the evaluator's ask at
# A2-G13c, and the field a per-device acknowledgement is compared against.
#
# **Derived from the same `_MONTH_START` the expiry formula uses — never from a second conversion.**
# The field exists so a client can stop keeping a second clock; one derived a different way from the
# boundary it describes is a second clock with a nicer name, and it would disagree exactly at a
# month end, which is the only moment anybody looks. When the boundary moved from UTC to Taipei on
# 2026-08-27 this field moved with it and no client was told anything, which is what it is for.
SERVER_MONTH = "select to_char({}, 'YYYY-MM') as month".format(_MONTH_START)


# **D25 as amended 2026-08-28 (owner-ruled): a `persist = false` row lapses at READ time, and a
# lapsed row leaves the key with nothing in force.**
#
# **Why read time and not the erasure job.** `upto.privacy.erase` deletes every `persist = false`
# row nightly — except the ones a round pinned, which D24 makes undeletable. So a 「這次不吃」 that
# happened to be read by a roll survived for ever and stayed in force, which the evaluator's gate
# found on a live category (member 325, row 615, pinned by round 820). The row must stay — the pin
# says what was read — so what changes is what counts as *in force*: the row is history, the
# predicate is the answer.
#
# **The boundary is the erasure hour, 05:00 Taipei**, reused rather than invented: a second boundary
# would be a second clock, and D25's Taipei rule already exists for exactly this reason.
#
# **No fall-through, and that is the ruling rather than a convenience.** The latest row per key is
# taken first, as always; if *that* row is lapsed the key has nothing in force and nothing older is
# consulted. The rejected reading let a lapsed `allow` uncover a kept `avoid` beneath it — an
# avoidance a member had switched off would switch itself back on overnight, which is the opposite
# of what D17's opt-in default is for.
LAST_ERASURE_BOUNDARY = (
    "(date_trunc('day', (now() at time zone '{tz}') - interval '5 hours') + interval '5 hours')"
).format(tz=TIMEZONE)

#: **The one predicate, shared by the GET and the engine's loader.** Two reads of "in force" that
#: derive it separately are two answers waiting to disagree; `upto.engine.load` imports this string.
IN_FORCE_PREDICATE = (
    "(persist or (valid_from at time zone '{tz}') >= {boundary})"
).format(tz=TIMEZONE, boundary=LAST_ERASURE_BOUNDARY)


# `valid_from` and `expires_on` both come from the database's clock in one statement, so a month
# boundary cannot fall between two readings of two clocks. The boundary itself is `month_end_of`
# above — Taipei's month since 2026-08-27 — and this query interpolates it rather than restating it.
INSERT = """
insert into preference (member_id, kind, value, stance, persist, expires_on)
values (
    :member_id, :kind, :value, :stance, :persist,
    case when :kind = 'budget' then {month_end} else null end
)
returning id
""".format(month_end=month_end_of("now()"))

# The latest row per key, which is what "in force" means once nothing is edited. `distinct on` is
# the shape the index `ix_preference_in_force` was built for: (member_id, kind, valid_from desc).
IN_FORCE_BUDGET = """
select value, persist, expires_on, valid_from, expired from (
    select distinct on (kind) value, persist, expires_on, valid_from,
           (expires_on < {today}) as expired
      from preference
     where member_id = :member_id and kind = 'budget'
     order by kind, valid_from desc, id desc
) latest
 where {in_force}
""".format(today=_TODAY, in_force=IN_FORCE_PREDICATE)

# One row per avoided category — the latest stance for each value, then only the ones still
# `avoid`. An `allow` row is a real fact with a real history and is deliberately *not* returned:
# the screen asks "what am I avoiding", not "what have I ever said".
IN_FORCE_AVOID = """
select value, persist, valid_from from (
    select distinct on (value) value, stance, persist, valid_from
      from preference
     where member_id = :member_id and kind = :kind
     order by value, valid_from desc, id desc
) latest
 where stance = 'avoid' and {in_force}
 order by value
""".format(in_force=IN_FORCE_PREDICATE)
# **`kind` is a bound parameter and not two copies of the query, but it is passed explicitly at every
# call site** — never defaulted. An avoidance query that fell back to a kind would silently return
# categories to a caller asking about ingredients, and both lists are closed so nothing downstream
# would notice a wrong-kind value until it reached a screen.


# The evaluator's ask (2026-08-18), and the reason it is a payload field rather than a sentence in
# the markup: hardcoding today's proportion makes the screen's statement **false the moment the
# backfill runs**, silently. Same refusal M2 makes when it prints *insufficient history* instead of
# copying a cadence off a webpage. The denominator is the current reference publication — the set a
# member could actually propose from — and the numerator is the places that have a category, which
# is what decides whether an avoid can fire at all.
# **Which of D38's values no place in the current publication carries.** One row per value that is
# absent, so the caller gets a list rather than a shape to diff. `unnest` on the parameter rather
# than a literal list: the eleven live in `CATEGORIES` and this query must not become a twelfth
# place to keep them.
VALUES_WITH_NO_PLACES = """
with latest as (
    select id from place_publication order by detected_at desc, id desc limit 1
)
select v.value
  from unnest(cast(:values as text[])) as v(value)
 where not exists (
       select 1
         from reference_place rp
         join latest on true
         join place p
           on p.registry_no = rp.registry_no and p.origin = 'reference'
        where rp.publication_id = latest.id and p.category = v.value
 )
 order by v.value
"""


CATEGORY_COVERAGE = """
select (select count(*) from place where category is not null) as with_category,
       (select count(*) from reference_place
         where publication_id = (
             select id from place_publication order by detected_at desc, id desc limit 1
         )) as reference_rows
"""

# **`ingredient_coverage` is zero and is reported anyway (D103).** No place carries ingredient data —
# there is no source for it and none planned — so an ingredient avoidance is stored and produces no
# contribution. A screen offering eleven choices that change nothing must be able to say so, and the
# figure has to come from the payload for the same reason `category_coverage` does: the day a source
# arrives, a number written into markup becomes false silently.
#
# **It is computed rather than returned as a literal 0.** A hardcoded zero is indistinguishable from
# a query that broke, and it would keep reading zero after the column it counts starts filling. There
# is no ingredient column on `place` yet, so what this counts is the honest thing: nothing.
# **A19 made this a real query, and the literal `0` it replaced is the hazard, not a typo.** It was
# written when no place carried ingredient data and it said so in its own comment — and it would
# have gone on reporting zero for ever, silently, the day a source arrived. That day was 2026-08-29:
# 4,509 of 36,499 places have published materials. The same shape CLAUDE.md warns about for
# `category_coverage` — *today's figure becomes false the moment a backfill runs* — except a
# hard-coded constant cannot even drift into being wrong. It starts wrong and waits.
#
# **A place counts when its COMPANY publishes anything**, not when the materials name an allergen:
# the figure answers *how much of the city has published at all*, which is what a member reading
# 「N 家沒有資料」 needs. What those materials say is the veto's question, one layer down.
INGREDIENT_COVERAGE = """
select (select count(*) from reference_place rp
         where rp.publication_id = (
             select id from place_publication order by detected_at desc, id desc limit 1
         )
           and exists (
             select 1 from product_material pm
              where pm.company_name = rp.name
                and pm.publication_id = (
                  select id from brand_publication order by detected_at desc, id desc limit 1
                ))) as with_ingredient,
       (select count(*) from reference_place
         where publication_id = (
             select id from place_publication order by detected_at desc, id desc limit 1
         )) as reference_rows
"""


# **The proposable set, defined once (owner-ruled 2026-08-18, D22's amendment).** D22's breadth
# number needs a denominator, and "the feasible pool" is only defined inside a round — while the
# preference screen is by definition opened with none running (D17's decisive reason: payday lands
# with nothing open). The ruled denominator is **the circle's proposable set: every place any member
# could propose** — every `reference` place in the current publication, plus this circle's own
# `circle-local` places. Rejected: the last round's pool (answers a question about the past, so a
# member setting a preference after a quiet fortnight is warned against a pool nobody is choosing
# from) and the latest publication unscoped (counts thousands nobody in the circle would propose, so
# the proportion reads reassuringly small and means nothing).
#
# **The numerator can only count places that have a category**, because only a categorised place is
# reachable by a category stance — which is why the coverage figure below sits beside it rather than
# in the markup. That ceiling is about today's data, not about the definition: D22's 「碰到」 asks
# what the member's stances touch, and the ingredient half touches nothing only because no place
# carries ingredient data.
BREADTH = """
with latest as (
    select id from place_publication order by detected_at desc, id desc limit 1
),
proposable as (
    select p.category
      from reference_place rp
      join latest on true
      left join place p
        on p.registry_no = rp.registry_no and p.origin = 'reference'
     where rp.publication_id = latest.id
    union all
    select p.category
      from place p
     where p.origin = 'circle-local' and p.circle_id = :circle_id
)
select count(*) as proposable,
       -- **`touched`, and this is the field's second rename for the same reason: the name is a
       -- claim about behaviour.** It was `removed` until 2026-08-19 (a place is never removed — it
       -- stays proposable and stays in the pool), then `zeroed` until 2026-08-27, when D103 was
       -- reopened and a category stopped zeroing anything: it now discounts by `1 − 1/N`. A field
       -- still called `zeroed` would have gone on being read as *cannot be drawn* by every screen
       -- and every spec, which is exactly how 「拿掉」 got into a spec the first time.
       --
       -- **`touched` is D22 as the owner ruled it on 2026-08-27 — 「碰到」: the share of the
       -- proposable set any of this member's stances reaches at all**, whatever it does when it
       -- gets there. An ingredient's ×0 and a category's discount each count one place, because
       -- the question the number answers is *how much of the room have I had an opinion about*,
       -- not *how much have I killed*.
       -- **Categories alone again since 2026-08-30.** A19's ingredient join lived on this line
       -- for one day; the owner withdrew the kind from the surface (12.4% of the city declares
       -- anything, 「覆蓋率太小了，沒有意義」), so nothing on any screen can produce an ingredient
       -- stance and a join that can never match is a join that misleads whoever reads the query
       -- next. **The tables, the ingest and the stored rows all stay** — this is the surface
       -- leaving, not the data — so re-adding the `or (...)` block is a small change if a source
       -- ever makes the kind worth offering again.
       count(*) filter (where category = any(:avoided)) as touched
  from proposable
"""


# **D22's per-stance breakdown (owner-ruled 2026-08-19, `f51aec0`).** The combined figure above is
# what the threshold is applied to; this is what each stance zeroes on its own, so the screen can state
# every choice rather than only the total.
#
# **The two cannot be added up and must not be presented as if they could.** Categories are disjoint, so
# today the parts happen to sum to the whole — but the combined query is the authority and this one is
# the breakdown, and if a future kind ever overlaps (a place matching two stances) the sum would exceed
# the combined count while the combined count stayed right. Computed separately for that reason rather
# than derived from one pass, and the payload never invites the addition.
BREADTH_BY_STANCE = """
with latest as (
    select id from place_publication order by detected_at desc, id desc limit 1
),
proposable as (
    select p.category
      from reference_place rp
      join latest on true
      left join place p
        on p.registry_no = rp.registry_no and p.origin = 'reference'
     where rp.publication_id = latest.id
    union all
    select p.category
      from place p
     where p.origin = 'circle-local' and p.circle_id = :circle_id
)
select category, count(*) as touched
  from proposable
 where category = any(:avoided)
 group by category
"""


# **A19: the same question for an ingredient, and it is a different join rather than a different
# column.** A category lives on `place.category`; an ingredient lives on what a place's *company*
# published, so this reaches through `reference_place.name` into `product_material`. The rest is
# BREADTH_BY_STANCE's shape — the circle's proposable set (D22's ruled denominator), counted per
# stance.
#
# **`count(distinct rp.registry_no)`, not `count(*)`.** A company publishes many materials naming
# one group and a place would otherwise be counted once per material — 全家 has 87 products and
# would have reported hundreds of places touched by 蛋. The category query needs no such guard
# because a place has exactly one category.
#
# **Circle-local places are absent on purpose and the denominator still includes them.** A place a
# member typed has no company and no publisher, so it can never be touched by this — which is a true
# `unknown`, not a zero, and it is the same reason the payload's `share` is a share of the whole
# proposable set rather than of the places that published.
INGREDIENT_BY_STANCE = """
with latest as (
    select id from place_publication order by detected_at desc, id desc limit 1
),
brand as (
    select id from brand_publication order by detected_at desc, id desc limit 1
)
select pm.material_name as material, count(distinct rp.registry_no) as touched
  from reference_place rp
  join latest on true
  join brand on true
  join product_material pm
    on pm.company_name = rp.name and pm.publication_id = brand.id
 where rp.publication_id = latest.id
   and pm.material_name = any(:materials)
 group by pm.material_name
"""


class PreferenceBody(BaseModel):
    kind: str
    value: str
    # D17's default, expressed where the default belongs: absent means not kept.
    persist: bool = False
    stance: str | None = None


def _validate(body: PreferenceBody) -> None:
    """Refuse anything outside the closed lists, naming the list. Never coerce (D39).

    Coercing a near-miss — 「拉麵」 to 麵食, or a missing stance to `avoid` — would turn a client
    bug into a plausible stored fact, which is the H23 shape this schema keeps meeting. A default
    stance is the one that would hurt: it would let a malformed request *start* an avoidance.
    """
    # **One kind on the wire since 2026-08-30, and three still in the database.** The owner
    # withdrew `budget` and `avoid_ingredient` from the surface (「將選擇權還給使用者，我們專心做好
    # 分類」); `ck_preference_kind` still names all three and the 9 budget and 81 ingredient rows
    # stay where they are, because D24's pins reference preference rows and a screen losing a chip
    # is not a reason to delete what a member asked to keep. So: refused **here**, at the door, and
    # nowhere else.
    #
    # **422 and not 400, and the kind is named in the detail.** A retired kind is a well-formed
    # request the server will not process, and a client that gets a bare 400 cannot tell "you sent
    # nonsense" from "that feature is gone".
    # **Two refusals, two codes, and the difference is the point.** A kind this server has never
    # heard of is a malformed request — 400, as it always was. A kind it knows and has *retired*
    # is a well-formed request it will not process — 422, naming what happened. A client that gets
    # one code for both cannot tell "you sent nonsense" from "that feature is gone", and the second
    # is the one somebody needs to read in a changelog.
    if body.kind in RETIRED_KINDS:
        raise HTTPException(
            status_code=422,
            detail=(
                "{!r} was withdrawn from the surface on 2026-08-30 and is no longer accepted; "
                "{} is the only kind. Rows already stored under the retired kinds are kept and "
                "are never returned.".format(body.kind, KIND_AVOID)
            ),
        )
    if body.kind != KIND_AVOID:
        raise HTTPException(
            status_code=400,
            detail="kind must be {} — {!r} is not".format(KIND_AVOID, body.kind),
        )
    allowed = VALUES_FOR[body.kind]
    if body.value not in allowed:
        raise HTTPException(
            status_code=400,
            detail="a category must be one of ({}) — {!r} is not".format(
                "、".join(allowed), body.value
            ),
        )
    if body.stance not in STANCES:
        raise HTTPException(
            status_code=400,
            detail="an avoidance needs a stance, one of {} — {!r} is not. It is not defaulted: a "
            "malformed request must not be able to start an avoidance.".format(
                ", ".join(STANCES), body.stance
            ),
        )


@router.post("/circles/{circle_id}/preferences", status_code=204, response_class=Response)
async def record_preference(circle_id: int, body: PreferenceBody, request: Request) -> Response:
    """Append one preference row. Answers 204 with nothing, and publishes nothing.

    **The absence of a `publish(...)` call in this function is load-bearing.** Every other write
    in this application announces itself on the circle's stream; this one must not, and a future
    reader adding one "for consistency" would undo §3.0. The integration test asserts the stream
    stays quiet across a write.

    No 409: a second write is not a conflict, it is the next version. That is D70's quiet-success
    shape applied to a table that appends.
    """
    # **The credential first, the body second, and the order is a rule rather than a style.** A
    # request with no token must read 401 whatever it carries: validating first told an anonymous
    # caller which kinds this server accepts and which it has retired, and it turned the 401
    # contract into "401 unless your body is also wrong". Caught 2026-08-30 by
    # `test_preference_integration`'s no-token line going 422.
    async with session_factory()() as session:
        member_id = await _resolve_member(session, request, circle_id)
        _validate(body)
        await session.execute(
            text(INSERT),
            {
                "member_id": member_id,
                "kind": body.kind,
                "value": body.value,
                "stance": body.stance,
                "persist": body.persist,
            },
        )
        await session.commit()
    # 204 and no body. Not the row's id, not the value back — see the module docstring.
    return Response(status_code=204)


@router.get("/circles/{circle_id}/preferences")
async def preferences_in_force(circle_id: int, request: Request) -> dict:
    """What this member has in force — resolved here, never in the client (D5, D13).

    D25 requires this: the screen arrives with the value filled in rather than asking again — and
    that includes a band whose month has ended, flagged `expired` so the screen can prompt the
    re-affirmation D25 asks for rather than presenting a stale number as current. The history is
    not returned; a member does not need last month's band to change this month's, and
    a payload carrying twelve months of a person's states is a larger thing to hand out than the
    one fact the screen needs.

    **Shaped so D22's breadth number can be added without moving anything** — it will arrive as a
    sibling key when the owner has ruled what "the feasible pool" means outside a round, which is
    the one thing D22 defines only inside one.
    """
    async with session_factory()() as session:
        member_id = await _resolve_member(session, request, circle_id)
        avoided = (
            await session.execute(
                text(IN_FORCE_AVOID), {"member_id": member_id, "kind": KIND_AVOID}
            )
        ).all()
        coverage = (await session.execute(text(CATEGORY_COVERAGE))).one()
        # **Which of D38's values no place carries yet — asked, never assumed.** `便利商店` arrived
        # on 2026-08-30 and every one of the city's 2,110 convenience-store rows still reads 其他
        # until the v6 re-pass runs, so that chip's stat is a true 0 家 for a reason the member
        # cannot guess. A silent zero reads as "there are none of those near you"; this makes the
        # screen able to say which it is. It empties itself the day the re-pass lands.
        unclassified = [
            row.value for row in (
                await session.execute(text(VALUES_WITH_NO_PLACES),
                                      {"values": list(CATEGORIES)})
            ).all()
        ]
        breadth = (
            await session.execute(
                text(BREADTH),
                {
                    "circle_id": circle_id,
                    "avoided": [row.value for row in avoided],
                },
            )
        ).one()
        per_stance = {
            row.category: row.touched
            for row in (
                await session.execute(
                    text(BREADTH_BY_STANCE),
                    {"circle_id": circle_id, "avoided": [row.value for row in avoided]},
                )
            ).all()
        }
    return {
        # **`month` left this payload on 2026-08-30 with the budget.** It was the *budget's*
        # boundary — D25's one stated exception to D83's UTC rule — and a month on the wire that
        # nothing on the screen is bounded by is a fact waiting to be misread as "this expires".
        # `month_end_of` and `_TODAY` stay in this module: A2's fixture still writes an expiring
        # row and the 9 stored budgets still carry one.
        # **D22's breadth, with its denominator stated in the payload rather than assumed.** The
        # evaluator refuses an unstated denominator at the gate and is right to: the same share
        # means three different things over three candidate pools, and a warning nobody can check
        # is not a warning. `threshold` is `null` on purpose — **D22 says "when that crosses the
        # line" and names no number**, so the line is unruled and this payload will not invent
        # one. A screen may state the share; it may not say "crossed" until there is a line.
        "breadth": {
            # **`touched`, renamed from `zeroed` on 2026-08-27 with D22's 「碰到」 ruling.** The
            # field has now been renamed twice for the same reason, and that is the lesson rather
            # than the churn: `removed` was read as *taken out of the set*, `zeroed` as *cannot be
            # drawn*, and since D103 was reopened a category neither removes nor zeroes — it
            # discounts by `1 − 1/N`. A field name is a claim about behaviour, and the claim has to
            # be re-checked every time the behaviour moves.
            "touched": breadth.touched,
            "proposable": breadth.proposable,
            "share": 0.0
            if not breadth.proposable
            else round(breadth.touched / breadth.proposable, 4),
            "denominator": "the circle's proposable set — every reference place in the current "
                           "publication, plus this circle's own places",
            # **0.5, owner-ruled 2026-08-19 (`f51aec0`), applied to the member's COMBINED breadth** —
            # all their stances together over the proposable set, which is what `share` above is. It
            # was `null` until today and D22's warning could therefore never render; the evaluator had
            # split its own gate line into a real half and an `n/a` half for exactly that reason.
            "threshold": 0.5,
            # **Decided here, not in the browser.** The same argument as `counts` on A6's seat list:
            # a surface that computes whether the line was crossed can compute it wrong, and a payload
            # that states it cannot. It also keeps the comparison's direction in one place — `>` and
            # not `>=`, so a member sitting exactly on half is not warned about it.
            "crossed": bool(
                breadth.proposable
                and (breadth.touched / breadth.proposable) > 0.5
            ),
        },
        # **What an avoid can currently reach.** Not decoration: only a place with a category can be
        # avoided, so this is the honest bound on the whole feature. The screen states it and never
        # advises on it.
        #
        # **No number in this comment, deliberately — it had one and the number rotted.** It read
        # "6.2% today because one township has been classified"; five townships later the live figure
        # is nearly a third, and a stale figure in a comment beside the code that computes the live
        # one is worse than no figure, because a reader trusts the nearby prose over the query.
        # `with_category / reference_rows` below is the answer, and it is the only place that has it.
        #
        # **The word matters as much as the number (adopted 2026-08-19 from the evaluator).** Three
        # different quantities have all been called "coverage" and they were 28 points apart: rows the
        # classifier *processed*, rows that came out *categorised*, and rows carrying a category that
        # actually *discriminates* (其他 alone was 41% of processed). This field is **categorised** —
        # what the avoid machinery can read — which is the right one for this surface, because a
        # member gains nothing from a row the model looked at and declined to categorise. Never write
        # `coverage` bare; the denominator being named did not save anyone here, because it was the
        # *numerator* that was ambiguous.
        "category_coverage": {
            "with_category": coverage.with_category,
            "reference_rows": coverage.reference_rows,
            "share": 0.0
            if not coverage.reference_rows
            else round(coverage.with_category / coverage.reference_rows, 4),
        },
        # **Each stance says what it zeroes on its own (D22's amendment, `f51aec0`).** So the screen
        # can state every choice — 「火鍋 讓 354 家擲不到」 — rather than only the total, which is the
        # number a member can actually act on: the combined figure tells them they have narrowed a lot
        # and not which choice did it.
        #
        # **`touched` here and `touched` in `breadth` are the same word for the same thing on
        # purpose.** Neither is `removed` and neither is `zeroed` any more: a category stance
        # discounts a place by `1 − 1/N` (D103 as reopened), the place stays proposable, and it
        # keeps a real share of the dice table.
        "avoid_categories": [
            {
                "value": row.value,
                "persist": row.persist,
                "valid_from": row.valid_from.isoformat(),
                "touched": per_stance.get(row.value, 0),
                "share": 0.0
                if not breadth.proposable
                else round(per_stance.get(row.value, 0) / breadth.proposable, 4),
            }
            for row in avoided
        ],
        # **Which of the eleven no place carries yet, so a true zero can say why.** `便利商店`
        # is the whole of this list on 2026-08-30 and is expected to leave it after the v6
        # city re-pass; a value here means the chip works and there is nothing for it to reach
        # *yet*, which is a different sentence from "there are none near you". Derived from the
        # database, never a literal — the day the re-pass lands this empties itself.
        "values_awaiting_classification": {
            "values": unclassified,
            "why": "分類器尚未以 v6 重跑全市；這些類別目前沒有任何店家（2026-08-30）",
        },
    }
