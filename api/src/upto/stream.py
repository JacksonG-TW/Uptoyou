"""Ticket 20 — the circle's live channel, carried by the database so N instances share it.

D52 keys the stream on the circle, so an event is addressed by circle id and every open stream on
that circle receives it. **Until 2026-09-11 the broker was a dict of `asyncio.Queue` in this
process**, which was correct for one instance and silently wrong for two: a member served by
instance A would never hear an event published on B — five friends, three on one and two on the
other, and the two would sit on a round that had already been decided. The ceiling was deliberate
and documented; the owner's 「9/10改成可以長成多台」 is what moved it, and 「Notify」 is the ruling.

**How it works now.** `publish()` issues `pg_notify` on one channel, `upto_stream`, with the circle
id inside the payload; every instance holds one `LISTEN` connection and fans out to its own local
subscribers. One channel rather than one per circle, because a channel per circle means
`LISTEN`/`UNLISTEN` churn on every subscribe and a connection reconfigured as members come and go —
the filter is the same work done where it is cheap.

**Three facts measured on 2026-09-11 rather than assumed, because each one decides something:**

* **A notification is delivered if and only if its transaction commits.** Probed directly: a
  `pg_notify` in a committing transaction arrives, one in a transaction that rolls back **never
  does**. That is strictly better than what this module used to do — the old publish ran *after*
  `session.commit()`, so a crash between the two lost the event, and an event for a write that was
  rolled back afterwards was possible. It is also a trap for the next person adding a publisher:
  **if you call this inside a transaction that will not commit, nothing is sent.** See
  `transactional=False` below for the one place that is deliberate.
* **The payload ceiling is 7,999 bytes** (`MAX_PAYLOAD`), and 8,000 is **refused outright** with
  `InvalidParameterValueError: payload string too long` rather than truncated — a loud failure at
  the write, which is the better of the two. The largest event this product sends is the closed
  round at **717 bytes** measured on a real roll, so the margin is wide; `test_stream_payload`
  builds a round at D110's ruled maximum and asserts it stays under.
* **Ordering and at-most-once.** `NOTIFY` gives no history: an instance that is restarting misses
  what it did not hear. D56 makes the snapshot the stream's first event, so a missed notification
  costs a reconnect exactly what a network blip costs — which is why this is enough here and would
  not be in a product without that snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from contextlib import asynccontextmanager

from sqlalchemy import text

CHANNEL = "upto_stream"

#: Postgres refuses a longer payload outright (measured 2026-09-11: 7,999 delivered, 8,000
#: refused). Asserted from below by the ten-seat test rather than trusted as a number.
MAX_PAYLOAD = 7999

_log = logging.getLogger(__name__)

#: Local subscribers on THIS instance. The dict is no longer the broker — it is the last hop,
#: after the notification has crossed from whichever instance published it.
_subscribers: dict[int, set[asyncio.Queue]] = defaultdict(set)


def _envelope(circle_id: int, event: dict) -> str:
    payload = json.dumps({"circle_id": circle_id, "event": event}, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_PAYLOAD:
        # Refused here rather than by the database, so the message names the product's own limit
        # and the event that broke it. The fallback if this is ever hit in earnest is on the
        # record: notify the circle id alone (36 bytes) and let each instance rebuild the event.
        raise ValueError(
            "stream payload is {} bytes and the ceiling is {} — the event was {!r}".format(
                len(payload.encode("utf-8")), MAX_PAYLOAD, event.get("type")
            )
        )
    return payload


async def publish(session, circle_id: int, event: dict, transactional: bool = True) -> None:
    """Hand one event to every open stream on this circle, on every instance.

    **`transactional=True` is the default and the right answer for a write.** The notification
    rides the caller's transaction and is delivered only if that transaction commits, so an event
    for a write that rolled back cannot exist. Call it *before* the commit, not after.

    **`transactional=False` exists for exactly one caller and D37 is the reason.** `pool_swept`
    is published on a path that deliberately raises 409 and rolls back — «four people staring at a
    screen that did nothing is the silence §3.0 is built against». A transactional notify there
    would be swallowed by the rollback and the other four members would learn nothing, so that one
    event is sent on its own short-lived connection, unconditionally. The event says «the pool was
    empty», which is true whatever happens to the request that discovered it. Ruled 2026-09-11
    after the swallow was measured; the two rejected branches — committing the sweep (it would
    leave a `member_roll` row D108's seat list reads, so it buys uniformity by editing a fact) and
    accepting the loss (D37 forbids it) — are in the decision log.
    """
    payload = _envelope(circle_id, event)
    if transactional:
        await session.execute(text("select pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})
        return
    # Its own connection, so the caller's rollback cannot take it with it.
    from .db import session_factory  # noqa: PLC0415 — avoids a cycle at import time

    async with session_factory()() as own:
        await own.execute(text("select pg_notify(:c, :p)"), {"c": CHANNEL, "p": payload})
        await own.commit()


def deliver(payload: str) -> None:
    """One notification in, every local subscriber on that circle served. Never raises.

    The listener calls this from a driver callback, where an exception would be swallowed by
    asyncpg and the connection left in an unclear state — so a malformed payload is logged and
    dropped rather than allowed to take the listener down with it. D56's snapshot is what makes
    that survivable: a client that missed an event recovers on its next reconnect.
    """
    try:
        body = json.loads(payload)
        circle_id, event = int(body["circle_id"]), body["event"]
    except Exception:  # noqa: BLE001 — any malformed payload is the same problem
        _log.warning("stream: dropped a notification this instance could not read")
        return
    for queue in _subscribers[circle_id]:
        queue.put_nowait(event)


@asynccontextmanager
async def subscribe(circle_id: int):
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers[circle_id].add(queue)
    try:
        yield queue
    finally:
        _subscribers[circle_id].discard(queue)


@asynccontextmanager
async def listening(url: str | None = None):
    """One `LISTEN` connection for this instance, held for the process's life.

    **Raw asyncpg rather than the SQLAlchemy session**, because `LISTEN` is a connection-scoped
    state that must outlive every request while sessions are borrowed from a pool and returned —
    a listener on a pooled connection stops listening the moment that connection is recycled.

    **A failure here must not stop the API from serving.** If the listener cannot be established
    the product still answers every request; what it loses is the live stream, and D56's snapshot
    means a member who reloads still sees the truth. So this logs and continues rather than
    refusing to start — a stack that will not boot because a notification channel is unavailable
    is a worse outcome than one that boots quiet.
    """
    import asyncpg  # noqa: PLC0415 — the driver is already a dependency; imported here to keep
    #                                  this module importable by tests that never listen.
    from .db import database_url  # noqa: PLC0415

    dsn = (url or database_url()).replace("postgresql+asyncpg://", "postgresql://")
    connection = None
    try:
        connection = await asyncpg.connect(dsn)
        await connection.add_listener(CHANNEL, lambda _c, _pid, _ch, payload: deliver(payload))
        _log.info("stream: listening on %s", CHANNEL)
    except Exception as failure:  # noqa: BLE001 — any transport failure is the same outcome here
        _log.warning("stream: no listener (%s) — this instance serves, but its members will "
                     "not receive live events until it restarts", failure)
        connection = None
    try:
        yield
    finally:
        if connection is not None:
            await connection.close()
