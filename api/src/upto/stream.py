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
from datetime import datetime, timezone

from sqlalchemy import text

CHANNEL = "upto_stream"

#: The listening connection names itself in `pg_stat_activity`. **Not cosmetic:** it is how an
#: operator tells this connection from the pool's, and how the listener test finds the backend to
#: kill — without it both have to be guessed at from `query`, which the keepalive overwrites.
APPLICATION_NAME = "upto-stream-listener"

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


#: The supervisor's backoff, bounded at both ends. One second so a `pg_terminate_backend` or a
#: `docker compose up -d --no-deps db` is recovered from before anybody notices; thirty so a
#: database that is genuinely gone is not hammered by every instance in the group at once.
_BACKOFF_FIRST, _BACKOFF_MAX = 1.0, 30.0

#: How often the listening connection is asked whether it is really still there. asyncpg's
#: termination callback covers the connection that is *closed*; it cannot cover one that is
#: silently black-holed, where the socket stays open and nothing ever arrives — and that failure
#: is indistinguishable from a quiet circle, which is precisely the invisibility this supervisor
#: exists to remove. One `select 1` a quarter-minute is the cheapest question that has an answer.
_KEEPALIVE = 15.0

#: How long `listening()` waits for the first connection before letting the app serve. Bounded,
#: because a database that is slow to accept must not hold the whole process at startup — the
#: supervisor keeps trying behind a `/health` that says so.
_FIRST_CONNECT_WAIT = 10.0

_status: dict = {"up": False, "down_since": None, "reason": "not started"}


def listener_status() -> dict:
    """What `/health` publishes about this instance's ear. Never raises, never blocks.

    **The state is reported, not inferred from a failed publish.** A publish that fails says the
    database is unreachable; a listener that has died says something narrower and far quieter —
    this instance can still read, write and answer, and its members' screens will simply never
    move again. Those are different failures and only one of them used to be visible.
    """
    if _status["up"]:
        return {"stream_listener": "up"}
    since = _status["down_since"]
    return {"stream_listener": "down since {}".format(since.isoformat() if since else "start"),
            "stream_listener_detail": str(_status["reason"])[:200]}


def listener_is_up() -> bool:
    return bool(_status["up"])


def _mark_up() -> None:
    was_down_since = _status["down_since"]
    _status.update({"up": True, "down_since": None, "reason": None})
    if was_down_since is not None:
        _log.error("stream: listener recovered (it was down since %s)", was_down_since.isoformat())
    else:
        _log.info("stream: listening on %s", CHANNEL)


def _mark_down(reason: str) -> None:
    if _status["up"] or _status["down_since"] is None:
        _status["down_since"] = datetime.now(timezone.utc)
    _status.update({"up": False, "reason": reason})
    # **Error, not warning, and every time rather than once.** The failure this reports is
    # permanent and silent without it: the stream's 25-second heartbeat is generated locally in
    # the response loop, so a client on a deaf instance keeps receiving keepalives on a screen
    # that will never change again. Nothing else in this process would say a word.
    _log.error("stream: listener is DOWN (%s) — this instance's members receive no live events "
               "until it reconnects", reason)


async def _supervise(dsn: str) -> None:
    """Hold one `LISTEN` connection up for the process's life, reconnecting when it dies.

    **Written 2026-09-11 on the reviewer's report against e82f16d**, which found the shape D112
    is about: the first version connected once, caught only the failure of that first connect, and
    had no path back. A listener that died later — a database restart, `up -d --no-deps db`, a
    `pg_terminate_backend` — left an instance that looked healthy from every angle and delivered
    nothing, for ever, without logging a line.
    """
    import asyncpg  # noqa: PLC0415

    backoff = _BACKOFF_FIRST
    while True:
        connection = None
        died = asyncio.Event()
        try:
            connection = await asyncpg.connect(
                dsn, server_settings={"application_name": APPLICATION_NAME})
            connection.add_termination_listener(lambda _c: died.set())
            await connection.add_listener(CHANNEL, lambda _c, _pid, _ch, p: deliver(p))
            _mark_up()
            backoff = _BACKOFF_FIRST
            while not died.is_set():
                try:
                    await asyncio.wait_for(died.wait(), timeout=_KEEPALIVE)
                except asyncio.TimeoutError:
                    await connection.fetchval("select 1")  # raises when the socket is really gone
            _mark_down("the listening connection was terminated by the server")
        except asyncio.CancelledError:
            raise
        except Exception as failure:  # noqa: BLE001 — every transport failure has one answer here
            _mark_down("{}: {}".format(type(failure).__name__, failure))
        finally:
            if connection is not None:
                try:
                    await connection.close(timeout=5)
                except Exception:  # noqa: BLE001 — closing a dead connection is not a new problem
                    pass
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _BACKOFF_MAX)


@asynccontextmanager
async def listening(url: str | None = None):
    """This instance's ear, supervised, for the process's life.

    **Raw asyncpg rather than the SQLAlchemy session**, because `LISTEN` is connection-scoped state
    that must outlive every request while sessions are borrowed from a pool and returned — a
    listener on a pooled connection stops listening the moment that connection is recycled.

    **A failure here still does not stop the API from serving, and that has not changed** — every
    request is answered, and D56's snapshot means a member who reloads sees the truth. **What
    changed on 2026-09-11 is that it is no longer silent:** `/health` reports the listener's state
    and answers non-200 while it is down, so `--wait`, the proxy's gate and a load balancer all see
    a deaf instance and stop sending members to it. Serving reads while telling the truth about
    what is broken is the ruled behaviour; serving reads while looking perfect was the defect.
    """
    from .db import database_url  # noqa: PLC0415

    dsn = (url or database_url()).replace("postgresql+asyncpg://", "postgresql://")
    supervisor = asyncio.ensure_future(_supervise(dsn))
    deadline = asyncio.get_event_loop().time() + _FIRST_CONNECT_WAIT
    while not _status["up"] and asyncio.get_event_loop().time() < deadline:
        if supervisor.done():
            break
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        supervisor.cancel()
        try:
            await supervisor
        except asyncio.CancelledError:
            pass
