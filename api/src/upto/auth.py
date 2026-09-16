"""D67 — a bearer token resolves to a member, or the write does not happen.

The rule this module carries: **authentication references only `principal`, the product
domain references only `member`, and they meet at `member.principal_id`** (D12). So the
resolution is one join — hash the token, find the principal that owns the secret, find that
principal's seat in the circle the request names. A token the table does not know and a
principal with no seat in that circle produce the same `None`, because the caller learns
nothing about which half failed (H3's instinct: the error must not be a probe).

The token is hashed with SHA-256 before it touches a query, so the plaintext exists only in
the request. D12 rules the fast hash and why.
"""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import text


async def credential_for(session, token: str, circle_id: int):
    """`(member_id, operator, evidence)` for this token in this circle, or `None`. The D12 join, once.

    **The role comes from the secret and not from the person (D105).** `device_secret.operator` is
    read in the same query that resolves the seat, so a caller cannot be an operator by any route
    other than presenting the credential that was issued as one — there is no parameter, and nothing
    on `principal` to read.

    One principal may hold two secrets with different roles, so this returns the role **of the token
    presented**. "Is this person an operator" is deliberately not a question this can answer.

    **Two flags since 0047 (owner 「拆」, 2026-09-16), and they are unrelated powers.** `operator` is
    the invite power — minting and reading the circle's join link. `evidence` is D105's evidence
    table in the reveal payload. One boolean used to grant both, which handed the self-serve
    creator a privilege nobody ruled. A caller can hold either, both or neither.
    """
    digest = sha256(token.encode("utf-8")).hexdigest()
    row = (
        await session.execute(
            text(
                "select m.id as member_id, ds.operator as operator, ds.evidence as evidence "
                "from device_secret ds "
                "join member m on m.principal_id = ds.principal_id "
                "where ds.secret_sha256 = :digest and m.circle_id = :circle"
            ),
            {"digest": digest, "circle": circle_id},
        )
    ).one_or_none()
    return None if row is None else (row.member_id, bool(row.operator), bool(row.evidence))


async def member_for(session, token: str, circle_id: int) -> int | None:
    """The caller's member id in this circle, or None. The only crossing is the D12 join."""
    found = await credential_for(session, token, circle_id)
    return None if found is None else found[0]
