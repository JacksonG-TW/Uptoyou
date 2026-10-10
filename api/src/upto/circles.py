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

import hmac
import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256

import secrets

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .api_common import resolve_credential, submit_state
from .auth import credential_for
from .db import session_factory
from .issue import SEAT_CAP, SeatRefused, grow_seat
from .issue import DEFAULT_PUBLIC_ORIGIN, PUBLIC_ORIGIN_VAR
from .rounds import ROUND_FOR_CLOSE, PoolSwept, close_round
from .stream import publish

router = APIRouter(prefix="/circles", tags=["circles"])

#: **A server-side daily ceiling, beside the proxy's per-address one and not instead of it.** The
#: proxy rule is the cheap one and it is not a rule this API can prove — a request that never
#: reaches nginx (a direct origin hit, a future second front door) is not covered by it. This is the
#: floor under that.
#:
#: **It counts circles created since Taipei's midnight — D83's second exception, ruled 2026-09-14**
#: (owner 「台北」; D83's «Two exceptions» paragraph). The ceiling is a number a member reads as
#: 「今天」, and a UTC day turns over at 08:00 Taipei, which would make that word false for eight hours
#: of every day. Every cron and the stack's clock stay UTC. `test_self_serve_integration` evaluates
#: the boundary at fixed instants either side of 16:00 UTC, where this day turns.
DAILY_CIRCLE_CEILING = int(os.environ.get("UPTO_DAILY_CIRCLE_CEILING", "200"))

# **The per-address half of the day, held in memory and nowhere else (owner 「A」, 2026-10-10).** nginx
# cannot rate below one request a minute («If a rate of less than one request per second is desired,
# it is specified in request per minute», nginx.org limit_req, read 2026-10-10), which is about 1,440
# a day per address — so one address could spend the whole ceiling above and lock creation for
# everyone. This counts creations per address per Taipei day:
# - **the address is never stored or logged**: the key is an HMAC under a random key made at process
#   start and never written anywhere, so a key in memory cannot be turned back into an address, and
#   a restart forgets every count (the owner accepted the reset);
# - **per process**: with N api instances an address gets N × the cap, still far under the ceiling;
# - **counted only behind the proxy**: the address is the LAST `X-Forwarded-For` entry, the one nginx
#   appends from its own `$remote_addr` (after realip). A request with no such header did not come
#   through the proxy — on the box the api publishes no port, so that is only the dev machine's
#   loopback fixture door, which the harnesses use precisely to skip the proxy's limits.
PER_ADDRESS_DAILY = int(os.environ.get("UPTO_CIRCLES_PER_ADDRESS_DAY", "5"))
_ADDRESS_KEY = secrets.token_bytes(32)
_TAIPEI = timezone(timedelta(hours=8))   # no DST in Taiwan
#: Bounded: past this many distinct addresses in one day the table is cleared rather than grown.
#: An attacker holding that many addresses has already beaten any per-address rule.
_ADDRESS_TABLE_MAX = 50_000
_made_by_address: dict = {"day": None, "counts": {}}


def _address_of(request: Request) -> bytes | None:
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return None
    last = forwarded.split(",")[-1].strip()
    return hmac.new(_ADDRESS_KEY, last.encode(), sha256).digest() if last else None


def _spend_address_day(request: Request) -> bytes | None:
    """Refuse this address once it has made PER_ADDRESS_DAILY circles today; else reserve one.

    Returns the reserved key, which `_refund_address_day` gives back when the creation then fails
    (the global ceiling, a database error): the count is of circles made, not of attempts."""
    address = _address_of(request)
    if address is None:
        return None
    today = datetime.now(_TAIPEI).date()
    table = _made_by_address
    if table["day"] != today or len(table["counts"]) >= _ADDRESS_TABLE_MAX:
        table["day"], table["counts"] = today, {}
    made = table["counts"].get(address, 0)
    if made >= PER_ADDRESS_DAILY:
        raise HTTPException(status_code=429, detail="你今天開的圈子夠多了，明天再來。")
    table["counts"][address] = made + 1
    return address


def _refund_address_day(address: bytes | None) -> None:
    counts = _made_by_address["counts"]
    if address is not None and counts.get(address, 0) > 0:
        counts[address] -= 1

#: The start of «today» in Taipei, as a timestamptz, for an instant `{now}`. One spelling for the
#: query below and for the test that pins it at fixed instants — a boundary written twice is a
#: boundary that drifts.
TAIPEI_DAY_START = "date_trunc('day', {now} at time zone 'Asia/Taipei') at time zone 'Asia/Taipei'"


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


#: **Counted in code points, by the server alone.** A client `maxLength` counts UTF-16 units and can
#: cut an IME composition mid-word, so the one count and the one sentence live here (frontend's ask,
#: 2026-10-09). `👨‍👩‍👧` is one glyph and five code points, which is why the sentences say so.
NAME_MAX = 80
NICKNAME_MAX = 40


class CreateCircle(_Trimmed):
    # **No `max_length` on the two typed fields, on purpose.** Pydantic's 422 carries a list as its
    # `detail`, which the surface cannot read, so a person who typed too much saw only a status.
    # The handler refuses with a sentence instead; the proxy's 32k body cap still bounds the input.
    name: str = Field(min_length=1)
    nickname: str = Field(min_length=1)


class JoinCircle(_Trimmed):
    ticket: str = Field(min_length=1, max_length=200)
    nickname: str = Field(min_length=1)


def _refuse_too_long(nickname: str, name: str | None = None) -> None:
    """The over-length refusal, as a sentence the person can act on. The literals stay inside
    `detail=` so `server_copy.py` reads them and the font subset draws them."""
    if name is not None and len(name) > NAME_MAX:
        raise HTTPException(
            status_code=422,
            detail="圈子名稱太長了，最多80個字。一個表情符號可能算好幾個字。",
        )
    if len(nickname) > NICKNAME_MAX:
        raise HTTPException(
            status_code=422,
            detail="暱稱太長了，最多40個字。一個表情符號可能算好幾個字。",
        )


@router.post("", status_code=201)
async def create_circle(body: CreateCircle, request: Request) -> dict:
    """The circle, the creator's operator seat and the first join ticket — one transaction.

    **No credential is required and that is the whole feature**: a stranger on the live site can do
    this. The bound on «a stranger can do this» is the ceiling below plus the proxy's per-address
    rule, plus the in-memory per-address day (`PER_ADDRESS_DAILY`), not authentication.

    **The creator's seat is an operator seat (D105).** The role rides the secret, so the person who
    made the circle is the one who can re-issue its link, and there is no parameter by which anyone
    else could ask to be.
    """
    _refuse_too_long(body.nickname, body.name)
    # Before the database: no await between the read and the reservation, so one worker cannot
    # race it. A creation that then fails gives its reservation back (the count is of circles made).
    reserved = _spend_address_day(request)
    try:
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
                    text("select count(*) from circle where created_at >= "
                         + TAIPEI_DAY_START.format(now="now()"))
                )
            ).scalar_one()
            if made_today >= DAILY_CIRCLE_CEILING:
                raise HTTPException(status_code=429, detail="今天開的圈子太多了，明天再來。")

            name = body.name
            # **`self_serve = true` is what makes this circle sweepable, and nothing else sets it**
            # (revision 0045; owner 2026-09-14, «which circles the sweep may touch»). A circle an
            # operator makes stays false and is never swept, so the nightly job cannot reach the
            # owner's own circles or a fixture however long they sit untouched.
            circle_id = (
                await session.execute(
                    text("insert into circle (name, self_serve) values (:n, true) returning id"),
                    {"n": name},
                )
            ).scalar_one()
            try:
                # **The invite power, and not the evidence table** (owner 「拆」, 2026-09-16,
                # revision 0047). The person who opened the circle keeps its link; D105's table
                # identifies whose preference moved a place, and at two seats that is everyone.
                member_id, _, key = await grow_seat(
                    session, circle_id, body.nickname, operator=True, evidence=False
                )
            except SeatRefused as refused:
                # A brand-new circle cannot be full and cannot be missing, so anything here is a bug
                # rather than a member's mistake — 500 rather than a member-facing sentence that would
                # be a lie about whose fault it is.
                raise HTTPException(status_code=500, detail=refused.reason) from None
            # **The creator is the host (房主)** (owner 「A」, 2026-10-09, revision 0049): stored on the
            # circle, so the role can pass to another seat without touching anyone's key.
            await session.execute(text("update circle set host_member_id = :m where id = :c"),
                                  {"m": member_id, "c": circle_id})
            ticket = await _mint_ticket(session, circle_id)
            await session.commit()
    except BaseException:
        _refund_address_day(reserved)
        raise

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
    _refuse_too_long(body.nickname)
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
            raise HTTPException(status_code=410, detail="這個連結換過了，跟開圈子的人要新的。")
        if row.expired:
            # **A different sentence from the revoked one, because the remedy is the same and the
            # reason is not.** A person whose link was replaced knows somebody did something; a
            # person whose link ran out needs to know the link has a life at all, or the next one
            # will sit in the group chat overnight too.
            raise HTTPException(
                status_code=410, detail="這個連結只能用一小時，過期了。跟開圈子的人要新的。"
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


NO_STORE = {"Cache-Control": "no-store"}


@router.post("/{circle_id}/join/preview")
async def preview_join(circle_id: int, body: TicketCheck, response: Response) -> dict:
    """What the join page may say before the person joins: the circle's name and its creator.

    *UX items 1 and 2, 2026-10-07 — my proposal narrowed to frontend's terms, which only remove.*
    **No credential and no write.** It reads the ticket's row, the circle's name and one nickname;
    nothing is inserted or updated, so opening the page N times leaves every count where it was —
    the integration test asserts that. A ticket is multi-use until its hour or the cap, so a preview
    consumes nothing either way.

    **What it leaks, and to whom.** Only to a holder of a LIVE ticket, and only a subset of what that
    ticket already buys: a holder can join and then read every nickname (`GET /members`). The
    preview gives the name and one nickname — no seat count, no list, no id.

    **The ticket rides in the body and the answer is `no-store`**, the same exposure argument as
    `/join-ticket/check` above: the proxy's access log writes the visitor's address beside the
    request line, so a seat-granting secret may not travel in a path or a query, and a cached
    answer would outlive the hour the ticket has.

    **«Creator» is honestly the creator, not the sender.** A ticket belongs to a circle, not to the
    person who forwarded it, so the server never knows who sent the link. The creator is the seat
    whose invite-power key (0047's `operator`) was minted **in the circle's own creating
    transaction** — `device_secret.created_at = circle.created_at`, both `now()` of one
    transaction (35 of 35 self-serve circles on dev, none ambiguous, 2026-10-08). Not «the first
    operator seat»: once the creator's seat is gone that would name the next one, such as an
    operator principal attached later with `--principal` (the reviewer's catch). So it is `None`
    when that seat is gone, and for a circle made by `upto.issue` rather than this door.
    """
    response.headers.update(NO_STORE)
    digest = sha256(body.ticket.encode("utf-8")).hexdigest()
    async with session_factory()() as session:
        row = (
            await session.execute(
                text("select t.circle_id, c.name from join_ticket t "
                     "join circle c on c.id = t.circle_id "
                     "where t.token_sha256 = :h and t.revoked_at is null "
                     "and (t.expires_at is null or t.expires_at > now())"),
                {"h": digest},
            )
        ).one_or_none()
        if row is None or row.circle_id != circle_id:
            # **One sentence for every dead case, on purpose** (frontend's terms, 2026-10-07).
            # Unlike join's 410/404 split, a replaced ticket, an expired one, an unknown one and a
            # circle that does not exist answer the same status and the same bytes, so `c=` cannot
            # be walked to learn which circles exist. The sentence is frontend's, rendered verbatim,
            # stating rather than advising (D20). **Written inline, never through a constant:**
            # `server_copy.py` reads only literals inside `detail=`, and a sentence it cannot see is
            # one the font gate cannot check.
            raise HTTPException(
                status_code=404,
                detail="這條連結不能用了：可能已經過期（連結只有一小時）、被換掉，或沒有複製完整。"
                       "開圈子的人可以給一條新的。",
                headers=NO_STORE,
            )
        creator = await creator_nickname(session, circle_id)
    return {"circle_name": row.name, "creator_nickname": creator}


async def host_of(session, circle_id: int) -> int | None:
    """The circle's host seat (revision 0049), or `None` — a CLI-made circle, or every seat gone."""
    return (
        await session.execute(text("select host_member_id from circle where id = :c"),
                              {"c": circle_id})
    ).scalar_one_or_none()


async def creator_nickname(session, circle_id: int) -> str | None:
    """The real creator's nickname: the seat whose operator key was minted in the circle's own
    creating transaction, `None` once that seat has left or when there never was one (a circle made
    by the CLI). One query for the two readers — the join preview and the member list — so they
    cannot name different people."""
    return (
        await session.execute(
            text("select m.nickname from member m "
                 "join device_secret d on d.principal_id = m.principal_id "
                 "join circle c on c.id = m.circle_id "
                 "where m.circle_id = :c and not m.has_left and d.operator and d.created_at = c.created_at "
                 "order by m.id limit 1"),
            {"c": circle_id},
        )
    ).scalar_one_or_none()


@router.post("/{circle_id}/join-ticket", status_code=201)
async def reissue_ticket(circle_id: int, request: Request) -> dict:
    """A new link; the old one stops working. Operator credential only.

    **It does not remove a seat that has already joined**, and that is stated rather than assumed:
    the stranger stops being able to invite others, not to be there. Eject is a separate ruling with
    a data-deletion half (D42, H22) and is deliberately out of this candidate.
    """
    async with session_factory()() as session:
        caller, is_operator, _ = await resolve_credential(session, request, circle_id)
        if not (is_operator or await host_of(session, circle_id) == caller):
            # The host, or a CLI operator credential (D105: that role rides the presented secret).
            raise HTTPException(status_code=403, detail="只有房主可以換連結。")
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
        caller, is_operator, _ = await resolve_credential(session, request, circle_id)
        if not (is_operator or await host_of(session, circle_id) == caller):
            raise HTTPException(status_code=403, detail="只有房主可以看連結。")
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
        caller, is_operator, _ = await resolve_credential(session, request, circle_id)
        if not (is_operator or await host_of(session, circle_id) == caller):
            raise HTTPException(status_code=403, detail="只有房主可以看連結。")
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


@router.post("/{circle_id}/leave", status_code=204, response_class=Response)
async def leave_circle(circle_id: int, request: Request) -> Response:
    """Give the seat back: the old key, no body, 204 whatever happened (owner 「可以」, 2026-10-08).

    *Agreed with frontend: a device that moves to another circle fires this with its OLD key after
    the new join has succeeded, so a failed join never costs the old seat.*

    **What leaving does.** It sets `member.has_left` (0048) and deletes the seat's preferences that no
    round still needs (below). The seat stops counting
    toward D110's cap, leaves `GET /members`, is not pinned into a new round, and its key stops
    resolving in THIS circle (`auth.credential_for`) — while every past round, roll, trip and
    proposal keeps pointing at the row, and the principal and its key are untouched, because one
    principal can sit in other circles.

    **204 in every case** — a seat left, a seat already left, an unknown key, another circle's key,
    no key at all. The answer says nothing about which, so the endpoint cannot be used to test a
    key or a circle. The creator may leave too: the invite power goes with the seat, and a new link
    then needs the operator CLI.
    """
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        async with session_factory()() as session:
            found = await credential_for(session, header[7:].strip(), circle_id)
            if found is not None:
                await release_seat(session, circle_id, found[0], "seat_left")
                await session.commit()
    return Response(status_code=204)


async def release_seat(session, circle_id: int, member_id: int, event: str) -> None:
    """A seat leaves the circle — on its own (`seat_left`) or removed by the host (`seat_removed`).

    **The open round is locked first**, the same row a submit locks, so a leave and a last submit
    cannot both read «one missing». Then the seat goes, the event names it — its own stream ends on
    that event (`live.stream`), because a stream authorised at connect would otherwise keep
    delivering the circle to a seat that is no longer in it — and the count is re-read: if every
    pinned seat still here has submitted, the round closes in this request (owner's game room,
    2026-10-09). An empty pool at that moment keeps the round open and the leave still lands.

    **A host who goes hands the role on** (owner, 2026-10-09): to the earliest-joined seat still
    here — the lowest member id, because seats are numbered as they join — with a `host_changed`
    event; `None` when nobody is left. The circle row is locked first, so two seats leaving at once
    cannot both read themselves as the heir's predecessor.
    """
    host = (
        await session.execute(
            text("select host_member_id from circle where id = :c for update"), {"c": circle_id})
    ).scalar_one_or_none()
    open_round = (
        await session.execute(
            text("select id from round where circle_id = :c and status = 'open'"),
            {"c": circle_id},
        )
    ).scalar_one_or_none()
    round_row = None
    if open_round is not None:
        round_row = (
            await session.execute(text(ROUND_FOR_CLOSE), {"r": open_round})
        ).one_or_none()
    await session.execute(
        text("update member set has_left = true where id = :m"), {"m": member_id})
    # **The seat's preferences go with it** (owner 「刪掉」, 2026-10-08, on the
    # reviewer's report: kept preferences of a left seat would otherwise sit stored for
    # ever while counting nowhere). Two kinds stay, because a round's story needs them:
    # a version a closed round's contribution pinned (D24/D25 — the foreign key refuses
    # the delete anyway), and every preference of a seat an OPEN round has pinned, whose
    # roll will still read them. Only this member's rows; nobody else's are touched.
    await session.execute(
        text("delete from preference p where p.member_id = :m "
             "and not exists (select 1 from weight_contribution w "
             "                 where w.preference_id = p.id) "
             "and not exists (select 1 from round r where r.circle_id = :c "
             "                 and r.status = 'open' and :m = any(r.seat_ids))"),
        {"m": member_id, "c": circle_id})
    await publish(session, circle_id, {"type": event, "member_id": member_id})
    if host == member_id:
        heir = (
            await session.execute(
                text("select id from member where circle_id = :c and not has_left "
                     "order by id limit 1"), {"c": circle_id})
        ).scalar_one_or_none()
        await session.execute(text("update circle set host_member_id = :h where id = :c"),
                              {"h": heir, "c": circle_id})
        await publish(session, circle_id, {"type": "host_changed", "member_id": heir})
    if round_row is None or round_row.status != "open" or member_id not in (round_row.seat_ids or []):
        return
    submitted, required = await submit_state(session, open_round, circle_id, round_row.seat_ids)
    await publish(session, circle_id,
                  {"type": "submitted", "round_id": open_round, "submitted": submitted,
                   "required": required})
    if required == 0:
        # **Every pinned seat has left: the round is void** (owner, 2026-10-09 — «the invitation
        # lapsed»; revision 0050). Not closed — nobody invited to it is here to be shown a result —
        # and not left open, because nothing could ever complete it and the circle could open no
        # other round. The row and its seed commitment stay; there is no reveal.
        await session.execute(
            text("update round set status = 'void', closed_at = now() where id = :r"),
            {"r": open_round})
        # The left seats' preferences the open round was keeping for its roll: the roll will never
        # come, so they go now, as the close would have removed them.
        await session.execute(
            text("delete from preference p where p.member_id = any(:seats) "
                 "and exists (select 1 from member m where m.id = p.member_id and m.has_left) "
                 "and not exists (select 1 from weight_contribution w where w.preference_id = p.id)"),
            {"seats": list(round_row.seat_ids or [])})
        await publish(session, circle_id, {"type": "voided", "round_id": open_round})
    elif len(submitted) == required:
        try:
            async with session.begin_nested():
                await close_round(session, open_round, round_row, None)
        except PoolSwept:
            pass


@router.delete("/{circle_id}/members/{member_id}", status_code=204, response_class=Response)
async def remove_member(circle_id: int, member_id: int, request: Request) -> Response:
    """The host asks a seat to leave — for a seat that will never come back (owner 「A」, 2026-10-09).

    A lost device cannot leave by itself, and the round waits for every pinned seat, so without
    this one seat could hold a circle's round open for ever. The effect is exactly that seat
    leaving (`release_seat`): the same flag, the same re-count and close, and `seat_removed` ends
    the removed seat's own stream.

    **Refused, each with its own sentence:** a caller who is not the host (403); the host's own
    seat (409 — the host leaves through `leave`); a seat that has already submitted in the open
    round (409 — it came back and chose, so it is not the seat this exists for). A seat that is
    not in this circle, or has already left, answers 404 the same way.
    """
    async with session_factory()() as session:
        caller, _is_operator, _ = await resolve_credential(session, request, circle_id)
        host = (
            await session.execute(
                text("select host_member_id from circle where id = :c for update"),
                {"c": circle_id})
        ).scalar_one_or_none()
        if host is None or caller != host:
            raise HTTPException(status_code=403, detail="只有房主可以請人離開。")
        if member_id == host:
            raise HTTPException(status_code=409, detail="房主不能請自己離開。要離開，請用離開圈子。")
        present = (
            await session.execute(
                text("select 1 from member where id = :m and circle_id = :c and not has_left"),
                {"m": member_id, "c": circle_id})
        ).scalar_one_or_none()
        if present is None:
            raise HTTPException(status_code=404, detail="這個人已經不在圈子裡了。")
        # **The open round is locked before the «already submitted» read** (the reviewer's should,
        # 2026-10-09): read unlocked, a submit could land between this check and the removal.
        # Circle first, then round — the same order `release_seat` takes.
        await session.execute(
            text("select id from round where circle_id = :c and status = 'open' for update"),
            {"c": circle_id})
        submitted = (
            await session.execute(
                text("select 1 from member_roll mr join round r on r.id = mr.round_id "
                     "where r.circle_id = :c and r.status = 'open' and mr.member_id = :m"),
                {"c": circle_id, "m": member_id})
        ).scalar_one_or_none()
        if submitted is not None:
            raise HTTPException(status_code=409, detail="這個人已經提交了，不能請對方離開。")
        await release_seat(session, circle_id, member_id, "seat_removed")
        await session.commit()
    return Response(status_code=204)


@router.get("/{circle_id}/members")
async def circle_members(circle_id: int, request: Request) -> dict:
    """Who is at the table — the circle's name, then nicknames in the order they joined.

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

    **`name` since 2026-10-08 (frontend, on the evaluator's cold reader: the home never said which
    circle you were in).** It widens nothing: a stranger holding a live ticket already reads it on
    `/join/preview`, and this reader is a seated member.

    **`creator_nickname` since 2026-10-08 (frontend, on the evaluator's finding: a member who did not
    create the circle could not tell who can make an invite link).** The preview's own rule and key,
    through the same query; it widens nothing for the same reason `name` does.

    **`your_nickname` since 2026-10-08 (frontend, on the evaluator's finding: both readers asked
    «am I 小明?»).** The caller's own seat, read from the credential, so it names nobody the caller
    did not already know; with duplicate nicknames it is the only way the page can say which one
    is you.
    """
    async with session_factory()() as session:
        member_id, _, _ = await resolve_credential(session, request, circle_id)
        yours = (
            await session.execute(text("select nickname from member where id = :m"), {"m": member_id})
        ).scalar_one()
        name = (
            await session.execute(text("select name from circle where id = :c"), {"c": circle_id})
        ).scalar_one()
        rows = (
            await session.execute(
                text("select id, nickname from member where circle_id = :c and not has_left order by id"),
                {"c": circle_id},
            )
        ).all()
        creator = await creator_nickname(session, circle_id)
        host = await host_of(session, circle_id)
    # **`is_host` per row and `you_are_host`, never the host's id** (frontend, 2026-10-09): the list
    # stays id-free, and a flag on the row marks the host even when two seats share a nickname.
    return {"name": name,
            "members": [{"nickname": r.nickname, "is_host": r.id == host} for r in rows],
            "seats": len(rows), "cap": SEAT_CAP, "creator_nickname": creator,
            "your_nickname": yours, "you_are_host": host is not None and host == member_id}
