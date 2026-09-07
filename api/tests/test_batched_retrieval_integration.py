#!/usr/bin/env python3
"""The batched crib retrieval — the same prompts as before, in one request instead of 25.

Run inside the stack:
    docker compose exec api python /srv/tests/test_batched_retrieval_integration.py

The test builds its own database and drops it, so it never touches the stack's data. Real
PostgreSQL, real pgvector, real `crib_retriever`; the embedder is stubbed, because what is under
test is the pairing of names to vectors and not the quality of an embedding.

---

**Why this file exists.** `run.crib_retriever` used to embed one name per HTTP request. M12
measured that cost on 2026-08-18: 0.481 s/name one at a time against **0.045 s/name at 25 names
per request — 10.8×**, because the model box pays ~430 ms of per-*request* load against ~170 ms of
real work. Batching it removes four hours from a whole-city backfill and needs no concurrency, so
the resume frontier is untouched.

**But it introduces one failure mode that did not exist before, and this file is mostly about
that.** `embed` asserts that the reply holds one vector per input and that every vector has the
expected width — and **neither assertion covers order.** With one name per request there was no
order to get wrong. With 25, a reply that came back permuted would pair every name with another
name's embedding, and the result would be a full set of *plausible* prompts: real neighbours, real
categories, attached to the wrong names. Nothing downstream could tell. The API does not document
that order is preserved, so the property this file pins is the one the code actually relies on.

Three assertions, and they are deliberately different in kind:

1. **Equivalence.** `retrieve_many` over a list returns, element for element, exactly what the
   old one-name-at-a-time shape returned. This is the claim that the verdicts stay comparable
   across the change — 南港 was classified before it and the rest of the city after.
2. **One request, not 25.** Equivalence alone would still pass if someone re-introduced a loop
   inside `retrieve_many`, and the whole 10.8× lives in the request count. So the stub counts its
   calls, and the test names the number.
3. **The check can fail** — a stub that returns the batch's vectors *reversed* must break
   equivalence. Without this, assertion 1 could be passing for a scenario where every name happens
   to retrieve the same neighbours, and would then be blind to the exact permutation bug it exists
   to catch.

**The stub's vectors are graded, not orthogonal, and that is load-bearing.** Orthogonal basis
vectors make every pair equally distant, so `order by distance` becomes a tie and the retrieved
list is whatever the plan happens to emit — a test that would flake and, worse, would compare two
arbitrary orders and call them equal. Each name here gets `[1.0, index/200, 0 …]`, so every
similarity is distinct by about 1e-3 and the neighbour order is total.
"""

import asyncio
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from upto.classify import embed as embedding  # noqa: E402
from upto.classify import examples as store  # noqa: E402
from upto.classify import run as backfill  # noqa: E402
from upto.evaluate.score import load_testset  # noqa: E402

TEST_DB = "upto_batched_retrieval_check"
STUB_MODEL = "stub-embed:test"
K = 5

# How many names to ask for in one batch. 25 is `run.BATCH`, which is the number the 10.8× was
# measured at and the number a real pass sends, so the test asks the real question.
BATCH = backfill.BATCH

_INDEX: dict[str, int] = {}
_CALLS: list[int] = []


def vector_for(name: str) -> list[float]:
    """A graded vector per name — see the header for why not orthogonal."""
    out = [0.0] * embedding.DIMENSION
    out[0] = 1.0
    out[1] = _INDEX.setdefault(name, len(_INDEX)) / 200.0
    return out


def stub_embed(texts, model=None, **_):
    """One vector per input, in order. Records how many requests it was asked to serve.

    **`**_` is the point of this signature, not laziness.** What this file tests is *batching and
    order* — that retrieval asks once per commit batch and that the vectors come back paired with
    the names they were asked about. `embed`'s parameter list is not its subject, so a stub that
    mirrors it exactly turns every addition there into a red here about nothing: `embed` gained
    `cold=` on 2026-09-04 (36af3c5) and this file, written 2026-08-18 (7f236ee), raised
    `TypeError` from then until 2026-09-07 while the product was correct throughout — three days
    of a false red that nothing swept, because the file was in no register.
    **The admitted cost:** a parameter that changes what a caller *means* — `unload_after` is the
    live example — is swallowed here in silence. A test that cares about one asserts on it
    explicitly rather than relying on the stub to refuse it.
    """
    _CALLS.append(len(texts))
    return [vector_for(name) for name in texts]


def stub_embed_reversed(texts, model=None, **_):
    """A well-formed reply with the right count, the right widths, and the wrong order.

    This is the misbehaving API `embed`'s assertions cannot detect: the count matches, the widths
    match, and every vector belongs to a different name than the one it is returned for.
    """
    _CALLS.append(len(texts))
    return [vector_for(name) for name in reversed(texts)]


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url
    engine = create_async_engine(test_url, poolclass=None)

    rows, _digest = load_testset()
    names = sorted({row["name"] for row in rows})
    assert len(names) >= BATCH, (
        "the frozen set holds {} distinct names and the batch is {} — this test cannot ask a "
        "full-size batch".format(len(names), BATCH)
    )

    # Load the crib with the stub, exactly as `test_example_store_integration` does: patched on the
    # module the loader calls, because that is the name it actually looks up.
    store.available = lambda model=None: True
    store.embed = stub_embed
    store.EMBED_MODEL = STUB_MODEL
    assert await store.main(STUB_MODEL) == 0

    # `crib_retriever` imports the embedding client lazily, so the patch goes on the module object
    # it will find. `resolve` is patched too: the key it is handed is a real one (`arctic`), and the
    # crib in this database is under the stub's name.
    embedding.available = lambda model=None: True
    embedding.resolve = lambda key: STUB_MODEL
    embedding.embed = stub_embed

    asked = names[:BATCH]

    async with engine.connect() as connection:
        retrieve_many, embed_model = await backfill.crib_retriever(connection, "arctic", K)
        assert embed_model == STUB_MODEL

        # --- 1. equivalence with the shape this replaced ---------------------------------
        _CALLS.clear()
        batched = await retrieve_many(asked)
        batched_calls = list(_CALLS)

        _CALLS.clear()
        one_at_a_time = []
        for name in asked:
            vector = stub_embed([name], model=STUB_MODEL)[0]
            found = await store.nearest(
                connection, vector, STUB_MODEL, k=K, exclude_name=name
            )
            one_at_a_time.append(
                [(row["name"], row["label"], row.get("subtype")) for row in found]
            )
        serial_calls = list(_CALLS)

    assert len(batched) == len(asked), (
        "asked for {} names and got {} neighbour lists".format(len(asked), len(batched))
    )
    for position, (name, got, want) in enumerate(zip(asked, batched, one_at_a_time)):
        assert got == want, (
            "position {} ({}) retrieved different neighbours batched than one at a time — "
            "the vectors are misaligned\n  batched {}\n  serial  {}".format(
                position, name, got, want
            )
        )
    # Every name must retrieve exactly k, and none of them may retrieve itself: D88's
    # leave-one-out is per name, and batching the embedding must not have made it per batch.
    for name, got in zip(asked, batched):
        assert len(got) == K, (name, len(got))
        assert name not in [row[0] for row in got], (
            "{} was handed its own answer — `exclude_name` is per name and batching the "
            "embedding call must not have widened it".format(name)
        )

    # --- 2. one request, not 25 ---------------------------------------------------------
    assert batched_calls == [BATCH], (
        "the batch should be one embedding request carrying {} names; the stub was called with "
        "{} — the 10.8× measured in M12 is entirely in this number, so a loop reintroduced "
        "inside `retrieve_many` would keep every other assertion green and lose the whole "
        "speedup".format(BATCH, batched_calls)
    )
    assert serial_calls == [1] * BATCH, serial_calls

    # --- 3. the check can fail ----------------------------------------------------------
    embedding.embed = stub_embed_reversed
    async with engine.connect() as connection:
        retrieve_many, _ = await backfill.crib_retriever(connection, "arctic", K)
        _CALLS.clear()
        permuted = await retrieve_many(asked)
    assert permuted != one_at_a_time, (
        "a reply with the right count, the right widths and the wrong order produced the same "
        "neighbours as a correct one — this test cannot see the permutation bug it exists for, "
        "and neither can `embed`'s assertions"
    )
    # **And name what actually broke, because the first guess was wrong and the truth is worse.**
    # A reversed reply does *not* simply swap the two names' neighbour lists. The vector comes from
    # the mirror while `exclude_name` still carries the real name — so the query and the exclusion
    # disagree, and the list is a hybrid of two names that belongs to neither. Asserting the
    # tidy "each name gets its mirror's list" version failed here, which is how the hybrid was
    # found; the assertion below is the measured behaviour rather than the expected one.
    mirror = list(reversed(asked))
    async with engine.connect() as connection:
        hybrid = []
        for name, source in zip(asked, mirror):
            found = await store.nearest(
                connection, vector_for(source), STUB_MODEL, k=K, exclude_name=name
            )
            hybrid.append([(row["name"], row["label"], row.get("subtype")) for row in found])
    assert permuted == hybrid, (
        "a reversed reply should query with the mirror's vector while excluding the real name; "
        "it did not, so the failure mode this test documents is not the one it reproduces"
    )

    # **The consequence worth stating on its own: misalignment defeats D88's leave-one-out.**
    # `exclude_name` removes the name being asked about, but the vector is another name's — so the
    # *mirror* is free to appear in its own neighbour list, and a name can be handed its own label
    # as evidence. That is the difference between "the crib was unhelpful" and "the crib answered
    # the question", and it is invisible in the output.
    leaked = [
        (name, source) for name, source, got in zip(asked, mirror, permuted)
        if source in [row[0] for row in got]
    ]
    assert leaked, (
        "no name retrieved its own vector's owner under the permuted reply, so this scenario "
        "does not demonstrate the leave-one-out leak — the assertion above still holds, but the "
        "worst consequence of misalignment is not being shown"
    )

    await engine.dispose()
    print(
        "batched retrieval: 25 names in one embedding request return exactly the neighbours "
        "25 separate requests returned, each still without its own answer; the request count is "
        "pinned at one because the 10.8× lives there; and a right-count wrong-order reply — the "
        "one `embed`'s assertions cannot catch — is shown breaking the pairing"
    )


async def with_temporary_database() -> int:
    live = os.environ["UPTO_DATABASE_URL"]
    head, _, _ = live.rpartition("/")
    admin_url, test_url = head + "/postgres", head + "/" + TEST_DB

    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        from sqlalchemy import text

        await connection.execute(text('drop database if exists "{}"'.format(TEST_DB)))
        await connection.execute(text('create database "{}"'.format(TEST_DB)))
    await admin.dispose()

    try:
        environment = dict(os.environ, UPTO_DATABASE_URL=test_url)
        migrate = subprocess.run(
            ["alembic", "upgrade", "head"], cwd="/srv", env=environment, capture_output=True
        )
        if migrate.returncode != 0:
            print(migrate.stderr.decode("utf-8", "replace"), file=sys.stderr)
            return 2
        await scenario(test_url)
    finally:
        from sqlalchemy import text

        admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as connection:
            await connection.execute(
                text('drop database if exists "{}" with (force)'.format(TEST_DB))
            )
        await admin.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
