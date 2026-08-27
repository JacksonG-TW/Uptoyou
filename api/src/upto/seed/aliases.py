"""D113's authored aliases — the rows themselves, and what verifies each one.

Run:  docker compose exec api python -m upto.seed.aliases          (apply; idempotent)
      docker compose exec api python -m upto.seed.aliases --list    (print, write nothing)

**The list lives in code so the authoring is in git.** D113's second iron law wants per-row
provenance with a date; a row typed straight into the database has a date and no reviewable history.
Here the row, its author, its date and the evidence that makes it believable all arrive in one diff.

**Every entry is verified against a *published* brand pairing, never against general knowledge.**
The bound the owner set is «the obvious foreign-branded chains you can verify against the brand
pairings», so the test each candidate has to pass is: does `brand_registration` itself connect this
registered name to this foreign brand? Where it does not, there is no row, however obvious the chain
seems from outside.

**The list is one row long, and that is the honest answer rather than a stub.** Measured against the
current publications on 2026-08-20, every other large Latin-branded pairing fails the *need* test
rather than the verification test — the everyday Chinese name is already somewhere the search
reaches:

    悠旅生活事業股份有限公司 → STARBUCKS COFFEE   176 places   星巴克 appears NOWHERE  -> alias
    富利餐飲股份有限公司     → 肯德基              98 places   brand is already Chinese
    安心食品服務股份有限公司 → 摩斯漢堡           128 places   brand is already Chinese
    和德昌股份有限公司       → 麥當勞                          brand is already Chinese, and
                                                              68 sign rows carry 麥當勞 too
    富達零售股份有限公司     → OK mart            143 places   "OK" matches the brand directly
    統一多拿滋股份有限公司   → MisterDonut          32 places   多拿滋 is in the company name
    臺灣山崎股份有限公司     → Yamazaki             10 places   山崎 is in the company name
    咖碼股份有限公司         → CAMA                 61 places   咖碼 is in the company name
    天仁茶業股份有限公司     → CHAFFEE              42 places   天仁 is in the company name
    長沂國際實業股份有限公司 → COMEBUY              61 places   no standard Chinese name exists

**統一超商 split into a row that is in and a row that stays out, and the reason each way is worth
keeping.** The pairing reads `統一超商股份有限公司 → 統一超商股份有限公司`; nothing published connects
it to `7-ELEVEN`, so the default verification bound is met by neither spelling.

**`7-11` and `7-ELEVEN` are in, by the owner's per-row exception (D113 as amended 2026-08-20).** He
accepted that their correctness is his assertion. Their notes cite the ruling, which is the whole
difference between an exception path and "everyone knows".

**`小七` stays out, and it now has three reasons — the third measured by the evaluator.** No published
pairing; 統一超商 is typable today and returns rows; and **`小七` already returns two real rows,
`小七清粥小菜` and `小七食堂`, genuine eateries whose registered names contain 小七.** The alias would
not fill an empty result — it would bury two restaurants under a convenience chain's hundreds of
branches. **That is the first measured case of an alias being actively worse than its absence**, and
it is the argument to reach for if anyone proposes the row again: the everyday-name problem and the
collision problem point opposite ways here, and an alias that hides real stores harms the members it
was meant to help.

**Adding a row is not routine.** Each one is data this product asserts on its own authority, so the
`note` must name the published fact that supports it, and a row whose note would read "everyone
knows" does not belong in the table.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

# **`sqlalchemy` is imported inside `apply()`, not here, and that is what keeps the authored list
# checkable.** `app/api/tests/test_search_alias.py` asserts D113's iron laws on the host, where there
# is no sqlalchemy — a module-level import would put the provenance rules behind a dependency the
# test runner does not have, and the test would then have to be a copy of the list instead of the
# list. Same decision as `airflow/dags/_alerts.py`, for the same reason.

AUTHOR = "operator"

PAIRING = "pairing"          # a published brand_registration row supports it — falsifiable
OWNER_RULED = "owner-ruled"  # nothing published does; the owner asserted it — ask him to withdraw

# (alias, registered_name, authored_at, basis, note)
#
# **`basis` is a column and not a sentence, and that is the fix for a false pass.** The first version
# left it in the prose and the test asserted every note names `brand_registration`; the two
# owner-ruled rows passed it, because their notes mention `brand_registration` **to say it does not
# support them**. A true assertion about the wrong subject. The column is what
# `test_search_alias.py` reads now.
#
# The note is still the verification, not a description: for a `pairing` row it says which published
# row makes the mapping checkable; for an `owner-ruled` row it cites the ruling.
ALIASES: tuple[tuple[str, str, date, str, str], ...] = (
    # **The owner-exception rows (D113 as amended 2026-08-20).** These two have no published pairing
    # — `統一超商股份有限公司 → 統一超商股份有限公司` is all `brand_registration` says — and the owner
    # ruled them in anyway, accepting that their correctness is his assertion rather than a
    # publisher's. **The note therefore cites the ruling, and that is the whole of the exception
    # path: it is not "everyone knows" with better manners.** Both spellings are separate rows
    # because a member types one or the other and neither contains the other.
    (
        "7-11",
        "統一超商股份有限公司",
        date(2026, 8, 20),
        OWNER_RULED,
        "OWNER-RULED 2026-08-20 (「別名應該是7-11」), D113's amended per-row exception path. "
        "No published pairing supports this: brand_registration reads 統一超商股份有限公司 → "
        "統一超商股份有限公司 and nothing connects it to 7-ELEVEN. The owner accepted that this "
        "row's correctness is his assertion. Withdraw it by asking him, not by checking a source.",
    ),
    (
        "7-ELEVEN",
        "統一超商股份有限公司",
        date(2026, 8, 20),
        OWNER_RULED,
        "OWNER-RULED 2026-08-20 (「別名應該是7-11」), D113's amended per-row exception path — the "
        "second spelling a member might type for the same chain. No published pairing supports "
        "it either: brand_registration reads 統一超商股份有限公司 → 統一超商股份有限公司. This "
        "row's correctness is the owner's assertion. Withdraw it by asking him, not by checking "
        "a source.",
    ),
    (
        "星巴克",
        "悠旅生活事業股份有限公司",
        date(2026, 8, 20),
        PAIRING,
        "brand_registration pairs 悠旅生活事業股份有限公司 with STARBUCKS COFFEE; 星巴克 is the "
        "standard Chinese rendering of that brand and appears in no place, brand or company name "
        "in any publication. D113's ruled example.",
    ),
)


async def apply(list_only: bool = False) -> int:
    from sqlalchemy import text

    from ..db import dispose_all, pipeline_session_factory

    if list_only:
        for alias, registered, authored, basis, note in ALIASES:
            print("{} -> {}\n  basis {} · authored {} by {}\n  {}\n".format(
                alias, registered, basis, authored.isoformat(), AUTHOR, note))
        print("{} alias(es); nothing written".format(len(ALIASES)))
        return 0

    Session = pipeline_session_factory()
    try:
        async with Session() as session:
            for alias, registered, authored, basis, note in ALIASES:
                # **Idempotent by the unique pair**, so re-running after adding a row applies only
                # the new one. `note` and the date are refreshed on conflict: the authoring is the
                # thing under review, and a stale note is worse than no note.
                await session.execute(
                    text(
                        "insert into search_alias "
                        "  (alias, registered_name, authored_by, authored_at, basis, note) "
                        "values (:a, :r, :who, :when, :basis, :note) "
                        "on conflict (alias, registered_name) do update set "
                        "  authored_by = excluded.authored_by, "
                        "  authored_at = excluded.authored_at, "
                        "  basis = excluded.basis, "
                        "  note = excluded.note"
                    ),
                    {"a": alias, "r": registered, "who": AUTHOR,
                     "when": authored, "basis": basis, "note": note},
                )
            await session.commit()
            held = (
                await session.execute(text("select count(*) from search_alias"))
            ).scalar_one()
    finally:
        await dispose_all()

    print("search_alias: {} authored alias(es) applied, {} held".format(len(ALIASES), held))
    print("match-only — D113: no name a member sees comes from this table")
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print the aliases, write nothing")
    arguments = parser.parse_args()
    return asyncio.run(apply(arguments.list))


if __name__ == "__main__":
    sys.exit(cli())
