#!/usr/bin/env python3
"""Kill the API's LISTEN connection from the database side. It must say so, then heal.

*Written 2026-09-11 with candidate 15, on the reviewer's report against e82f16d.* The first
version of the multi-instance stream connected its listener once, caught only the failure of that
first connect, and had no path back. **The failure that leaves is D112's exact shape with the one
symptom removed.** A listener that dies later — a database restart, `up -d --no-deps db`, a
`pg_terminate_backend` — leaves an instance that answers every request correctly, logs nothing,
and moves nobody's screen again; and because the stream's 25-second heartbeat is generated locally
in the response loop, the connection does not even fall quiet. Permanent, invisible, and
recoverable only by somebody noticing.

**So this file does the one thing that proves the fix: it kills the connection for real.** Nothing
is stubbed. A backend is terminated from another session, and what is asserted is the state the
outside world can see — `/health` stops answering 200, and then an event published afterwards
arrives at a member's stream, which is the half a health flip alone would not prove.

    docker compose run --rm tests python /srv/tests/test_stream_listener_integration.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_DB = "upto_listener_check"
PORT = 8905

FAILURES: list[str] = []


def check(label: str, ok: bool, detail=None) -> None:
    print(("ok   " if ok else "FAIL ") + label + ("" if ok or detail is None else f" {detail!r}"))
    if not ok:
        FAILURES.append(label)


async def admin_sql(url: str, statement: str, params: dict | None = None):
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(statement), params or {})
            return result.scalars().all() if result.returns_rows else None
    finally:
        await engine.dispose()


async def health(client) -> tuple[int, dict]:
    answer = await client.get(f"http://127.0.0.1:{PORT}/health", timeout=5)
    try:
        return answer.status_code, answer.json()
    except Exception:  # noqa: BLE001
        return answer.status_code, {}


async def until(predicate, seconds: float, step: float = 0.2):
    """Poll a coroutine predicate until it holds or the budget runs out. Returns whether it held.

    **A bounded wait, never a fixed sleep.** «Flip within a second or two» is the requirement, so
    the assertion has to be about a deadline rather than about how long this file chose to nap.
    """
    remaining = seconds
    while remaining > 0:
        if await predicate():
            return True
        await asyncio.sleep(step)
        remaining -= step
    return False


async def listener_pid(test_url: str, application_name: str) -> int | None:
    pids = await admin_sql(
        test_url,
        "select pid from pg_stat_activity where application_name = :a and pid <> pg_backend_pid()",
        {"a": application_name})
    return pids[0] if pids else None


async def scenario(test_url: str) -> None:
    import httpx  # noqa: PLC0415

    from upto.stream import APPLICATION_NAME, _envelope  # noqa: PLC0415

    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        circle = await session.scalar(
            text("insert into circle (name) values ('listener') returning id"))
        principal = await session.scalar(text("insert into principal default values returning id"))
        await session.execute(
            text("insert into member (circle_id, principal_id, nickname) values (:c, :p, 'Amy')"),
            {"c": circle, "p": principal})
        token = secrets.token_urlsafe(32)
        await session.execute(
            text("insert into device_secret (principal_id, secret_sha256) values (:p, :s)"),
            {"p": principal, "s": hashlib.sha256(token.encode()).hexdigest()})
        await session.commit()
    await engine.dispose()

    async with httpx.AsyncClient() as client:
        code, body = await health(client)
        check("a healthy instance answers 200", code == 200, (code, body))
        check("and says its listener is up", body.get("stream_listener") == "up", body)

        # **The connection is found by name, not guessed at.** `application_name` is set by the
        # listener itself; matching on `query like 'LISTEN%'` would work only until the keepalive
        # overwrote it, which is a test that passes for fifteen seconds.
        pid = await listener_pid(test_url, APPLICATION_NAME)
        check("the listening backend is identifiable in pg_stat_activity", pid is not None, pid)
        if pid is None:
            return

        await admin_sql(test_url, "select pg_terminate_backend(:p)", {"p": pid})

        async def degraded():
            code_, body_ = await health(client)
            return code_ != 200 and body_.get("status") != "ok"

        # Two seconds is the requirement, not an approximation of one.
        check("within two seconds of the kill, /health no longer answers 200 with status ok",
              await until(degraded, 2.0), (await health(client)))
        code, body = await health(client)
        check("and it names the listener as the reason",
              str(body.get("stream_listener", "")).startswith("down since"), body)
        # It must still answer — the ruled behaviour is «serving and honest», not «refusing».
        check("while the API is still serving reads", code == 503 and "database" in body, body)

        async def recovered():
            code_, body_ = await health(client)
            return code_ == 200 and body_.get("stream_listener") == "up"

        # The first backoff step is one second, so ten is a wide margin rather than a guess.
        check("and it reconnects on its own within ten seconds", await until(recovered, 10.0),
              (await health(client)))

        new_pid = await listener_pid(test_url, APPLICATION_NAME)
        check("on a genuinely new backend, not the corpse", new_pid is not None and new_pid != pid,
              (pid, new_pid))

        # --- the other half: a health flip alone would not prove the ear works ----------------
        heard: list[dict] = []
        headers = {"Authorization": "Bearer " + token}
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{PORT}", timeout=20) as watcher:
            async with watcher.stream("GET", f"/circles/{circle}/stream", headers=headers) as live:
                async def collect():
                    async for line in live.aiter_lines():
                        if line.startswith("data: "):
                            heard.append(json.loads(line[6:]))

                async def heard_past(n: int) -> bool:
                    return len(heard) > n

                reader = asyncio.ensure_future(collect())
                await until(lambda: heard_past(0), 5.0)
                snapshot = len(heard)
                check("the snapshot still arrives after the reconnect, so a silence would mean "
                      "something", snapshot == 1 and heard[0].get("type") == "snapshot", heard)

                await admin_sql(test_url, "select pg_notify(:c, :p)",
                                {"c": "upto_stream",
                                 "p": _envelope(circle, {"type": "after-the-kill"})})
                await until(lambda: heard_past(snapshot), 5.0)
                reader.cancel()
        check("and an event published AFTER the kill reaches the member's stream",
              [e.get("type") for e in heard[snapshot:]] == ["after-the-kill"], heard[snapshot:])

    from upto.db import dispose_all  # noqa: PLC0415
    await dispose_all()


async def main() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB

    await admin_sql(admin_url, f'drop database if exists "{TEST_DB}" with (force)')
    await admin_sql(admin_url, f'create database "{TEST_DB}"')

    server = None
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrated = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv",
                                  env=environment, capture_output=True)
        if migrated.returncode != 0:
            sys.stderr.write(migrated.stderr.decode("utf-8", "replace"))
            return 2
        import httpx  # noqa: PLC0415
        server = subprocess.Popen(
            ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd="/srv/src", env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        async with httpx.AsyncClient() as probe:
            for _ in range(80):
                try:
                    if (await probe.get(f"http://127.0.0.1:{PORT}/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.25)
            else:
                print("FAIL the instance never became healthy", file=sys.stderr)
                return 2
        await scenario(test_url)
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
        await admin_sql(admin_url, f'drop database if exists "{TEST_DB}" with (force)')

    if FAILURES:
        print(f"\n{len(FAILURES)} failing: " + ", ".join(FAILURES), file=sys.stderr)
        return 1
    print("\na listener killed from the database side is reported within two seconds, the instance "
          "keeps serving reads while saying it is degraded, it reconnects on a new backend within "
          "ten, and an event published after the kill reaches a member's stream")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
