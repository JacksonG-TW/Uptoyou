#!/usr/bin/env python3
"""提交 and the host — the game room, through a real uvicorn against a real PostgreSQL.

    docker compose run --rm tests python /srv/tests/test_submit_integration.py

*Owner's rulings of 2026-10-09: 這一餐 ends in 提交; the round waits for every seat with no timer
and nobody starting early; a seat may take its submission back until the last one lands; the
circle's creator is its host (房主), who may remove a seat that will not come back; when the host
leaves the role passes to the earliest-joined seat still there. It builds its own database and
drops it.*

**It drives HTTP and the stream, because the refusals and the pushes ARE the feature.** A closed
round that every device hears about, a stream that ends for a removed seat, and a 409 that keeps a
submitted list as the others are waiting on it are only real at a process boundary.

**The one property it guards hardest: no dice while the round is open.** The round now waits, so
a deciding pair shown beside the visible pool would let a member compute the winner and then take
their submission back to change it.
"""

import asyncio
import json
import os
import subprocess
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
sys.path.insert(0, SRC)

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_submit_check"
PORT = 8908
#: No `/api` prefix: the proxy strips it before forwarding, and this drives uvicorn directly.
BASE = f"http://127.0.0.1:{PORT}"

CHECKS = []


def check(label: str, condition: bool, detail: str = "") -> None:
    CHECKS.append((label, condition, detail))
    print(("  ok   " if condition else "  FAIL ") + label + (f" — {detail}" if detail else ""))


def urls():
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    return head + "/postgres", head + "/" + TEST_DB


def ticket_of(link: str) -> str:
    return dict(part.split("=", 1) for part in link.partition("#")[2].split("&"))["t"]


def bearer(key: str) -> dict:
    return {"Authorization": "Bearer " + key}


class Listener:
    """One device's stream, collected in the background. `ended` is set when the server closes it."""

    def __init__(self, client, circle: int, key: str):
        self.events: list = []
        self.ended = asyncio.Event()
        self._task = asyncio.ensure_future(self._run(client, circle, key))

    async def _run(self, client, circle, key):
        try:
            async with client.stream("GET", f"{BASE}/circles/{circle}/stream",
                                     headers=bearer(key), timeout=None) as live:
                async for line in live.aiter_lines():
                    if line.startswith("data: "):
                        self.events.append(json.loads(line[6:]))
        except Exception:  # noqa: BLE001 — a cancelled or cut stream is just «ended»
            pass
        finally:
            self.ended.set()

    async def wait_for(self, kind: str, seconds: float = 8.0) -> dict | None:
        for _ in range(int(seconds * 10)):
            for event in self.events:
                if event.get("type") == kind:
                    return event
            await asyncio.sleep(0.1)
        return None

    def cancel(self):
        self._task.cancel()


async def scenario(test_url: str) -> None:
    import httpx  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with httpx.AsyncClient(timeout=20) as client:
        # ---- three seats: the host and two friends ------------------------------------------
        made = (await client.post(BASE + "/circles",
                                  json={"name": "週五晚餐", "nickname": "房主小美"})).json()
        circle, H, host_id = made["circle_id"], made["key"], made["member_id"]
        ticket = ticket_of(made["join_link"])
        seats = {}
        for nick in ("阿明", "阿華"):
            joined = (await client.post(f"{BASE}/circles/{circle}/join",
                                        json={"ticket": ticket, "nickname": nick})).json()
            seats[nick] = (joined["member_id"], joined["key"])
        (ming_id, M), (hua_id, W) = seats["阿明"], seats["阿華"]

        async with Session() as session:
            stored_host = (await session.execute(
                text("select host_member_id from circle where id = :c"), {"c": circle})).scalar_one()
        check("the creator's seat is the host, stored on the circle (0049)", stored_host == host_id,
              f"{stored_host} vs {host_id}")

        opened = await client.post(f"{BASE}/circles/{circle}/rounds", json={}, headers=bearer(H))
        rid = opened.json()["round_id"]
        for shop in ("巷口麵店", "轉角咖哩"):
            place = (await client.post(f"{BASE}/circles/{circle}/places", json={"name": shop},
                                       headers=bearer(H))).json()["place_id"]
            await client.post(f"{BASE}/rounds/{rid}/proposals", json={"place_id": place},
                              headers=bearer(H))

        host_view = Listener(client, circle, H)
        hua_view = Listener(client, circle, W)
        snap = await host_view.wait_for("snapshot")
        check("the snapshot names the reader's own seat and the host",
              snap is not None and snap.get("me") == host_id and snap.get("host") == host_id,
              str({k: (snap or {}).get(k) for k in ("me", "host")}))
        hua_snap = await hua_view.wait_for("snapshot")
        check("and another reader's `me` is that reader's own seat",
              hua_snap is not None and hua_snap.get("me") == hua_id and hua_snap.get("host") == host_id)

        # ---- submit, the locked list, and taking it back ------------------------------------
        first = await client.post(f"{BASE}/rounds/{rid}/submit", headers=bearer(H))
        body = first.json()
        check("the first submit leaves the round open and reports the count",
              first.status_code == 200 and body.get("status") == "open"
              and body.get("submitted") == [host_id] and body.get("required") == 3, first.text)
        heard = await host_view.wait_for("submitted")
        check("and every device hears the count", heard is not None and heard.get("required") == 3, heard)

        locked = await client.post(f"{BASE}/rounds/{rid}/proposals", json={"place_id": 1},
                                   headers=bearer(H))
        check("a submitted seat cannot propose — its list is what the others wait on",
              locked.status_code == 409 and "先收回提交" in locked.text, locked.text)
        pref = await client.post(f"{BASE}/circles/{circle}/preferences", headers=bearer(H),
                                 json={"kind": "avoid_category", "value": "火鍋",
                                       "stance": "avoid", "persist": True})
        check("nor change a preference", pref.status_code == 409 and "先收回提交" in pref.text,
              pref.text)

        back = await client.delete(f"{BASE}/rounds/{rid}/submit", headers=bearer(H))
        check("taking it back is allowed while the round is open",
              back.status_code == 200 and back.json().get("submitted") == [], back.text)
        pref2 = await client.post(f"{BASE}/circles/{circle}/preferences", headers=bearer(H),
                                  json={"kind": "avoid_category", "value": "火鍋",
                                        "stance": "avoid", "persist": True})
        check("and unlocks the list", pref2.status_code == 204, pref2.status_code)

        await client.post(f"{BASE}/rounds/{rid}/submit", headers=bearer(H))
        await client.post(f"{BASE}/rounds/{rid}/submit", headers=bearer(M))

        # **The guard this file exists for.** Two of three submitted, so if any pair were on the
        # wire it would be now.
        late = Listener(client, circle, M)
        snap2 = await late.wait_for("snapshot")
        rolls = ((snap2 or {}).get("open_round") or {}).get("rolls") or []
        check("while the round is open, no seat shows dice — submitted or not",
              len(rolls) == 3 and all(r["die1"] is None and r["die2"] is None for r in rolls), rolls)
        check("each seat carries `submitted` and `left` instead",
              sorted((r["member_id"], r["submitted"], r["left"]) for r in rolls)
              == sorted([(host_id, True, False), (ming_id, True, False), (hua_id, False, False)]),
              rolls)
        late.cancel()

        # ---- the host's remove ---------------------------------------------------------------
        not_host = await client.delete(f"{BASE}/circles/{circle}/members/{hua_id}", headers=bearer(M))
        check("a seat that is not the host cannot remove anyone", not_host.status_code == 403,
              not_host.text)
        chosen = await client.delete(f"{BASE}/circles/{circle}/members/{ming_id}", headers=bearer(H))
        check("the host cannot remove a seat that has already submitted",
              chosen.status_code == 409, chosen.text)
        itself = await client.delete(f"{BASE}/circles/{circle}/members/{host_id}", headers=bearer(H))
        check("nor itself — the host leaves through leave", itself.status_code == 409, itself.text)

        removed = await client.delete(f"{BASE}/circles/{circle}/members/{hua_id}", headers=bearer(H))
        check("the host removes the seat that never submitted", removed.status_code == 204,
              removed.status_code)
        gone = await hua_view.wait_for("seat_removed")
        check("the removed device hears that it was removed",
              gone is not None and gone.get("member_id") == hua_id, gone)
        try:
            await asyncio.wait_for(hua_view.ended.wait(), 8)
            ended = True
        except asyncio.TimeoutError:
            ended = False
        check("and its stream ends — a seat no longer in the circle stops hearing it", ended)
        dead = await client.get(f"{BASE}/circles/{circle}/members", headers=bearer(W))
        check("its key is dead in this circle", dead.status_code in (401, 404), dead.status_code)

        closed = await host_view.wait_for("closed")
        check("the removal left everyone else submitted, so the round closed for every device",
              closed is not None and (closed.get("result") or {}).get("winning_place_id") is not None,
              str(closed)[:200])
        result = await client.get(f"{BASE}/rounds/{rid}/result", headers=bearer(M))
        check("and the result is the stored one", result.status_code == 200
              and result.json().get("winning_place_id") == (closed or {}).get("result", {}).get("winning_place_id"))
        too_late = await client.delete(f"{BASE}/rounds/{rid}/submit", headers=bearer(M))
        check("after the close, a submission cannot be taken back", too_late.status_code == 409,
              too_late.text)
        host_view.cancel()

        # ---- the host leaves: the role passes ------------------------------------------------
        ming_view = Listener(client, circle, M)
        await ming_view.wait_for("snapshot")
        left = await client.post(f"{BASE}/circles/{circle}/leave", headers=bearer(H))
        check("the host can leave like anyone", left.status_code == 204, left.status_code)
        passed = await ming_view.wait_for("host_changed")
        check("the role passes to the earliest-joined seat still here, and every device hears it",
              passed is not None and passed.get("member_id") == ming_id, passed)
        members = (await client.get(f"{BASE}/circles/{circle}/members", headers=bearer(M))).json()
        check("the member list marks the new host and tells it so",
              members.get("you_are_host") is True
              and [m["is_host"] for m in members["members"]] == [True], members)
        link = await client.post(f"{BASE}/circles/{circle}/join-ticket", headers=bearer(M))
        check("and the invite link follows the host", link.status_code == 201, link.status_code)
        ming_view.cancel()

        # ---- a leave closes a round; a seat that joined after the open is not waited for ----
        ticket2 = ticket_of(link.json()["join_link"])
        joined = (await client.post(f"{BASE}/circles/{circle}/join",
                                    json={"ticket": ticket2, "nickname": "阿強"})).json()
        Q = joined["key"]
        opened2 = await client.post(f"{BASE}/circles/{circle}/rounds", json={}, headers=bearer(M))
        rid2 = opened2.json()["round_id"]
        for shop in ("巷口麵店", "轉角咖哩"):
            place = (await client.post(f"{BASE}/circles/{circle}/places", json={"name": shop},
                                       headers=bearer(M))).json()["place_id"]
            await client.post(f"{BASE}/rounds/{rid2}/proposals", json={"place_id": place},
                              headers=bearer(M))
        latecomer = (await client.post(f"{BASE}/circles/{circle}/join",
                                       json={"ticket": ticket2, "nickname": "晚到"})).json()
        refused = await client.post(f"{BASE}/rounds/{rid2}/submit", headers=bearer(latecomer["key"]))
        check("a seat that joined after the open cannot submit to this round",
              refused.status_code == 409 and "下一輪" in refused.text, refused.text)
        waiting = await client.post(f"{BASE}/rounds/{rid2}/submit", headers=bearer(M))
        check("and is not counted — two pinned seats are required",
              waiting.json().get("required") == 2, waiting.text)
        await client.post(f"{BASE}/circles/{circle}/leave", headers=bearer(Q))
        async with Session() as session:
            status = (await session.execute(
                text("select status from round where id = :r"), {"r": rid2})).scalar_one()
        check("the last unsubmitted seat leaving closes the round", status == "closed", status)

        # ---- every pinned seat leaves: the round is void (owner, 2026-10-09) --------------------
        #
        # **The reviewer's block.** A opens a round alone, B joins after the open, A leaves: nobody
        # the round waits for is left, B cannot submit to it, and one open round per circle meant
        # no other round could open — stuck for good. «The invitation lapsed», so it is voided.
        alone = (await client.post(BASE + "/circles",
                                   json={"name": "一個人的局", "nickname": "先到"})).json()
        lone_circle, A = alone["circle_id"], alone["key"]
        lone = await client.post(f"{BASE}/circles/{lone_circle}/rounds", json={}, headers=bearer(A))
        lone_rid = lone.json()["round_id"]
        b_join = (await client.post(f"{BASE}/circles/{lone_circle}/join",
                                    json={"ticket": ticket_of(alone["join_link"]),
                                          "nickname": "後到"})).json()
        B = b_join["key"]
        # A proposes before leaving, so the void has an author to erase (the reviewer's should:
        # D14's erasure was pinned only for a close).
        lone_place = (await client.post(f"{BASE}/circles/{lone_circle}/places",
                                        json={"name": "巷口麵店"}, headers=bearer(A))).json()["place_id"]
        await client.post(f"{BASE}/rounds/{lone_rid}/proposals", json={"place_id": lone_place},
                          headers=bearer(A))
        b_view = Listener(client, lone_circle, B)
        await b_view.wait_for("snapshot")
        await client.post(f"{BASE}/circles/{lone_circle}/leave", headers=bearer(A))
        voided = await b_view.wait_for("voided")
        check("the latecomer's device hears that the round was voided",
              voided is not None and voided.get("round_id") == lone_rid, voided)
        check("and no `closed` comes with it — a void round has no reveal",
              not any(e.get("type") == "closed" for e in b_view.events), [e.get("type") for e in b_view.events])
        b_view.cancel()
        async with Session() as session:
            row = (await session.execute(
                text("select status, closed_at, winning_place_id, die1, seed_commit from round "
                     "where id = :r"), {"r": lone_rid})).one()
        check("the row stays, marked void, with its time and its seed commitment and no result",
              row.status == "void" and row.closed_at is not None and row.winning_place_id is None
              and row.die1 is None and row.seed_commit is not None, str(row))
        async with Session() as session:
            authors = (await session.execute(
                text("select member_id from proposal where round_id = :r"), {"r": lone_rid})).scalars().all()
        check("a void round's proposals lose their author, as a closed round's do (D14)",
              len(authors) == 1 and authors[0] is None, authors)
        read = await client.get(f"{BASE}/rounds/{lone_rid}/result", headers=bearer(B))
        check("its result reads 410 with a sentence, never «not yet»",
              read.status_code == 410 and "作廢" in read.text, read.text)
        late_submit = await client.post(f"{BASE}/rounds/{lone_rid}/submit", headers=bearer(B))
        check("a submit to it says it is void", late_submit.status_code == 409
              and "作廢" in late_submit.text, late_submit.text)
        late_back = await client.delete(f"{BASE}/rounds/{lone_rid}/submit", headers=bearer(B))
        check("taking a submission back from it says it is void too",
              late_back.status_code == 409 and "作廢" in late_back.text, late_back.text)
        late_propose = await client.post(f"{BASE}/rounds/{lone_rid}/proposals",
                                         json={"place_id": lone_place}, headers=bearer(B))
        check("and so does proposing to it", late_propose.status_code == 409
              and "作廢" in late_propose.text, late_propose.text)
        fresh_view = Listener(client, lone_circle, B)
        fresh = await fresh_view.wait_for("snapshot")
        check("a device that arrives now sees no open round",
              fresh is not None and fresh.get("open_round") is None, str(fresh)[:160])
        fresh_view.cancel()
        reopened = await client.post(f"{BASE}/circles/{lone_circle}/rounds", json={}, headers=bearer(B))
        check("and the circle can open its next round", reopened.status_code == 201, reopened.text)

    await engine.dispose()


async def with_temporary_database() -> int:
    admin_url, test_url = urls()
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

    server = None
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrate = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv",
                                 env=environment, capture_output=True)
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2

        server = subprocess.Popen(
            ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd="/srv/src", env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import httpx  # noqa: PLC0415

        async with httpx.AsyncClient() as probe:
            for _ in range(60):
                try:
                    if (await probe.get(f"http://127.0.0.1:{PORT}/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.2)
            else:
                print("the test server never came up", file=sys.stderr)
                return 2

        await scenario(test_url)
    finally:
        if server is not None:
            server.terminate()
            server.wait(timeout=10)
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text('drop database if exists "{}" with (force)'.format(TEST_DB))
            )
        await admin.dispose()

    failed = [label for label, ok, _ in CHECKS if not ok]
    print()
    print("submit: {} checks, {}".format(
        len(CHECKS), "all green" if not failed else "{} FAILED".format(len(failed))))
    if failed:
        print(json.dumps(failed, ensure_ascii=False, indent=2), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
