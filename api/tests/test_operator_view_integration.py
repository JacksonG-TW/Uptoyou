#!/usr/bin/env python3
"""D105 — two reveal shapes, chosen by the credential that authenticated. The ticket's Done line.

Run inside the stack:
    docker compose exec api python /srv/tests/test_operator_view_integration.py

Builds and drops its own database and starts its own uvicorn on 127.0.0.1:8903, because two of the
ruled behaviours are about the SSE snapshot and httpx's ASGI transport buffers a response until the
app returns — which an SSE generator never does.

**The role is on the credential, so the sharpest test is one person with two devices.** Both tokens
below belong to the same principal and the same seat. Everything that differs between the two
payloads therefore comes from the secret that was presented and from nothing about the person — which
is the whole reason D105 put the flag there rather than on `principal`.
"""

import asyncio
import json
import os
import secrets as pysecrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from hashlib import sha256

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

TEST_DB = "upto_operator_check"
TAIPEI = timezone(timedelta(hours=8))
FAILURES = []
ARITHMETIC = ("weights", "allocation", "panel")
OUTCOME = ("round_id", "status", "dice", "sum", "winning_place_id", "places")


def check(name, condition, detail=""):
    if condition:
        print("ok   {}".format(name))
    else:
        FAILURES.append(name)
        print("FAIL {} {}".format(name, detail))


async def scenario(test_url: str, base_url: str) -> None:
    import httpx  # noqa: PLC0415

    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    plain = "t-" + pysecrets.token_urlsafe(24)
    op = "t-" + pysecrets.token_urlsafe(24)
    amy_token = "t-" + pysecrets.token_urlsafe(24)

    async with Session() as session:
        circle = (
            await session.execute(text("insert into circle (name) values ('週三午餐') returning id"))
        ).scalar_one()
        principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        member = (
            await session.execute(
                text("insert into member (principal_id, circle_id, nickname) "
                     "values (:p, :c, 'Kevin') returning id"),
                {"p": principal, "c": circle},
            )
        ).scalar_one()
        # **One person, one seat, two devices.** Anything that differs downstream is the secret's.
        for token, is_op in ((plain, False), (op, True)):
            await session.execute(
                text("insert into device_secret (principal_id, secret_sha256, operator) "
                     "values (:p, :h, :o)"),
                {"p": principal, "h": sha256(token.encode()).hexdigest(), "o": is_op},
            )
        # A categorised place plus an avoidance, so the round carries a **private** contribution —
        # the row whose reason must stay behind even from an operator (D13).
        avoided = (
            await session.execute(
                text("insert into place (origin, circle_id, name) "
                     "values ('circle-local', :c, '麻辣鍋店') returning id"),
                {"c": circle},
            )
        ).scalar_one()
        other = (
            await session.execute(
                text("insert into place (origin, circle_id, name) "
                     "values ('circle-local', :c, '轉角咖啡') returning id"),
                {"c": circle},
            )
        ).scalar_one()
        # **A category on the place and an avoidance against it — otherwise there is no private
        # contribution and the assertions below pass on an empty table.** The first run of this test
        # did exactly that: `panel` came back with empty `factors`, and "its reason is withheld"
        # passed because there was no reason to withhold. H36's family again.
        #
        # D39's provenance travels with a category or the category does not exist, so all five
        # columns are written.
        await session.execute(
            text("update place set category = '火鍋', category_model = 'test-stub', "
                 "category_prompt_version = 'v-test', category_generated_at = now(), "
                 "category_input = '麻辣鍋店' where id = :p"),
            {"p": avoided},
        )
        # **The avoidance belongs to somebody else, and that is the whole point.** The first version
        # gave it to Kevin — who holds the operator device — so the reason was shown, correctly, and
        # the assertion that it is withheld failed. The rule is *`represented_member` means exactly
        # one person*, and an operator is not exempted from it. Testing it needs a second person.
        amy_principal = (
            await session.execute(text("insert into principal default values returning id"))
        ).scalar_one()
        amy = (
            await session.execute(
                text("insert into member (principal_id, circle_id, nickname) "
                     "values (:p, :c, 'Amy') returning id"),
                {"p": amy_principal, "c": circle},
            )
        ).scalar_one()
        await session.execute(
            text("insert into device_secret (principal_id, secret_sha256, operator) "
                 "values (:p, :h, false)"),
            {"p": amy_principal, "h": sha256(amy_token.encode()).hexdigest()},
        )
        await session.execute(
            text("insert into preference (member_id, kind, value, stance, persist) "
                 "values (:m, 'avoid_category', '火鍋', 'avoid', true)"),
            {"m": amy},
        )
        await session.commit()

    P = {"Authorization": "Bearer " + plain}
    O = {"Authorization": "Bearer " + op}
    meal = (datetime.now(TAIPEI) + timedelta(hours=2)).replace(microsecond=0)

    async with httpx.AsyncClient(base_url=base_url, timeout=20) as client:
        opened = await client.post("/circles/{}/rounds".format(circle), headers=P,
                                   json={"target_hour": meal.isoformat()})
        round_id = opened.json()["round_id"]
        for place in (avoided, other):
            await client.post("/rounds/{}/proposals".format(round_id), headers=P,
                              json={"place_id": place})
        rolled_member = await client.post("/rounds/{}/roll".format(round_id), headers=P)
        check("the roll lands", rolled_member.status_code == 200, rolled_member.text)
        member_body = rolled_member.json()

        # The same closed round, asked again on the other device (D69's retry path).
        rolled_op = await client.post("/rounds/{}/roll".format(round_id), headers=O)
        check("the operator device is answered too", rolled_op.status_code == 200, rolled_op.text)
        operator_body = rolled_op.json()

        # ---- the two shapes -------------------------------------------------------------
        for field in ARITHMETIC:
            check("the member shape withholds `{}`".format(field), field not in member_body,
                  sorted(member_body))
        for field in OUTCOME:
            check("the member shape keeps `{}`".format(field), field in member_body,
                  sorted(member_body))
        for field in ARITHMETIC:
            check("the operator shape carries `{}`".format(field), field in operator_body,
                  sorted(operator_body))
        check("they agree about what happened",
              member_body["winning_place_id"] == operator_body["winning_place_id"]
              and member_body["dice"] == operator_body["dice"])
        check("the member shape is a strict subset of the operator's",
              set(member_body) <= set(operator_body),
              set(member_body) - set(operator_body))

        # ---- no PROPOSAL authorship in either, under any nesting (D55 as narrowed) --------
        # **Was "no member_id anywhere", and that reading died with D108** (owner: 「收窄」,
        # `71ddbe5`). H3's concern is that a payload must not let a reader attach a private act to a
        # person; a seat list attaches a *roll* to a person, which everybody performed visibly and on
        # purpose, and carries no link to a place. So the assertion moves to the structures where
        # authorship would actually be harmful — the pool of places and the weight panel.
        for label, payload in (("member", member_body), ("operator", operator_body)):
            flat = json.dumps(payload, ensure_ascii=False)
            check("the {} payload never names a proposer".format(label), "proposer" not in flat)
            check("the {} payload carries no principal".format(label), "principal" not in flat)
            for place_id, place_name in payload["places"].items():
                check("place {} in the {} payload is a bare name".format(place_id, label),
                      isinstance(place_name, str))
        # The panel is the operator's arithmetic and names no member either — D13 labels a factor
        # `represented_member` without saying which member, and that distinction is the whole rule.
        panel_flat = json.dumps(operator_body["panel"], ensure_ascii=False)
        check("the weight panel names no member", "member_id" not in panel_flat)

        # ---- the private row is labelled and reasonless (D13) ----------------------------
        #
        # **`fired` is not optional in this filter, and leaving it out made three checks below
        # vacuous** (the reviewer's catch on candidate 16). Since 甲's pad the panel carries every
        # contributor whether it fired or not, so a `private` row — the preference contributor's —
        # is present on every place in every round. Without the filter, «the table contains the
        # private contribution» could no longer fail, and «another member's reason is withheld»
        # would pass on a padded row whose reason is null by construction rather than by D13. The
        # subject here is a contribution somebody actually made.
        private = [
            factor
            for place in operator_body["panel"].values()
            for factor in place["factors"]
            if factor["channel"] == "private" and factor["fired"]
        ]
        check("the operator's table is not empty at all",
              any(any(f["fired"] for f in place["factors"])
                  for place in operator_body["panel"].values()),
              operator_body["panel"])
        check("the operator's table contains the private contribution", private, operator_body)
        check("its channel is named", all(f["channel"] == "private" for f in private))
        check("and another member's reason is withheld from the operator (D13)",
              all(f["reason"] is None for f in private), private)
        check("the contributor is still shown — the odds were never the secret",
              all(f["contributor"] for f in private), private)

        # **The mirror, so the rule is shown working in both directions.** Amy is not an operator and
        # sees no table at all — but the represented-member rule is what would show her own sentence
        # if she ever did, and an operator who *is* the represented member sees theirs. Asserting
        # only the withholding would pass on a payload that withheld every reason from everyone,
        # which is a different and wrong rule.
        amy_view = await client.post("/rounds/{}/roll".format(round_id),
                                     headers={"Authorization": "Bearer " + amy_token})
        check("Amy's own device is answered", amy_view.status_code == 200, amy_view.text)
        check("and it is the member shape — she is not an operator",
              all(f not in amy_view.json() for f in ARITHMETIC), sorted(amy_view.json()))

        # ---- an operator-ish parameter changes nothing -----------------------------------
        for attempt in ("?operator=true", "?operator=1&shape=operator"):
            probe = await client.post("/rounds/{}/roll{}".format(round_id, attempt), headers=P)
            body = probe.json()
            check("a request asking to be an operator is not one ({})".format(attempt),
                  all(f not in body for f in ARITHMETIC), sorted(body))

        # ---- the snapshot follows the credential (D56) -----------------------------------
        async def snapshot(headers):
            got = []
            async with httpx.AsyncClient(base_url=base_url, timeout=20) as watcher:
                async with watcher.stream("GET", "/circles/{}/stream".format(circle),
                                          headers=headers) as live:
                    if live.status_code != 200:
                        return None

                    async def collect():
                        async for line in live.aiter_lines():
                            if line.startswith("data: "):
                                got.append(json.loads(line[6:]))
                    reader = asyncio.ensure_future(collect())
                    for _ in range(50):
                        if got:
                            break
                        await asyncio.sleep(0.1)
                    reader.cancel()
            return got[0] if got else None

        member_snapshot = await snapshot(P)
        operator_snapshot = await snapshot(O)
        check("both devices receive a snapshot at all (D56)",
              member_snapshot is not None and operator_snapshot is not None)
        member_last = (member_snapshot or {}).get("last_result") or {}
        operator_last = (operator_snapshot or {}).get("last_result") or {}
        for field in ARITHMETIC:
            check("the member's snapshot withholds `{}`".format(field), field not in member_last,
                  sorted(member_last))
            check("the operator's snapshot carries `{}`".format(field), field in operator_last,
                  sorted(operator_last))

        # ---- revoking the operator secret leaves the seat --------------------------------
        async with Session() as session:
            await session.execute(
                text("delete from device_secret where secret_sha256 = :h"),
                {"h": sha256(op.encode()).hexdigest()},
            )
            await session.commit()
        gone = await client.post("/rounds/{}/roll".format(round_id), headers=O)
        check("the revoked operator device no longer authenticates", gone.status_code == 401,
              gone.status_code)
        still = await client.post("/rounds/{}/roll".format(round_id), headers=P)
        check("and the seat is untouched — the ordinary device still works",
              still.status_code == 200, still.status_code)
        check("in the member shape", all(f not in still.json() for f in ARITHMETIC))
        async with Session() as session:
            seats = (
                await session.execute(
                    text("select count(*) from member where id = :m"), {"m": member}
                )
            ).scalar()
        check("the member row survived the revocation", seats == 1, seats)

    await engine.dispose()
    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        raise SystemExit(1)
    print("\nD105: one person with two devices sees two shapes — the member's keeps what happened and "
          "withholds how the odds got there, the operator's carries the table with the private row "
          "labelled and reasonless, neither carries a member id, no parameter can ask for the "
          "operator shape, the snapshot follows the credential, and revoking the operator device "
          "leaves the seat")


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

    server = None
    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrate = subprocess.run(["alembic", "upgrade", "head"], cwd="/srv", env=environment,
                                 capture_output=True)
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2
        port = 8903
        server = subprocess.Popen(
            ["uvicorn", "upto.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd="/srv/src", env=environment,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        import httpx  # noqa: PLC0415

        base_url = "http://127.0.0.1:{}".format(port)
        async with httpx.AsyncClient() as probe:
            for _ in range(50):
                try:
                    if (await probe.get(base_url + "/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    await asyncio.sleep(0.2)
            else:
                print("the test server never came up", file=sys.stderr)
                return 2
        await scenario(test_url, base_url)
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
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(with_temporary_database()))
