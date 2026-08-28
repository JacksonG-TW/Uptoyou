"""Ticket 18 — D74's issuing command: the first secret is an operator's act, printed once.

Run inside the stack:
    docker compose exec api python -m upto.issue <circle_id> <nickname>
    docker compose exec api python -m upto.issue <circle_id> <nickname> --principal <id>

**One transaction issues everything** — a principal (unless ``--principal`` names an existing
one), a `device_secret` row holding only the SHA-256 of the token, and a member seat in the
named circle. Any refusal — unknown circle, unknown principal, a seat that already exists —
rolls the whole act back, so a half-issued device cannot exist.

**The token is printed exactly once and stored nowhere.** The row is its hash (D12: H10's
direct database reader holds sixty-four hex characters that impersonate nobody), so a token
lost is a token reissued, never recovered.

**``--principal`` is D12's returning-device rule made operable:** a person joining a second
circle attaches their existing principal and gains a seat, not a second identity. D12 calls
the silent double-mint the consequence easiest to get wrong precisely because nothing errors;
here the default mints only when no principal is named, and naming one never mints.

**Deliberately absent:** the invite flow — single-use links, the existing-principal attach on
a device that already holds a secret. That is mid-September's work (D74), and until it lands
this command is the only door, which D74 accepts for exactly as long as nobody but the
operator needs one.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from hashlib import sha256

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from upto.db import dispose_all, session_factory

# **A20 / D74 as amended 2026-08-28 — the operator hands over a link, not two strings to retype.**
#
# **The token rides in the URL FRAGMENT and never in the query, and that is the whole design.** A
# fragment is not sent to the server: it never reaches the proxy's access log, never reaches an
# access log's `Referer` on the next request, and never reaches this API at all. A `?k=` would be
# written to disk on every hop between the operator's phone and the member's browser. The device
# screen reads it with `location.hash` and exchanges it for a session; nothing on our side ever
# sees it, which is what makes "printed once and stored nowhere" still true after the link exists.
#
# **The origin is configuration with a working default.** `UPTO_PUBLIC_ORIGIN` is the address a
# member's browser can actually reach — a real deployment's hostname. The default is the proxy's
# own, which is what `UPTO_HTTP_PORT` already serves, so **a fresh clone prints a working link with
# no configuration at all**. The name is in `.env.example` with an empty value on purpose: it
# carries no `PASSWORD`, so CI writes it empty (H58), and the default is what keeps the integration
# tier and `split_boot_check.sh` from failing on a variable they have no reason to set.
PUBLIC_ORIGIN_VAR = "UPTO_PUBLIC_ORIGIN"
DEFAULT_PUBLIC_ORIGIN = "http://localhost:8080"


def invite_link(circle_id: int, token: str) -> str:
    """`<origin>/device#c=<circle_id>&k=<token>` — the fragment carries both.

    The circle id travels in the fragment too, though it is not a secret: keeping the pair together
    means one string to copy, and a link whose query is empty cannot grow a secret into it later by
    somebody adding "just one more parameter".
    """
    import os

    origin = (os.environ.get(PUBLIC_ORIGIN_VAR) or DEFAULT_PUBLIC_ORIGIN).rstrip("/")
    return "{}/device#c={}&k={}".format(origin, circle_id, token)

# **D110 as amended 2026-08-20 (owner-ruled): the supported shape is 10 people.** Ten seats, three
# proposals each, so 30 candidate places against D72's 36 dice outcomes — the apportionment has room
# and D108's decider draw is nowhere near the byte boundary that H48 records.
#
# **Enforced here because this command is the only door.** D74's invite flow does not exist yet, and
# this file's own docstring says so; when it lands, the member-facing refusal belongs there and must
# read from this constant rather than restating the number.
#
# **The cap refuses the next join and deletes nothing — D110's no-migration rule.** A circle that is
# already over it stays exactly as it is: the fixture circle held 291 seats when this landed, every
# one of them written before the rule existed, and removing them is a separate decision nobody has
# made. So this reads "the eleventh seat is refused", not "a circle has at most ten seats".
#
# **Deliberately not a database trigger.** A trigger would hold the rule for every writer including
# a future one, which is the stronger guarantee — and it would need a migration, and D110's ruling
# named the join path. Left as a possible follow-up rather than smuggled in.
SEAT_CAP = 10


async def issue(circle_id: int, nickname: str, principal_id: int | None,
                operator: bool = False) -> int:
    token = secrets.token_urlsafe(32)
    digest = sha256(token.encode("utf-8")).hexdigest()

    Session = session_factory()
    try:
        async with Session() as session:
            circle_name = (
                await session.execute(
                    text("select name from circle where id = :c"), {"c": circle_id}
                )
            ).scalar_one_or_none()
            if circle_name is None:
                print(f"no circle with id {circle_id} — nothing was written", file=sys.stderr)
                return 1

            # **Counted before anything is minted**, so a refusal writes nothing at all — no
            # principal, no device_secret, no token printed. The `IntegrityError` path below rolls
            # back for the same reason; this one never starts.
            seats = (
                await session.execute(
                    text("select count(*) from member where circle_id = :c"), {"c": circle_id}
                )
            ).scalar_one()
            if seats >= SEAT_CAP:
                print(
                    f"circle {circle_id} ({circle_name}) already holds {seats} seats and the "
                    f"supported shape is {SEAT_CAP} — nothing was written. D110: ten people, three "
                    "proposals each. A circle already over the cap keeps its seats; this refuses "
                    "the next one.",
                    file=sys.stderr,
                )
                return 1

            if principal_id is None:
                principal_id = (
                    await session.execute(
                        text("insert into principal default values returning id")
                    )
                ).scalar_one()
            else:
                known = (
                    await session.execute(
                        text("select id from principal where id = :p"), {"p": principal_id}
                    )
                ).scalar_one_or_none()
                if known is None:
                    print(
                        f"no principal with id {principal_id} — nothing was written; omit "
                        "--principal to mint a new one",
                        file=sys.stderr,
                    )
                    return 1

            # **D105: the role is written here and nowhere else.** It rides the secret rather than
            # the person, so it can never arrive as a request parameter and it is revocable on its
            # own — revoking an operator device leaves the seat intact.
            await session.execute(
                text(
                    "insert into device_secret (principal_id, secret_sha256, operator) "
                    "values (:p, :h, :operator)"
                ),
                {"p": principal_id, "h": digest, "operator": operator},
            )
            try:
                member_id = (
                    await session.execute(
                        text(
                            "insert into member (principal_id, circle_id, nickname) "
                            "values (:p, :c, :n) returning id"
                        ),
                        {"p": principal_id, "c": circle_id, "n": nickname},
                    )
                ).scalar_one()
                await session.commit()
            except IntegrityError:
                # UNIQUE (principal_id, circle_id): the principal already holds a seat here.
                # The rollback takes the fresh device_secret with it — one transaction.
                print(
                    f"principal {principal_id} already holds a seat in circle {circle_id} — "
                    "nothing was written",
                    file=sys.stderr,
                )
                return 1
    finally:
        await dispose_all()

    print(f"token: {token}")
    print("(shown once — only its hash is stored, and it cannot be recovered)")
    # The same secret, in the shape a person can actually send. Printed for every path — the
    # `--principal` attach included — because a returning device needs a link exactly as much as a
    # new one does.
    print(f"link: {invite_link(circle_id, token)}")
    print(f"principal: {principal_id}")
    print(f"member: {member_id}")
    print(f"circle: {circle_name}")
    # Said explicitly, because the two devices are indistinguishable afterwards from the outside and
    # the difference is what the holder can see.
    print("role: operator — this device's reveal carries the evidence table (D105)"
          if operator else "role: member")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m upto.issue",
        description="Issue a device secret and a seat in one transaction (D74).",
    )
    parser.add_argument("circle_id", type=int, help="the circle to seat the member in")
    parser.add_argument("nickname", help="the member's nickname inside that circle")
    parser.add_argument(
        "--principal",
        type=int,
        default=None,
        help="attach to this existing principal instead of minting one (D12)",
    )
    parser.add_argument(
        "--operator",
        action="store_true",
        help="issue this device as an operator's: its reveal payload carries the evidence table "
             "(D105). The role belongs to the secret, not the person — the same human is an "
             "ordinary member on any other device, and revoking this one leaves their seat.",
    )
    args = parser.parse_args()
    return asyncio.run(issue(args.circle_id, args.nickname, args.principal, args.operator))


if __name__ == "__main__":
    sys.exit(main())
