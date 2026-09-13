"""A24 — self-serve circles: create one, join it by a shared link, replace that link.

*Candidate 21, from the self-serve sitting of 2026-09-13 (`doc/issues/A24-self-serve-circles.md`).
Until this file existed the only door into a circle was `python -m upto.issue` on an operator's
machine — D74's own docstring said so and `SEAT_CAP`'s comment said what would land here.*

**Three secrets leave this module and each leaves exactly once.** A device key on create, a device
key on join, a join ticket on create and on re-issue. In every case only a sha256 is stored, so a
database read cannot produce a working credential (D74), and the plaintext exists in one HTTP
response and nowhere else — not in a log, not in a query string. The client puts it in the URL
**fragment** (A20), which reaches no proxy log, no `Referer` and not this API.

**The seat cap is D110's and it is read from `issue.SEAT_CAP`, never restated.** `grow_seat` was
extracted from the CLI for this file so that the count happens in one place; a second door with its
own copy of «ten» would be the boundary spelled twice.

**What a leaked ticket can do, because it decides the shapes below.** A tap grows a seat; a seat
reads nicknames, proposals and reveals, and cannot read another member's preferences. The radius is
`SEAT_CAP - seats` strangers and it is a **total, not a rate** — there is no leave, no seat reuse
and no churn, so a circle of five can absorb at most five before the ticket is dead of its own
accord. That bound is why re-issue exists and why expiry does not (A24's research paragraph).
"""

from __future__ import annotations

import os
from hashlib import sha256

import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .api_common import resolve_credential
from .db import session_factory
from .issue import SEAT_CAP, SeatRefused, grow_seat
from .issue import DEFAULT_PUBLIC_ORIGIN, PUBLIC_ORIGIN_VAR

router = APIRouter(prefix="/circles", tags=["circles"])

#: **A server-side daily ceiling, beside the proxy's per-address one and not instead of it.** The
#: proxy rule is the cheap one and it is not a rule this API can prove — a request that never
#: reaches nginx (a direct origin hit, a future second front door) is not covered by it. This is the
#: floor under that.
#:
#: **It counts circles created since Taipei's midnight, and whether it MAY is not ruled yet.** The
#: reviewer's note, 2026-09-13: D25's exception to D83's UTC rule was argued from a **member-facing
#: month**, and whether an operational cap inherits that argument is exactly what the owner has not
#: decided. **The code's day is Taipei until he rules**; it is one clause either way, and going to
#: him with the sweep. *Stating it as «D25's exception applied» — which this comment did — asserted
#: a ruling that does not exist.*
DAILY_CIRCLE_CEILING = int(os.environ.get("UPTO_DAILY_CIRCLE_CEILING", "200"))


def join_link(circle_id: int, ticket: str) -> str:
    """`<origin>/join#c=<circle_id>&t=<ticket>` — the ticket in the FRAGMENT, like D74's key.

    Same rule as `issue.invite_link` and the same reason: a fragment reaches no proxy log, no
    `Referer` and not this API, which is what keeps «the ticket lives only in the group chat» true
    once it travels in a URL. The circle id rides along because one string is one thing to paste.
    """
    origin = (os.environ.get(PUBLIC_ORIGIN_VAR) or DEFAULT_PUBLIC_ORIGIN).rstrip("/")
    return "{}/join#c={}&t={}".format(origin, circle_id, ticket)


#: **One hour, owner-ruled 2026-09-13** — 「約一頓飯使用…哪需要那麼長時間，占用不必要的資源」,
#: overriding A24's recommendation of no expiry. The argument that won is not the one I argued
#: against: it is that a link outliving the meal it was made for holds resources for nothing, which
#: is a different question from whether a leaked ticket is dangerous. **Recorded as an interval in
#: one place** so the ticket, the refusal and the test read the same number.
#:
#: **The cost of the ruling, stated rather than argued again:** a friend tapping the link two hours
#: later is refused, and the fix is the creator re-issuing — which is why re-issue landed first.
TICKET_LIFETIME = "1 hour"


async def _mint_ticket(session, circle_id: int) -> str:
    """Revoke whatever is live for this circle, insert a new one, return the plaintext.

    **Revoke-then-insert in one call, because «revoke» alone is not an operation anybody wants.**
    It would leave a circle nobody can join — a state a worried person creates by accident, pressing
    the button that shuts a stranger out and killing their real friend's link with it. The only
    operation is «a new link; the old one stops working», so whatever they press leaves them
    something to share (A24).

    The partial unique index (`circle_id where revoked_at is null`) is what makes this safe under a
    race: two simultaneous re-issues cannot both leave a live row.
    """
    token = secrets.token_urlsafe(32)
    await session.execute(
        text("update join_ticket set revoked_at = now() "
             "where circle_id = :c and revoked_at is null"),
        {"c": circle_id},
    )
    # `now()` twice rather than `created_at + interval` in a second statement: the two columns are
    # written by one row, so they cannot disagree about when this ticket began.
    await session.execute(
        text("insert into join_ticket (circle_id, token_sha256, expires_at) "
             "values (:c, :h, now() + interval '{}')".format(TICKET_LIFETIME)),
        {"c": circle_id, "h": sha256(token.encode("utf-8")).hexdigest()},
    )
    return token


class _Trimmed(BaseModel):
    """**Strip first, then require something left — because `min_length` counts spaces.**

    Measured 2026-09-13 against the running stack: a name of three spaces passed Pydantic, reached
    `ck_circle_name_not_blank` and came back **500 Internal Server Error**. The database was right
    and the answer was wrong twice over — a 500 says «we broke», and the person who typed spaces
    would have no idea what to change. The constraints stay: this is the second line, not a
    replacement for them.
    """

    @field_validator("*", mode="after")
    @classmethod
    def _strip(cls, value):
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            raise ValueError("這裡不能只有空白。")
        return stripped


class CreateCircle(_Trimmed):
    name: str = Field(min_length=1, max_length=80)
    nickname: str = Field(min_length=1, max_length=40)


class JoinCircle(_Trimmed):
    ticket: str = Field(min_length=1, max_length=200)
    nickname: str = Field(min_length=1, max_length=40)


@router.post("", status_code=201)
async def create_circle(body: CreateCircle, request: Request) -> dict:
    """The circle, the creator's operator seat and the first join ticket — one transaction.

    **No credential is required and that is the whole feature**: a stranger on the live site can do
    this. The bound on «a stranger can do this» is the ceiling below plus the proxy's per-address
    rule, not authentication.

    **The creator's seat is an operator seat (D105).** The role rides the secret, so the person who
    made the circle is the one who can re-issue its link, and there is no parameter by which anyone
    else could ask to be.
    """
    async with session_factory()() as session:
        # **The ceiling is checked before anything is written**, the same arrangement `grow_seat`
        # uses for the cap: a refusal leaves no circle, no principal, no seat and no ticket.
        # **The same check-then-act shape as the seat cap, and it is LEFT that way deliberately**
        # (the reviewer's call, 2026-09-13, and I agree). Overshooting a flood ceiling by a handful
        # of circles costs nothing; a lock here would serialise **every creation on the box** — the
        # one request path that is meant to be reachable by a stranger. The seat cap got a lock
        # because eleven seats breaks a ruling a leaked ticket is bounded by; 203 circles on a day
        # capped at 200 breaks nothing.
        made_today = (
            await session.execute(
                text("select count(*) from circle "
                     "where created_at >= date_trunc('day', now() at time zone 'Asia/Taipei')"
                     " at time zone 'Asia/Taipei'")
            )
        ).scalar_one()
        if made_today >= DAILY_CIRCLE_CEILING:
            raise HTTPException(status_code=429, detail="今天開的圈子太多了，明天再來。")

        name = body.name
        circle_id = (
            await session.execute(
                text("insert into circle (name) values (:n) returning id"), {"n": name}
            )
        ).scalar_one()
        try:
            member_id, _, key = await grow_seat(
                session, circle_id, body.nickname, operator=True
            )
        except SeatRefused as refused:
            # A brand-new circle cannot be full and cannot be missing, so anything here is a bug
            # rather than a member's mistake — 500 rather than a member-facing sentence that would
            # be a lie about whose fault it is.
            raise HTTPException(status_code=500, detail=refused.reason) from None
        ticket = await _mint_ticket(session, circle_id)
        await session.commit()

    return {
        "circle_id": circle_id,
        "member_id": member_id,
        "key": key,
        "join_link": join_link(circle_id, ticket),
    }


@router.post("/{circle_id}/join", status_code=201)
async def join_circle(circle_id: int, body: JoinCircle, request: Request) -> dict:
    """Grow a seat from the shared ticket, and hand back a key of this device's own.

    **The four refusals are deliberately different sentences**, because they need different actions
    from the person reading them: a full circle is nobody's mistake, a replaced link needs a word
    with the creator, an unknown one is a mistyped paste, and the ceiling is ours.

    **A revoked ticket answers 410 and an unknown one 404, and that difference is not a probe.** The
    ticket is 32 random bytes; a caller who does not hold one cannot reach the 410 branch by
    guessing, so telling a holder that their link was *replaced* rather than that it never existed
    costs nothing and is the only message they can act on.
    """
    digest = sha256(body.ticket.encode("utf-8")).hexdigest()
    async with session_factory()() as session:
        # **`expired` is computed by the database, in the same statement.** It used to be a second
        # round trip comparing the returned timestamp against `now()`, which asked the same server
        # the same question twice and left a window between the two answers.
        row = (
            await session.execute(
                text("select circle_id, revoked_at, "
                     "(expires_at is not null and expires_at <= now()) as expired "
                     "from join_ticket where token_sha256 = :h"),
                {"h": digest},
            )
        ).one_or_none()
        # The circle in the path must be the ticket's own: a ticket is for one circle and a
        # mismatch is an unknown ticket, not a seat somewhere else.
        if row is None or row.circle_id != circle_id:
            raise HTTPException(status_code=404, detail="這個連結沒有用，跟朋友要一次。")
        if row.revoked_at is not None:
            raise HTTPException(status_code=410, detail="這個連結換過了，跟建立的人要新的。")
        if row.expired:
            # **A different sentence from the revoked one, because the remedy is the same and the
            # reason is not.** A person whose link was replaced knows somebody did something; a
            # person whose link ran out needs to know the link has a life at all, or the next one
            # will sit in the group chat overnight too.
            raise HTTPException(
                status_code=410, detail="這個連結只能用一小時，過期了。跟建立的人要新的。"
            )

        try:
            member_id, _, key = await grow_seat(session, circle_id, body.nickname)
        except SeatRefused as refused:
            if refused.reason == "full":
                raise HTTPException(
                    status_code=409, detail=f"這個圈子滿了，最多{SEAT_CAP}個人。"
                ) from None
            raise HTTPException(status_code=404, detail="這個連結沒有用，跟朋友要一次。") from None
        await session.commit()

    return {"member_id": member_id, "key": key}


@router.post("/{circle_id}/join-ticket", status_code=201)
async def reissue_ticket(circle_id: int, request: Request) -> dict:
    """A new link; the old one stops working. Operator credential only.

    **It does not remove a seat that has already joined**, and that is stated rather than assumed:
    the stranger stops being able to invite others, not to be there. Eject is a separate ruling with
    a data-deletion half (D42, H22) and is deliberately out of this candidate.
    """
    async with session_factory()() as session:
        _, is_operator = await resolve_credential(session, request, circle_id)
        if not is_operator:
            # D105's split: the role came from the presented secret, so this cannot be argued with.
            raise HTTPException(status_code=403, detail="只有開圈子的人可以換連結。")
        try:
            ticket = await _mint_ticket(session, circle_id)
            await session.commit()
        except IntegrityError:
            # The partial unique index under a simultaneous re-issue. The other one won; the caller
            # asking again gets that one's replacement, which is the same outcome they asked for.
            raise HTTPException(status_code=409, detail="剛剛換過了，重新整理看看。") from None

    return {"join_link": join_link(circle_id, ticket)}


@router.get("/{circle_id}/join-ticket")
async def ticket_status(circle_id: int, request: Request) -> dict:
    """Is this circle's link still live, and until when — **without the link, and without holding it.**

    *The evaluator's ruling, 2026-09-13, correcting my own first answer. I built
    `…/join-ticket/check {ticket}` believing the creator's device would still hold the string.
    **The creator does not have the ticket** — it was shown once and is stored only as a hash,
    which is precisely why they are on a durable screen looking for it. A screen that must supply
    the ticket in order to ask about the ticket cannot be used by the person who lost it.*

    **It returns no link and it never will.** `join_ticket` holds `token_sha256` and nothing else,
    so returning one would mean storing the plaintext — trading away the property that makes a
    database read, or the nightly dump in S3, useless to whoever gets one (D74). The screen shows
    **no link box and the re-issue control**, which is an honest hole rather than a remembered link
    that quietly died an hour ago.

    **Keyed on the creator's own credential**, which is the only thing they still have.
    """
    async with session_factory()() as session:
        _, is_operator = await resolve_credential(session, request, circle_id)
        if not is_operator:
            raise HTTPException(status_code=403, detail="只有開圈子的人可以看連結。")
        row = (
            await session.execute(
                text("select expires_at, (expires_at is not null and expires_at <= now()) "
                     "as expired from join_ticket "
                     "where circle_id = :c and revoked_at is null"),
                {"c": circle_id},
            )
        ).one_or_none()

    # **«No live ticket» and «a live ticket that has run out» are different answers**, and the
    # screen's next sentence differs: one is «press re-issue», the other is «press re-issue, and
    # this is why the link you sent stopped working». Collapsing them loses the reason.
    if row is None:
        return {"active": False, "expired": False, "expires_at": None}
    return {"active": not row.expired, "expired": bool(row.expired), "expires_at": row.expires_at}


class TicketCheck(_Trimmed):
    ticket: str = Field(min_length=1, max_length=200)


@router.post("/{circle_id}/join-ticket/check")
async def check_ticket(circle_id: int, body: TicketCheck, request: Request) -> dict:
    """Is the link this device already holds still good, and until when?

    *Frontend asked for `GET /join-ticket` returning the current link, 2026-09-13. **No endpoint
    can return a link**, and the reason is the design's own: only `token_sha256` is stored, so the
    server cannot reconstruct a ticket it has never held in plaintext (D74). That property is what
    makes a database read — or the nightly dump sitting in S3 — useless to somebody who gets one.
    Storing the plaintext to make a durable screen possible would trade it away for a convenience.*

    **So the link stays on the creator's device and this answers the question the device cannot.**
    That closes the exact hole frontend named in their own rejected option: a remembered link shown
    on a screen whose whole job is the link, quietly dead for an hour, looking live. The device
    holds the string; the server holds the truth about it.

    **A POST for a read, and the exposure now has a file path rather than a principle.** The ticket
    is a seat-granting secret, so it may not travel in a query string — that reaches the proxy's
    access log, this API's own logs and the next request's `Referer`, the same rule that put it in
    the URL fragment (A20). **And since candidate 20 the proxy's `access_log` records the VISITOR'S
    REAL ADDRESS for every request but `/health`**, in the container's json-file driver, 10 MB × 3,
    on the box (measured by the reviewer, 2026-09-13). A `GET …/check?ticket=` would write a
    seat-granting secret **next to the IP of the person who sent it**, and keep three rotations of
    it. A body is the only place it can go. **The method is wrong about intent and right about
    exposure, and exposure wins** — if anybody ever «tidies» this to a GET, this paragraph is the
    argument.

    **Operator credential only.** It tells you whether a seat-granting secret is live; that is the
    creator's question and nobody else's.
    """
    async with session_factory()() as session:
        _, is_operator = await resolve_credential(session, request, circle_id)
        if not is_operator:
            raise HTTPException(status_code=403, detail="只有開圈子的人可以看連結。")
        row = (
            await session.execute(
                text("select circle_id, revoked_at, expires_at, "
                     "(expires_at is not null and expires_at <= now()) as expired "
                     "from join_ticket where token_sha256 = :h"),
                {"h": sha256(body.ticket.encode("utf-8")).hexdigest()},
            )
        ).one_or_none()

    # **Four states and they are not the same sentence.** A screen that collapses them shows a dead
    # link as live, which is the failure this endpoint exists to prevent.
    if row is None or row.circle_id != circle_id:
        return {"status": "unknown", "expires_at": None}
    if row.revoked_at is not None:
        return {"status": "revoked", "expires_at": None}
    if row.expired:
        return {"status": "expired", "expires_at": row.expires_at}
    return {"status": "live", "expires_at": row.expires_at}


@router.get("/{circle_id}/members")
async def circle_members(circle_id: int, request: Request) -> dict:
    """Who is at the table — nicknames, in the order they joined, and nothing else.

    *Added on frontend's finding, 2026-09-13: the spec's §2c draws a seat list and two gate lines
    measure it, and before a round exists a circle's membership was unreadable — nicknames reached a
    client in exactly two places and both were round-scoped.*

    **No `member_id`, by rule.** §3.0 and H3: a member id is an identifier a screen never needs and
    a correlation somebody else might. This is the same shape `rolls[]` already sets.

    **Any member of the circle, not the operator alone.** Everyone at the table can see who is at
    the table, and the alternative is a product shape nobody ruled — a joiner who cannot see who
    else is in the circle they just joined. It still needs a credential: a circle's membership is
    not public, and a bare id must not enumerate one.

    **Duplicate nicknames come back as the server holds them**, because §7 rules duplicates legal
    and the screen adds no marker. This endpoint deduplicates nothing; two 小明 are two rows.
    """
    async with session_factory()() as session:
        await resolve_credential(session, request, circle_id)
        rows = (
            await session.execute(
                text("select nickname from member where circle_id = :c order by id"),
                {"c": circle_id},
            )
        ).scalars().all()
    return {"members": [{"nickname": n} for n in rows], "seats": len(rows), "cap": SEAT_CAP}
