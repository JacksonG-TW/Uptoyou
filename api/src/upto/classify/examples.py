"""D88's example store: loading the frozen set into vectors, and retrieving cribs from it.

Load it once per embedder, inside the stack, with the model service up (it is behind a
compose profile):

    docker compose --profile model up -d ollama
    docker compose exec ollama ollama pull bge-m3
    docker compose exec api python -m upto.classify.examples load
    docker compose exec api python -m upto.classify.examples load --embed qwen3e
    docker compose exec api python -m upto.classify.examples status

Exit **0** the table holds the set · **2** usage, including an embedder key nothing pins ·
**3** the embedding service is not up and **nothing was written** — ordinary rather than a
failure, the same code `upto.classify.run` uses for the same situation.

**One table, several embedders side by side, keyed by `embed_model` (0019).** D88's
amendment, owner-ruled 2026-08-17: the embedder is a measured variable and the matrix is
3 embedders × 3 generators, so the nine cells share one table rather than taking turns in it.
Every read here therefore names an embedder, and that argument is required rather than
defaulted at the query — cosine distance between two models' vectors is a well-formed number
that means nothing, and a filter that could be forgotten is a filter that will be.

**The load is one transaction that empties this embedder's rows and refills them.** Not an
upsert, and not a whole-table wipe either: the table is a derived cache of the **current** test
set (`testset_v2.json` since 2026-08-30; see `evaluate.score.TESTSET_PATH`)
(0018), a partial refresh would leave rows from two digests side by side while
`testset_sha256` claimed one of them, and a whole-table wipe would destroy the other
embedders' work to reload one. Delete-where-model then insert means each embedder's rows are
wholly the old set or wholly the new one, and its digest is then a true statement about every
row it owns.

**Retrieval is leave-one-out and that is not a detail.** During an evaluation round the
asked name is itself in the store — the store *is* the frozen set — so a neighbour search
that did not exclude it would hand the model the exam answer as a worked example, and the
round would measure the lookup rather than the classifier. `nearest(exclude_name=...)` is
what keeps the experiment honest, and D82's rule that an example drawn from the exam teaches
the exam is why it is refused at the query rather than filtered afterwards.

**Ordering is exact cosine distance over a sequential scan.** 179 rows per embedder (0018
explains the number) is microseconds, and the ANN indexes pgvector offers are approximate —
they would buy a speed nobody needs by sometimes dropping the true nearest neighbour, which
is a different experiment.

Nothing here is imported by `upto.evaluate.run_round` at module level: this module pulls
SQLAlchemy, the host Python that runs the score tests has none, and the round runner is
importable there today. The import happens inside `--rag` alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

# `prefix_kind` is resolved through the module so the map has exactly one home.
from upto.classify import embed as embedding
from upto.classify.embed import (
    DEFAULT_EMBED_KEY,
    EMBED_MODEL,
    EMBED_MODELS,
    EmbedUnavailable,
    as_literal,
    available,
    embed,
)
from upto.classify.brand_labels import BRAND_LABELED_BY, BRAND_LABELS
from upto.db import database_url
from upto.evaluate.score import TESTSET_PATH, load_testset

# One request per 32 names. The service embeds a batch in one pass, and a batch this size
# keeps the request body small enough to read in a log if it ever has to be.
EMBED_BATCH = 32

# How many cribs a prompt carries. Five is the starting value of the variable under test —
# the round file records it, so a later k is a different round rather than a silent change.
K = 5

# Who wrote the labels this loader stores. **Not the owner** — disclosed 2026-08-15: the
# frozen set was drafted by Fable 5 and cross-checked against Gemini, and never
# hand-adjudicated. It is stamped rather than left implicit because an example teaches, and a
# crib that turns out to have taught the wrong thing has to name its teacher. A later case
# book written by a different model arrives under its own value and is distinguishable here.
TESTSET_LABELED_BY = "fable5+gemini"

# 0042's two sources. `TESTSET` rows are drawn from the exam and are held out of their own
# retrieval; `BRAND` rows are D77's published brand names and are not (D88, 2026-09-03
# amendment). The strings are constants because the exclusion predicate, the two loads and the
# test that reads both `nearest()` call sites all have to spell them the same way.
TESTSET = "testset"
BRAND = "brand"


# --- the store ---------------------------------------------------------------------------


async def stored_sha(target, embed_model: str, source: str = TESTSET) -> str | None:
    """The digest this embedder's rows were built from, for ONE source, or None if it has none.

    **`source` is why 0042 exists.** The store now holds two kinds of row and they have
    unrelated provenance: a frozen-set row's digest is the test-set file's, a brand row's is the
    D77 publication's. Asking for «the digest» across both would raise the multi-digest error
    below on a perfectly healthy store, so every read names its source and the default is the
    one every existing caller meant.

    Singular on purpose: one load writes one digest across every row it owns, so more than
    one value under a single `embed_model` means something wrote outside the load, and the
    caller should be told that rather than shown whichever one sorted first. Another
    embedder's rows are invisible here — they are a different load with its own digest.
    """
    rows = (
        await _execute(
            target,
            "select distinct source_digest from example_embedding "
            " where embed_model = :model and prefix_kind = :prefix_kind "
            "   and source = :source",
            {"model": embed_model, "prefix_kind": embedding.prefix_kind(embed_model),
             "source": source},
        )
    ).all()
    if not rows:
        return None
    if len(rows) > 1:
        raise RuntimeError(
            f"example_embedding holds {embed_model} {source} rows from {len(rows)} different "
            "digests — each (embedder, source) pair is written whole by one load and by nothing "
            f"else. Re-run the {source} load."
        )
    return rows[0][0]


async def loaded_models(target) -> list[dict]:
    """Which embedders the table holds, how many rows each, and under which digest.

    The one read that deliberately crosses embedders, because that is its whole question:
    which cells of the matrix are loaded. `sha` is NULL-free by construction but is printed
    truncated by the CLI — the comparison a caller wants is *the same or not*, and 12
    characters answer it without a line that wraps.
    """
    rows = (
        await _execute(
            target,
            "select embed_model, prefix_kind, source, count(*) as rows, "
            "       count(distinct source_digest) as digests, "
            "min(source_digest) as sha, max(loaded_at) as loaded_at "
            "from example_embedding group by embed_model, prefix_kind, source "
            " order by embed_model, prefix_kind, source",
        )
    ).all()
    return [
        {
            "embed_model": row.embed_model,
            "source": row.source,
            "rows": row.rows,
            "digests": row.digests,
            "sha": row.sha,
            "loaded_at": row.loaded_at,
        }
        for row in rows
    ]


async def nearest(target, query_vector: list[float], embed_model: str, k: int = K,
                  exclude_name: str = "", prefix: str | None = None) -> list[dict]:
    """The k labelled names closest to a vector, nearest first, within one embedder.

    **`embed_model` is required and is in the WHERE clause (0019).** Two embedders' vectors
    live in unrelated spaces; a search across both would return a distance that is arithmetic
    rather than meaning, and the crib would be neighbours of nothing.

    **`exclude_name` is the leave-one-out rule and it is required in practice.** In an
    evaluation round the asked name is a row in this table; retrieving its own gold row would
    hand the model the exam answer, and the score would be a score of the lookup. Excluded
    by name rather than by id because 0019's UNIQUE collapses the frozen set's repeated
    names within an embedder — one exclusion therefore removes every copy of the asked string
    from the space being searched.

    **It excludes frozen-set rows ONLY — D88's 2026-09-03 amendment, owner-ruled 「縮」.** The
    rule above is an argument about rows drawn from the exam, and a brand row is not one: it is
    a publisher-listed fact from D77, the same kind of thing D113's aliases are, and holding it
    out removes the only row that carries the fact. Measured before the ruling: 93.7% of the
    brand-joined places are asked as exactly the brand, so the old rule made a `麥當勞` crib row
    invisible to every one of them, in production as well as in a round. The `source` column
    (0042) is what lets the predicate say «drawn from the exam» instead of «has this name».
    """
    rows = (
        await _execute(
            target,
            "select name, label, subtype from example_embedding "
            "where embed_model = :model and prefix_kind = :prefix_kind "
            # D88 (2026-09-03 amendment): the hold-out is scoped to the frozen set. A brand row
            # with the asked name STAYS — that is the ruling, not an oversight.
            "  and not (source = :testset_source and name = :exclude) "
            # Cast through text, not straight to vector: the driver would otherwise be asked
            # to send a `vector`-typed parameter and has no codec for one.
            "order by embedding <=> (:vec)::text::vector limit :k",
            {
                "model": embed_model,
                # `prefix` overrides only for the screen, which compares one embedder's two
                # conventions against each other; every product path leaves it None and gets the
                # convention the model is actually embedded under.
                "prefix_kind": prefix or embedding.prefix_kind(embed_model),
                "testset_source": TESTSET,
                "exclude": exclude_name,
                "vec": as_literal(query_vector),
                "k": k,
            },
        )
    ).all()
    # `subtype` travels with the label because the prompt renders it when it is there
    # (0018: finer granularity lives in the case book, never in D38's ten). It is NULL for
    # everything loaded from the frozen set, so today this is the shape and not yet the value.
    return [{"name": row.name, "label": row.label, "subtype": row.subtype} for row in rows]


async def replace_all(connection, rows: list[dict], vectors: list[list[float]],
                      digest: str, embed_model: str,
                      labeled_by: str = TESTSET_LABELED_BY) -> int:
    """Empty this embedder's rows and refill them, in the caller's transaction. Returns rows written.

    **The delete is scoped to `embed_model` (0019).** Reloading one embedder must not cost the
    other two their cells; the nine-cell matrix would otherwise be nine sequential loads that
    each destroyed the last.

    The frozen set repeats 7 names across 21 rows and never contradicts itself about their
    labels (measured 2026-08-15), so the collapse onto 0019's UNIQUE `(embed_model, name)` is
    lossless — but it is asserted rather than assumed, because a future amendment that *did*
    contradict itself would otherwise be resolved silently by whichever row was inserted last.
    """
    seen: dict[str, dict] = {}
    for row, vector in zip(rows, vectors):
        name = row["name"]
        previous = seen.get(name)
        if previous is not None:
            if previous["label"] != row["label"]:
                raise ValueError(
                    f"the frozen set gives {name!r} two labels — {previous['label']} and "
                    f"{row['label']}. One name is one crib (0019's UNIQUE); resolve the set."
                )
            continue
        seen[name] = {
            "label": row["label"],
            "layer": row.get("layer"),
            # The frozen set carries no finer tag, so this is NULL — the column is 0018's
            # room for a case book, not something to invent a value for here.
            "subtype": row.get("subtype"),
            "vector": vector,
        }

    await connection.execute(
        # Scoped to the convention: re-loading arctic-with-prefix must not delete the bare
        # arctic crib the experiment is comparing it against.
        # **Scoped to the source as well as the convention (0042).** Re-loading the frozen set
        # must not delete the brand rows: they are a different load with a different provenance,
        # and a whole-embedder wipe would silently empty the crib the D88 amendment exists for.
        text("delete from example_embedding where embed_model = :model "
             "  and prefix_kind = :prefix_kind and source = :source"),
        {"model": embed_model, "prefix_kind": embedding.prefix_kind(embed_model),
         "source": TESTSET}
    )
    for name, row in seen.items():
        await connection.execute(
            text(
                # `prefix_kind` is derived from the model string by `embed.prefix_kind`, never
                # passed in — a caller could otherwise label a vector with a convention it was
                # not embedded under, which is the one thing revision 0041 exists to prevent.
                "insert into example_embedding "
                "(name, label, subtype, layer, embedding, embed_model, prefix_kind, "
                " source, source_digest, source_ref, labeled_by) "
                "values (:name, :label, :subtype, :layer, (:vec)::text::vector, :model, "
                " :prefix_kind, :source, :sha, null, :by)"
            ),
            {
                "name": name,
                "label": row["label"],
                "subtype": row["subtype"],
                "layer": row["layer"],
                "vec": as_literal(row["vector"]),
                "model": embed_model,
                "prefix_kind": embedding.prefix_kind(embed_model),
                "source": TESTSET,
                "sha": digest,
                "by": labeled_by,
            },
        )
    return len(seen)


def brand_digest() -> str:
    """The digest of the brand crib's CONTENT — names and labels, not the publication's id.

    **It covers the labels, not just the names, and that is the point.** A crib goes stale when
    what it teaches changes, and an amended label changes exactly that while leaving D77's
    publication untouched. `status` compares against this, so a re-labelled row shows as STALE
    the same way an amended frozen set does, and a round refuses it rather than scoring against
    a crib that no longer says what its report will claim.
    """
    payload = "\n".join(
        "{}\t{}".format(name, BRAND_LABELS[name][0]) for name in sorted(BRAND_LABELS)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def replace_brands(connection, vectors: list[list[float]], embed_model: str) -> int:
    """Empty this embedder's BRAND rows and refill them, in the caller's transaction.

    **Scoped to `source = 'brand'` (0042).** The frozen set's rows are a different load with
    different provenance and must survive this one — and the reverse, which is why `replace_all`
    gained the same scope. Five names live under both sources by measurement (`麥味登`, `CAMA`,
    `Krispy Kreme Doughnuts`, `五桐號`, `味亦美`); 0042's key admits both, the frozen-set copy is
    held out when its name is asked and this one is not, and that difference is D88's
    2026-09-03 amendment.

    `source_ref` carries the D77 company the brand was published under, so a row states the
    published basis it rests on without anyone reading prose (D113's shape).
    """
    names = sorted(BRAND_LABELS)
    digest = brand_digest()
    await connection.execute(
        text("delete from example_embedding where embed_model = :model "
             "  and prefix_kind = :prefix_kind and source = :source"),
        {"model": embed_model, "prefix_kind": embedding.prefix_kind(embed_model),
         "source": BRAND},
    )
    for name, vector in zip(names, vectors):
        label, company = BRAND_LABELS[name]
        await connection.execute(
            text(
                "insert into example_embedding "
                "(name, label, subtype, layer, embedding, embed_model, prefix_kind, "
                " source, source_digest, source_ref, labeled_by) "
                "values (:name, :label, null, :layer, (:vec)::text::vector, :model, "
                " :prefix_kind, :source, :sha, :ref, :by)"
            ),
            {
                "name": name,
                "label": label,
                # Every brand row IS the brand layer: the string is what a sign says, which is
                # D82's own definition of that layer. Recorded rather than left NULL so a later
                # report can split the crib's contribution by layer without guessing.
                "layer": "brand",
                "vec": as_literal(vector),
                "model": embed_model,
                "prefix_kind": embedding.prefix_kind(embed_model),
                "source": BRAND,
                "sha": digest,
                "ref": "brand_registration company_name={}".format(company),
                "by": BRAND_LABELED_BY,
            },
        )
    return len(names)


# --- plumbing ----------------------------------------------------------------------------


async def _execute(target, statement: str, parameters: dict | None = None):
    """Run one statement against an engine, a connection or a session, whichever was passed.

    An engine gets its own connection for the call; anything else is already one and is used
    as it is, so a caller inside a transaction stays inside it.
    """
    if hasattr(target, "connect"):
        async with target.connect() as connection:
            return await connection.execute(text(statement), parameters or {})
    return await target.execute(text(statement), parameters or {})


async def _with_connection(work):
    engine = create_async_engine(database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await work(connection)
    finally:
        await engine.dispose()


def stored_sha_sync(embed_model: str) -> str | None:
    """`stored_sha` for a synchronous caller — the round runner, which has no loop of its own.

    A fresh engine per call, disposed per call: an asyncpg connection belongs to the loop
    that opened it, and `asyncio.run` closes that loop on the way out. The cost is one
    connect per call, and against a 7-second model call per row it does not register.
    """

    async def work(connection):
        return await stored_sha(connection, embed_model)

    return asyncio.run(_with_connection(work))


def nearest_sync(query_vector: list[float], embed_model: str, k: int = K,
                 exclude_name: str = "") -> list[dict]:
    """`nearest` for a synchronous caller. Same per-call engine, same reason as above."""

    async def work(connection):
        return await nearest(
            connection, query_vector, embed_model, k=k, exclude_name=exclude_name
        )

    return asyncio.run(_with_connection(work))


def loaded_models_sync() -> list[dict]:
    """`loaded_models` for a synchronous caller. Same per-call engine, same reason as above."""
    return asyncio.run(_with_connection(loaded_models))


# --- the load ----------------------------------------------------------------------------


async def main(embed_model: str | None = None) -> int:
    """Load one embedder's copy of the frozen set. The other embedders' rows are untouched."""
    model = embed_model or EMBED_MODEL
    rows, digest = load_testset()
    if not available(model):
        print(
            f"the embedding model {model} is not reachable — the service is behind a "
            "compose profile and is off unless a backfill or a round is running: "
            f"`docker compose --profile model up -d ollama`, then `docker compose exec ollama "
            f"ollama pull {model}`. Nothing was written.",
            file=sys.stderr,
        )
        return 3

    vectors: list[list[float]] = []
    try:
        for start in range(0, len(rows), EMBED_BATCH):
            batch = rows[start : start + EMBED_BATCH]
            # **First batch `cold`, last batch `unload_after`.** Cold because a 6.16 GB embedder
            # answers its first request with `RemoteDisconnected` rather than slowly (H52) and the
            # ordinary retry spends 2.5 s — the 4B crib died exactly there today, having written
            # nothing. Unload because the 4B and the 0.6B cannot both be resident (6.16 + 2.37 GB
            # on an 8 GB card), and a constraint that depends on somebody running the
            # configurations in the right order is not a constraint.
            vectors.extend(embed(
                [row["name"] for row in batch], model=model,
                cold=(start == 0),
                unload_after=(start + len(batch) >= len(rows)),
            ))
            print(f"  embedded {len(vectors)}/{len(rows)}", flush=True)
    except EmbedUnavailable as error:
        print(f"{error}. Nothing was written.", file=sys.stderr)
        return 3

    engine = create_async_engine(database_url(), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            written = await replace_all(connection, rows, vectors, digest, model)
    finally:
        await engine.dispose()

    print(
        f"example_embedding: {written} distinct names from {len(rows)} frozen rows, "
        f"embedded by {model}, labels by {TESTSET_LABELED_BY}, "
        f"test set sha256 {digest}"
    )
    return 0


async def main_brands(embed_model: str | None = None) -> int:
    """Load one embedder's copy of the BRAND crib. The frozen set's rows are untouched.

    Same shape and the same exit codes as `main` — 3 when the embedder is unreachable, and
    nothing written. The one difference worth knowing: this crib's digest is over its labels
    (`brand_digest`), so re-running after a label amendment is what un-stales it.
    """
    model = embed_model or EMBED_MODEL
    names = sorted(BRAND_LABELS)
    if not available(model):
        print(
            f"the embedding model {model} is not reachable. Nothing was written.",
            file=sys.stderr,
        )
        return 3

    vectors: list[list[float]] = []
    try:
        for start in range(0, len(names), EMBED_BATCH):
            batch = names[start : start + EMBED_BATCH]
            # H52's cold first call and H43's unload after the last, exactly as the frozen-set
            # load does them — the hazards are the embedder's, not the crib's.
            vectors.extend(embed(
                batch, model=model,
                cold=(start == 0),
                unload_after=(start + len(batch) >= len(names)),
            ))
            print(f"  embedded {len(vectors)}/{len(names)}", flush=True)
    except EmbedUnavailable as error:
        print(f"{error}. Nothing was written.", file=sys.stderr)
        return 3

    engine = create_async_engine(database_url(), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            written = await replace_brands(connection, vectors, model)
    finally:
        await engine.dispose()

    print(
        f"example_embedding: {written} brand names embedded by {model}, "
        f"labels by {BRAND_LABELED_BY}, brand crib sha256 {brand_digest()}"
    )
    return 0


async def status() -> int:
    """Which cells of the matrix are loaded — one line per embedder, plus the file's digest."""
    _rows, digest = load_testset()
    engine = create_async_engine(database_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            held = await loaded_models(connection)
    finally:
        await engine.dispose()
    # **The name is derived, not typed.** It read `testset_v1.json` until 2026-08-30 and printed
    # that beside v2's digest the first time a second set existed — a status line naming the wrong
    # file is worse than none, because it is the line somebody checks instead of the file.
    print(f"{os.path.basename(TESTSET_PATH)} sha256 {digest}")
    print(f"brand crib ({len(BRAND_LABELS)} names) sha256 {brand_digest()}")
    if not held:
        print("example_embedding is empty — no embedder has been loaded.")
        return 0
    for entry in held:
        # `stale` is the whole point of printing the digest: a round refuses a crib built
        # from labels the owner has since amended, and this is where that is visible before
        # a round spends minutes discovering it.
        # **The comparison is per source (0042).** A brand row measured against the test-set
        # file's digest would read STALE for ever, which is the shape of a warning nobody can
        # act on and therefore stops reading.
        want = brand_digest() if entry["source"] == BRAND else digest
        mark = "current" if entry["sha"] == want and entry["digests"] == 1 else "STALE"
        print(
            f"  {entry['embed_model']:<28} {entry['source']:<8} {entry['rows']:>4} rows  "
            f"sha {entry['sha'][:12]}  {mark}  loaded {entry['loaded_at']:%Y-%m-%d %H:%M}"
        )
    return 0


def parse(argv: list[str]) -> tuple[str, str | None]:
    """argv to (command, embed model). Raises ValueError with the message to print."""
    arguments = list(argv)
    key = DEFAULT_EMBED_KEY
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--embed":
            if index + 1 >= len(arguments):
                raise ValueError("--embed needs a key")
            key = arguments[index + 1]
            del arguments[index : index + 2]
            continue
        if argument.startswith("--embed="):
            key = argument.split("=", 1)[1]
            del arguments[index]
            continue
        index += 1
    if len(arguments) != 1 or arguments[0] not in ("load", "load-brands", "status"):
        raise ValueError(
            "usage: python -m upto.classify.examples load | load-brands [--embed "
            f"<{'|'.join(EMBED_MODELS)}>] | status"
        )
    if key not in EMBED_MODELS:
        raise ValueError(
            f"unknown embedder {key!r} — it is one of {', '.join(EMBED_MODELS)}. The key is "
            "pinned to a model string in `upto.classify.embed`, because a round is a "
            "measurement of one named model."
        )
    return arguments[0], EMBED_MODELS[key]


if __name__ == "__main__":
    try:
        command, model_string = parse(sys.argv[1:])
    except ValueError as problem:
        print(str(problem), file=sys.stderr)
        raise SystemExit(2)
    if command == "status":
        raise SystemExit(asyncio.run(status()))
    if command == "load-brands":
        raise SystemExit(asyncio.run(main_brands(model_string)))
    raise SystemExit(asyncio.run(main(model_string)))
