#!/usr/bin/env python3
"""D88's example store, against a real PostgreSQL, a real pgvector, and a stub embedder.

Run inside the stack:
    docker compose exec api python /srv/tests/test_example_store_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**The embedder is stubbed and the vectors are hand-chosen.** What is under test is the store
half — that a load writes the whole frozen set under one digest and one `labeled_by`, that
`<=>` really orders by cosine distance, that the leave-one-out exclusion removes every copy
of a name, and that a second load replaces rather than appends. Whether bge-m3's neighbours
are *good* neighbours is the evaluation round's question and needs a live model, not a fixed
one; a stub here is what makes the cosine order something the reader can verify by hand.

The vectors are unit basis vectors in the first few coordinates, so every distance in this
file is arithmetic:

    query           e0
    小李子麵食館      e0                 cosine distance 0
    路易莎咖啡…       0.6·e0 + 0.8·e1    distance 1 - 0.6 = 0.4
    everything else  e9                 distance 1

so the nearest two are fixed and everything behind them is a tie the test never depends on.

**The second half is 0019's: two embedders in one table.** A second stub embedder loads the
same 200 names into a *different* arrangement — the near/far pair is deliberately swapped —
and the assertions are the four ways the per-model key could fail to hold: the second load
does not collide with the first, `nearest` returns the asked embedder's order and not the
other's, reloading one leaves the other's rows and digest untouched, and each embedder's
digest is read on its own. The swap is what makes the filter observable: if the WHERE clause
were dropped, the two spaces would interleave and the order would be neither model's.
"""

import asyncio
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from upto.classify import embed as embedding  # noqa: E402
from upto.classify import examples as store  # noqa: E402
from upto.evaluate.score import load_testset  # noqa: E402

TEST_DB = "upto_examples_check"

STUB_MODEL = "stub-embed:test"
# 0019's second embedder. A different *name*, because the name is the key — and a different
# arrangement, because a filter nobody could observe failing is not tested.
OTHER_MODEL = "stub-embed:other"

# Three names lifted from the frozen set itself, so the load is the real 200-row load and the
# hand-computable pairs are genuinely inside it. 薔薇廳 is one of the 7 names the set repeats.
NEAR = "小李子麵食館"
MIDDLE = "路易莎咖啡股份有限公司"
OTHER_NEAR = "臺北碧瑤飯店"
REPEATED = "薔薇廳"


def basis(index: int, weight: float = 1.0) -> list[float]:
    vector = [0.0] * embedding.DIMENSION
    vector[index] = weight
    return vector


def _diagonal() -> list[float]:
    vector = basis(0, 0.6)
    vector[1] = 0.8
    return vector


def stub_embed(texts, model=None, **service):
    """Deterministic vectors, and the two stub embedders disagree about which name is nearest.

    **`**service` swallows the real embedder's service arguments — `cold`, `unload_after` —
    and that is deliberate rather than lazy.** They are H52's and H43's, about a model service
    this stub does not have: there is no first request to be dropped and nothing resident to
    unload. Named explicitly the stub would have to be edited every time a hazard adds one, and
    the edit was missed once already: `cold=`/`unload_after=` landed in `examples.main` on
    2026-08-31 and this file went red as `TypeError: unexpected keyword argument 'cold'` — which
    reads as a broken test rather than as a stale stub, and left the crib-load path unverified.

    Under `stub-embed:test` the query e0 lands on 小李子麵食館; under `stub-embed:other` it
    lands on 臺北碧瑤飯店 and 小李子麵食館 is parked at distance 1. So a `nearest` that had
    lost its `embed_model` filter would return the *other* model's row first, which is a
    visible failure rather than a silent tie.
    """
    other = model == OTHER_MODEL
    vectors = []
    for name in texts:
        if name == (OTHER_NEAR if other else NEAR):
            vectors.append(basis(0))
        elif name == MIDDLE:
            vectors.append(_diagonal())
        else:
            vectors.append(basis(9))
    return vectors


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url
    engine = create_async_engine(test_url, poolclass=None)

    rows, digest = load_testset()
    distinct = len({row["name"] for row in rows})
    present = {row["name"] for row in rows}
    for required in (NEAR, MIDDLE, OTHER_NEAR):
        assert required in present, "the frozen set no longer holds " + required

    # An empty table is None rather than an error — the round runner turns that into "run the
    # load first", which is a different message from "the load is stale".
    assert await store.stored_sha(engine, STUB_MODEL) is None
    assert await store.loaded_models(engine) == []

    # The load, with the model stubbed at both doors: `available` says the service is up and
    # `embed` returns the hand-chosen vectors. Patched on the module the loader imported into,
    # because that is the name it actually calls.
    store.available = lambda model=None: True
    store.embed = stub_embed
    store.EMBED_MODEL = STUB_MODEL

    assert await store.main(STUB_MODEL) == 0

    async with engine.connect() as connection:
        stored = (
            await connection.execute(
                text(
                    "select count(*) as n, count(distinct source_digest) as shas, "
                    "count(distinct embed_model) as models, "
                    "count(distinct labeled_by) as authors, "
                    "count(subtype) as subtypes from example_embedding"
                )
            )
        ).one()

    # 0018: one row per distinct name, and the frozen set's 7 repeats collapse losslessly.
    assert stored.n == distinct, f"stored {stored.n} rows for {distinct} distinct names"
    assert stored.n < len(rows), "the repeated names did not collapse"
    # One digest, one embedding model, one label author across the whole table — the table is
    # written whole or not at all, and each of these columns is a statement about every row.
    assert (stored.shas, stored.models, stored.authors) == (1, 1, 1), stored
    # The amendment's second column: the frozen set carries no finer tag, so every subtype is
    # NULL. The rendering branch that uses one is covered in test_classify_rag.py.
    assert stored.subtypes == 0, f"{stored.subtypes} rows invented a subtype"

    async with engine.connect() as connection:
        provenance = (
            await connection.execute(
                text(
                    "select embed_model, source_digest, labeled_by, subtype, layer "
                    "from example_embedding where name = :n"
                ),
                {"n": NEAR},
            )
        ).one()
    assert provenance.embed_model == STUB_MODEL
    assert provenance.source_digest == digest, "the stored digest is not the file's"
    # Disclosed 2026-08-15: the frozen set's labels were drafted by Fable 5 and cross-checked
    # against Gemini, never hand-adjudicated. The crib says so on every row.
    assert provenance.labeled_by == store.TESTSET_LABELED_BY == "fable5+gemini"
    assert provenance.subtype is None
    assert provenance.layer in ("sign", "brand", "registered")

    # `stored_sha` is what the round runner asks before it asks the model anything, and after
    # 0019 it asks per embedder — an embedder nobody loaded is None, not the other one's sha.
    assert await store.stored_sha(engine, STUB_MODEL) == digest
    assert await store.stored_sha(engine, OTHER_MODEL) is None

    # --- retrieval, by hand ---------------------------------------------------------------

    query = basis(0)
    async with engine.connect() as connection:
        nearest = await store.nearest(connection, query, STUB_MODEL, k=2, exclude_name="")
    assert [row["name"] for row in nearest] == [NEAR, MIDDLE], nearest
    assert nearest[0]["label"] == next(r["label"] for r in rows if r["name"] == NEAR)
    assert nearest[0]["subtype"] is None, "nearest must carry the subtype slot, NULL or not"

    # Leave-one-out: the asked name is in the store, and handing back its own gold row would
    # be handing the model the exam answer (D82/D88).
    async with engine.connect() as connection:
        excluded = await store.nearest(connection, query, STUB_MODEL, k=2, exclude_name=NEAR)
    assert NEAR not in [row["name"] for row in excluded], excluded
    assert excluded[0]["name"] == MIDDLE, excluded

    # One exclusion removes every copy of a repeated name, because 0019's UNIQUE already
    # collapsed them into one row per embedder — the property that makes exclusion-by-name
    # whole within the space being searched.
    async with engine.connect() as connection:
        without_repeat = await store.nearest(
            connection, basis(9), STUB_MODEL, k=distinct, exclude_name=REPEATED
        )
    assert REPEATED not in [row["name"] for row in without_repeat]
    assert len(without_repeat) == distinct - 1, len(without_repeat)

    # An engine may be passed instead of a connection; it opens its own.
    assert (
        await store.nearest(engine, query, STUB_MODEL, k=1, exclude_name="")
    )[0]["name"] == NEAR

    # --- a second load replaces, never appends -------------------------------------------

    assert await store.main(STUB_MODEL) == 0
    async with engine.connect() as connection:
        again = (
            await connection.execute(text("select count(*) from example_embedding"))
        ).scalar_one()
    assert again == distinct, f"a second load left {again} rows where {distinct} were expected"

    # --- 0019: a second embedder beside the first ----------------------------------------

    assert await store.main(OTHER_MODEL) == 0
    async with engine.connect() as connection:
        side_by_side = (
            await connection.execute(
                text(
                    "select embed_model, count(*) as n from example_embedding "
                    "group by embed_model order by embed_model"
                )
            )
        ).all()
    # Two embedders, each holding the whole frozen set. Under 0018's `name` UNIQUE the second
    # load could not have been inserted at all; under a whole-table delete it would have taken
    # the first with it. Both failures land here.
    assert [(row.embed_model, row.n) for row in side_by_side] == [
        (OTHER_MODEL, distinct),
        (STUB_MODEL, distinct),
    ], side_by_side

    # The filter, and this is the assertion the swapped arrangement exists for: the same query
    # vector reads differently under each embedder, and a search that had lost its WHERE
    # clause would put the other model's e0 row first.
    async with engine.connect() as connection:
        under_stub = await store.nearest(connection, query, STUB_MODEL, k=2, exclude_name="")
        under_other = await store.nearest(connection, query, OTHER_MODEL, k=2, exclude_name="")
    assert [row["name"] for row in under_stub] == [NEAR, MIDDLE], under_stub
    assert [row["name"] for row in under_other] == [OTHER_NEAR, MIDDLE], under_other

    # A whole-space read returns one embedder's rows and not both: 179, not 358.
    async with engine.connect() as connection:
        whole_space = await store.nearest(
            connection, query, STUB_MODEL, k=distinct * 2, exclude_name=""
        )
    assert len(whole_space) == distinct, len(whole_space)

    # Per-embedder digests, read on their own.
    assert await store.stored_sha(engine, STUB_MODEL) == digest
    assert await store.stored_sha(engine, OTHER_MODEL) == digest

    # `loaded_models` is the one read that deliberately crosses embedders — it is the `status`
    # command's whole content, and its question is which cells of the matrix exist.
    held = await store.loaded_models(engine)
    assert [entry["embed_model"] for entry in held] == [OTHER_MODEL, STUB_MODEL], held
    assert all(entry["rows"] == distinct and entry["digests"] == 1 for entry in held), held
    assert all(entry["sha"] == digest for entry in held), held

    # Reloading one embedder leaves the other's rows exactly where they were — the nine-cell
    # matrix is nine loads into one table, not nine loads that each destroy the last.
    async with engine.connect() as connection:
        before = (
            await connection.execute(
                text(
                    "select min(id) as lo, max(id) as hi, count(*) as n from example_embedding "
                    "where embed_model = :m"
                ),
                {"m": OTHER_MODEL},
            )
        ).one()
    assert await store.main(STUB_MODEL) == 0
    async with engine.connect() as connection:
        after = (
            await connection.execute(
                text(
                    "select min(id) as lo, max(id) as hi, count(*) as n from example_embedding "
                    "where embed_model = :m"
                ),
                {"m": OTHER_MODEL},
            )
        ).one()
    # Same ids, not merely the same count: rewritten-and-restored rows would keep the count
    # and take new ids, and that is a different claim from untouched.
    assert (after.lo, after.hi, after.n) == (before.lo, before.hi, before.n), (before, after)
    async with engine.connect() as connection:
        both = (
            await connection.execute(text("select count(*) from example_embedding"))
        ).scalar_one()
    assert both == distinct * 2, both

    # The service being off is an ordinary outcome, distinct from a failure, and writes
    # nothing: every row from every successful load is still there afterwards.
    store.available = lambda model=None: False
    assert await store.main(STUB_MODEL) == 3
    async with engine.connect() as connection:
        survived = (
            await connection.execute(text("select count(*) from example_embedding"))
        ).scalar_one()
    assert survived == distinct * 2, "an unavailable embedder emptied the table"

    await engine.dispose()
    print(
        "example store: the frozen set loads whole under one digest, one embed model and one "
        "label author, repeated names collapse losslessly, cosine order is exact, "
        "leave-one-out removes every copy of the asked name, a re-load replaces — and 0019's "
        "two embedders sit side by side, each searched and each reloaded on its own"
    )


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        for attempt in (1, 2):
            migrate = subprocess.run(
                ["alembic", "upgrade", "head"], cwd="/srv", env=environment, capture_output=True
            )
            if migrate.returncode != 0:
                print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
                return 2
            if attempt == 2:
                noise = migrate.stdout.decode("utf-8", "replace") + migrate.stderr.decode(
                    "utf-8", "replace"
                )
                assert "Running upgrade" not in noise, (
                    "the second `alembic upgrade head` ran a migration:\n" + noise
                )
        await scenario(test_url)
    finally:
        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text('drop database if exists "{}" with (force)'.format(TEST_DB))
            )
        await admin.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
