#!/usr/bin/env python3
"""D75/D76's backfill, against a real PostgreSQL and a stub model.

Run inside the stack:
    docker compose exec api python /srv/tests/test_classify_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**The model is stubbed on purpose.** What is under test is the schema half — materialising
a township (D76), writing provenance with the value (D39), D80's name ladder choosing what
the model is asked about, D79's decided absence being skipped on the next pass while a
refusal is retried, and a prompt-version change clearing every decided row. Whether the
model answers *well* is the evaluation rounds' question and needs a fixed set, not a live
service.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.classify import PROMPT_VERSION  # noqa: E402
from upto.classify import run as runner  # noqa: E402
import _tempdb  # noqa: E402

TEST_DB = "upto_classify_check"

NAMES = {
    "A-1": "啟祥早餐店",
    "A-2": "老捌麻辣食堂",
    "A-3": "旨王開發有限公司",
    "A-4": "一階堂",
    "A-5": "悠旅測試股份有限公司",
}
# What the stub model answers, keyed by the string it is asked about. D80's ladder decides
# that string: A-2 is asked as its storefront sign, A-5 as its single brand, the rest as
# their registered names. A-3 is a legal entity — D79's decided absence. A-4's answer is
# outside D38's list on purpose.
ANSWERS = {
    "啟祥早餐店": "早餐",
    "老捌麻辣鍋物": "火鍋",  # A-2's sign — the registered name must never reach the model
    "旨王開發有限公司": "法人",
    "一階堂": "拉麵",
    "星巴克測試": "咖啡飲料",  # A-5's brand — likewise
}


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url
    engine = create_async_engine(test_url, poolclass=None)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        for code, name in (("63000010", "松山區"), ("63000020", "信義區")):
            await session.execute(
                text(
                    "insert into township_station "
                    "(township_code, township_name, station_id, station_name, resolution) "
                    "values (:c, :n, 'C0A980', '測試站', 'town_code')"
                ),
                {"c": code, "n": name},
            )
        publication = (
            await session.execute(
                text(
                    "insert into place_publication (source, content_sha256, detected_at, "
                    "payload_bytes, entry_name, entry_bytes, scope) "
                    "values ('fda-97', repeat('b', 64), now(), 1000, 'x.csv', 1000, "
                    "'餐飲場所 / 臺北市') returning id"
                )
            )
        ).scalar_one()
        for registry_no, name in NAMES.items():
            await session.execute(
                text(
                    "insert into reference_place (publication_id, registry_no, origin, name, "
                    "name_raw, address, address_raw, township_code, township_name) "
                    "values (:pub, :no, 'reference', :n, :n, 'x', 'x', '63000010', '松山區')"
                ),
                {"pub": publication, "no": registry_no, "n": name},
            )
        # A neighbouring township, so the backfill is shown to stay inside its own scope.
        await session.execute(
            text(
                "insert into reference_place (publication_id, registry_no, origin, name, "
                "name_raw, address, address_raw, township_code, township_name) "
                "values (:pub, 'B-1', 'reference', '信義區的店', '信義區的店', 'x', 'x', "
                "'63000020', '信義區')"
            ),
            {"pub": publication},
        )
        # D80's ladder, seeded: A-2 carries a storefront sign, A-5 a single brand.
        brand_pub = (
            await session.execute(
                text(
                    "insert into brand_publication (source, content_sha256, detected_at, "
                    "payload_bytes, scope) values ('taipei-foodtracer', repeat('c', 64), "
                    "now(), 1000, 'x') returning id"
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into brand_registration (publication_id, company_name, "
                "company_name_raw, brand_name, brand_name_raw) "
                "values (:p, '悠旅測試股份有限公司', '悠旅測試股份有限公司', "
                "'星巴克測試', '星巴克測試')"
            ),
            {"p": brand_pub},
        )
        storefront_pub = (
            await session.execute(
                text(
                    "insert into storefront_publication (source, content_sha256, "
                    "detected_at, payload_bytes, scope) values ('taipei-hygiene-grade', "
                    "repeat('d', 64), now(), 1000, 'x') returning id"
                )
            )
        ).scalar_one()
        await session.execute(
            text(
                "insert into storefront_name (publication_id, registry_no, name, name_raw, "
                "grade) values (:p, 'A-2', '老捌麻辣鍋物', '老捌麻辣鍋物', '優')"
            ),
            {"p": storefront_pub},
        )
        await session.commit()

    # The stub: answers from the table above, and records what it was asked.
    asked = []

    def stub(prompt):
        # Matched on the 店名 line alone, never by substring over the whole prompt: the
        # instruction's own step-0 example (「旨王開發有限公司」) is inside every prompt,
        # and a substring match returns 法人 for anything it reaches first — a stub bug the
        # old schema hid, because a swallowed refusal and a decided absence both wrote
        # nothing. D79 made them distinguishable and this stub honest.
        asked.append(prompt)
        name = prompt.rsplit("店名：", 1)[1].split("\n", 1)[0].strip()
        try:
            return ANSWERS[name]
        except KeyError:
            raise AssertionError(
                "the runner asked about a name the test never seeded: " + name
            ) from None

    runner.ask = stub
    runner.available = lambda: True
    runner.MODEL = "stub-model:test"

    assert await runner.main("63000010") == 0

    # D80: the registered names of the sign-carrying and brand-carrying rows never reached
    # the model — the ladder's output did.
    joined = "\n".join(asked)
    assert "老捌麻辣食堂" not in joined, "A-2 was asked as its registered name, not its sign"
    assert "悠旅測試股份有限公司" not in joined, "A-5 was asked as itself, not its brand"

    async with Session() as session:
        rows = (
            await session.execute(
                text(
                    "select p.registry_no, p.category, p.category_model, "
                    "p.category_prompt_version, p.category_generated_at, p.category_input "
                    "from place p where p.origin = 'reference' order by p.registry_no"
                )
            )
        ).all()
    by_registry = {row.registry_no: row for row in rows}

    # D76: the township was materialised — and only this township.
    assert set(by_registry) == set(NAMES), f"materialised the wrong set: {sorted(by_registry)}"

    # D39: the value travels with its provenance — and now with the asked string (0015).
    assert by_registry["A-1"].category == "早餐"
    assert by_registry["A-1"].category_input == "啟祥早餐店"
    assert by_registry["A-2"].category == "火鍋"
    assert by_registry["A-2"].category_input == "老捌麻辣鍋物"
    assert by_registry["A-5"].category == "咖啡飲料"
    assert by_registry["A-5"].category_input == "星巴克測試"
    assert by_registry["A-1"].category_model == "stub-model:test"
    # Against the constant, never a literal: a bumped version must not need a test edit,
    # or the test starts asserting history instead of behaviour.
    assert by_registry["A-1"].category_prompt_version == PROMPT_VERSION
    assert by_registry["A-1"].category_generated_at is not None

    # D63: an answer outside D38's list is not written and not coerced — a refusal is not
    # a decision, so the row stays entirely undecided.
    assert by_registry["A-4"].category is None, "拉麵 was written despite being off the list"
    assert by_registry["A-4"].category_model is None
    assert by_registry["A-4"].category_input is None

    # D79: a legal entity is a decided absence — no category, full provenance, the asked
    # string recorded. The absence D58 states, never 其他.
    assert by_registry["A-3"].category is None, "a legal entity was given a category"
    assert by_registry["A-3"].category_model == "stub-model:test"
    assert by_registry["A-3"].category_prompt_version == PROMPT_VERSION
    assert by_registry["A-3"].category_input == "旨王開發有限公司"

    # The prompt the model actually received carries the ladder, not just the name.
    assert any("判斷順序" in prompt for prompt in asked)

    # D79's point: a second run retries exactly what holds no decision — the refused row and
    # nothing else. The legal entity is recorded and skipped, which is the measured hour of
    # re-asking this revision exists to stop.
    asked.clear()
    assert await runner.main("63000010") == 0
    assert len(asked) == 1, f"a second pass re-asked {len(asked)} names instead of the one"
    assert "一階堂" in asked[0]

    # A prompt version change invalidates its own output — the decided absence included:
    # rows written under the old version are cleared and re-done, because a column holding
    # two versions answers a different question per row (D39).
    async with Session() as session:
        await session.execute(
            text("update place set category_prompt_version = 'v0-superseded' "
                 "where category_generated_at is not null")
        )
        await session.commit()
    asked.clear()
    assert await runner.main("63000010") == 0
    assert len(asked) == 5, f"a superseded prompt version left {5 - len(asked)} rows unre-done"

    # The model being off is an ordinary outcome, distinct from a failure, and writes nothing.
    runner.available = lambda: False
    assert await runner.main("63000010") == 3

    await engine.dispose()
    print(
        "classify: the ladder decides what the model is asked, a decided absence is skipped "
        "while a refusal retries, provenance travels with every decision, and a version "
        "bump re-does them all"
    )


async def with_temporary_database() -> int:
    async def served(test_url: str, environment: dict) -> None:
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, served)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
