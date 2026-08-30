"""D75's backfill: one township, materialised then classified, with provenance on every row.

Run inside the stack, with the model service up (it is behind a compose profile):

    docker compose --profile model up -d ollama
    docker compose exec api python -m upto.classify.run 63000010

**With D88's crib (owner-ruled 2026-08-18, the backfill configuration):**

    docker compose exec api python -m upto.classify.run 63000090 --rag --embed arctic --k 5

`--rag` asks through `classify_name_rag` with the k nearest labelled names from
`example_embedding` in the prompt, and the row's stored `category_prompt_version` becomes the
RAG one — so provenance says which prompt decided, without anyone recording it by hand (D39,
D80). The crib must be loaded for that embedder first (`python -m upto.classify.examples load
--embed arctic`); a crib built from a different `testset_v1.json` is **refused**, not used, for
the reason D88 gives.

**The asked name is excluded from its own retrieval, and here that is not about scoring.** The
crib is the teacher's frozen set — 200 松山 names with their labels — so re-running 松山 with
retrieval would hand the model **the answer key** for any name that is also a crib row, and the
category written to `place` would be a copy of the label rather than a verdict. `nearest(
exclude_name=...)` removes every copy of the asked string within the embedder (0019's UNIQUE),
which is what keeps a re-run a re-run. The evaluation path excludes for a different reason —
a score of the lookup rather than the classifier — and the two reasons want the same line.

Two passes, in this order and for a reason:

1. **Materialise (D76).** Every `reference_place` in the township that has no `place` row
   gets one — origin `reference`, the 登錄字號 and nothing else, which is D28's shape. The
   category then has one home, 0007's own columns.
2. **Classify.** Every place in that township not yet decided is sent to the model one at a
   time — asked about **the best name this project holds** (D80: storefront sign → single
   brand → registered name), validated against D38's ten values, and written **with the
   prompt version, the model name and the asked string** (D39's condition 3, plus 0015's
   `category_input`). A legal-entity verdict is written as a **decided absence** (D79):
   provenance present, category NULL, so the next pass skips it — the measured cost this
   replaces was ~1,060 re-asks, an hour of inference per re-run. An answer outside the
   list is still not written and not coerced — a refusal is not a decision.

**The model's absence is ordinary, not an error.** The service is off unless a backfill is
running, so this exits 3 and says so, having written nothing. Exit 0 means the pass ran —
including the pass that had nothing left to do.

**Committed in batches rather than at the end**, because 3,324 places is roughly seven hours
and a crash at hour six must not throw away hour one. Each batch is a transaction; a
re-run resumes at the first unclassified row, which is what makes this safe to interrupt.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone

from sqlalchemy import text

from upto.api_common import SINGLE_BRAND, STOREFRONT
from upto.classify.classify import Classified, NoSignal, classify_name, classify_name_rag
from upto.classify.model import MODEL, available, ask, take_samples
from upto.classify.transport import reset_retries, retries_spent
from upto.classify.prompt import PROMPT_VERSION, RAG_PROMPT_VERSION
from upto.db import dispose_all, pipeline_session_factory

BATCH = 25

# **H43 — the model is unloaded every N rows, and N is 200. Owner-ruled 2026-08-30
# (「不改WSL，用卸載壓住。因為windows環境也需要用到記憶體」).**
#
# **The two measured quantities, both of them, because N is a trade between them and the next
# person cannot move it without seeing both:**
#
#   * **Cache growth per distinct prompt** — ollama keeps one saved prompt state per distinct
#     prompt, unbounded, inside the `llama-server` subprocess. Measured on the GPU box at matched
#     ~350-token prompts: **gemma2:2b 9.9 MB/row · qwen2.5:7b 3.9 MB/row**. The 7B is ~2.5×
#     *cheaper* per cached prompt than the 2B — KV geometry, not parameter count — which is the
#     opposite of what everybody assumed, so **do not scale N by model size.** (An earlier
#     15.5 MB figure came from ~120-token prompts and is withdrawn.)
#   * **What a reload costs** — one cold load on that path, measured **~10 s** (and 14.8 s when
#     the card has to evict an embedder first).
#
# So at N = 200 the worst case is the 2B: 200 × 9.9 MB ≈ **2.0 GB** of cache plus the runner's
# own footprint, against a **7.7 GiB** WSL2 ceiling the owner has ruled stays where it is — the
# Windows side needs that memory. The price is one ~10 s reload per 200 rows: on a 3,000-row
# township, 15 reloads ≈ 2.5 minutes against a pass measured in hours.
#
# **This is a robustness measure, not a speed one, and it reverses a call I made on 2026-08-28.**
# I declined a periodic reset then as a ~6.5% throughput gain not worth touching a running server.
# That was right on the evidence available. It is wrong now: on 2026-08-30 ollama was OOM-killed on
# that box holding 433 saved prompt states, and the reset empties exactly the thing that killed it.
#
# **⚠️ One thing this constant does NOT rest on, and H43 says so: nobody has explained why the
# 大同 pass survived.** 3,311 rows with no gap over 70 s would need ~21 GB at 9.9 MB/row on a
# 7.7 GiB box, and it completed. Either the growth bounds, or something frees states mid-pass. The
# `ps -o rss= -C llama-server` sampling on a real township is the experiment that settles it. Until
# it runs, 200 is a floor chosen to be obviously safe rather than a number derived from a model
# anyone has confirmed. **Read H43 before moving it.**
UNLOAD_EVERY = 200


class CribUnavailable(Exception):
    """The crib cannot be used for this run, and nothing has been written.

    Kept apart from a missing model service: that is exit 3 and ordinary (the profile is off),
    while a stale or absent crib is a thing someone has to go and load. Both leave the database
    untouched, so neither is a partial pass.
    """


async def crib_retriever(session, embed_key: str, k: int):
    """Return `async retrieve_many(names) -> list[list[tuple]]`, or raise `CribUnavailable`.

    Everything that can be wrong is checked **before the first row is asked**, because a
    backfill that discovers on row 900 that its crib was stale has written 900 rows whose
    provenance says RAG and whose neighbours were nonsense.

    Imported lazily: a plain backfill does not pull the embedding client or the evaluation
    package in at all, and `--rag` is the only thing that needs either.
    """
    from upto.classify import embed as embedding  # noqa: PLC0415
    from upto.classify import examples as example_store  # noqa: PLC0415
    from upto.evaluate.score import load_testset  # noqa: PLC0415

    embed_model = embedding.resolve(embed_key)
    if not embedding.available(embed_model):
        raise CribUnavailable(
            "the embedding model {} is not reachable — it sits behind the same compose profile "
            "as the classifier, and a RAG backfill needs both: `docker compose --profile model "
            "up -d ollama`".format(embed_model)
        )

    # D88: the crib is a derived cache of the frozen set, and a round refuses one built from a
    # different file. A backfill has more at stake than a round — it writes to `place` — so it
    # refuses on the same rule rather than a looser one.
    _rows, digest = load_testset()
    stored = await example_store.stored_sha(session, embed_model)
    if stored is None:
        raise CribUnavailable(
            "example_embedding holds no {} rows — the crib has never been loaded for this "
            "embedder. `docker compose exec api python -m upto.classify.examples load --embed "
            "{}` first; `… examples status` lists what is loaded.".format(embed_model, embed_key)
        )
    if stored != digest:
        raise CribUnavailable(
            "example_embedding's {} rows were built from test set {} and the file now hashes to "
            "{} — a label was amended under the crib. Re-load it before backfilling.".format(
                embed_model, stored, digest
            )
        )

    async def retrieve_many(names: list[str]) -> list[list]:
        """The k nearest labelled names for each of `names`, in order, one embedding request.

        **One request for the whole batch, and M12 measured what that is worth: 10.8× on this
        half** (0.481 → 0.045 s/name at 25 names per request, 2026-08-18, `probes/m12_inflight.py`).
        The cost gpu-imggen found on the model box is ~430 ms of per-*request* load on a model
        that never leaves the GPU, against ~170 ms of real work — so asking once for 25 names pays
        it once instead of 25 times. **It buys that without concurrency**: no second connection,
        no second in-flight request, and the rows are still decided in the order `pending`
        returned them, so D75's resume-at-the-first-undecided-row frontier is untouched. That is
        why this is a build decision and `--in-flight` is a ruling.

        **`embed` is the reason this is safe to batch at all.** It asserts that the reply holds one
        vector per input and that every vector has the expected width, because the API does not
        document that order is preserved — and a reply one vector short would silently pair every
        later name with its neighbour's embedding, which no test of the SQL could catch. The count
        assertion is what turns "probably in order" into "in order or it raises".

        **The k-NN stays per name, and that is not an oversight.** `exclude_name` is D88's
        leave-one-out rule and it is per name by definition; only the embedding is batched, so the
        prompt each name gets is byte-identical to the one it got before this change. The verdicts
        are therefore comparable across the change, which matters because 松山 and 南港 were
        classified either side of it.

        **What did change, and it is small:** a batch's embeddings are all fetched before its first
        generation, so a pass that dies mid-batch has spent up to 25 embeddings rather than as many
        as it had reached. Nothing is committed until the batch completes either way, so the blast
        radius of a failure is the same 25 rows it always was.
        """
        if not names:
            return []
        vectors = embedding.embed(names, model=embed_model)
        out = []
        for name, vector in zip(names, vectors):
            rows = await example_store.nearest(
                session, vector, embed_model, k=k, exclude_name=name
            )
            # (name, label, subtype) — the third slot is what `prompt._example_line` prints as
            # 「類別（細分類）」 when the store holds one, so passing it costs nothing and keeps the
            # backfill's prompt byte-identical to the evaluated one.
            out.append([(row["name"], row["label"], row.get("subtype")) for row in rows])
        return out

    return retrieve_many, embed_model


async def clear_superseded(session, township_code: str, version: str) -> int:
    """Rows generated by an older prompt are cleared so this pass re-does them.

    D39 says two prompt versions are compared by re-running rather than by trusting either;
    a column holding both answers a different question per row, which is the shape this
    project refuses everywhere else. The provenance goes with the value — all four columns
    or none, which 0007's CHECK enforces anyway.

    **The version is a parameter, so `--rag` clears the plain prompt's rows and a plain run
    clears the crib's — the same rule in both directions rather than one privileged prompt.**
    That is also what makes the ruled 松山 re-run a single command: the township's 3,290 v4 rows
    are cleared and re-decided under the crib, so `category_model` and
    `category_prompt_version` end up single-valued without anyone deleting anything by hand.
    **It is a real footgun and worth knowing before you type it:** pointing `--rag` at a
    township clears that township's existing verdicts. Nothing is lost that a completed pass
    does not replace, and an interrupted pass leaves the cleared rows pending, which the next
    run picks up (that is the same resumability the batching exists for) — but a run started
    by accident does spend the inference again.
    """
    cleared = (
        await session.execute(
            text(
                "update place p set category = null, category_model = null, "
                "category_prompt_version = null, category_generated_at = null, "
                "category_input = null "
                "from reference_place rp "
                "where rp.registry_no = p.registry_no and rp.township_code = :tc "
                "and p.category_prompt_version is not null "
                "and p.category_prompt_version <> :v returning p.id"
            ),
            {"tc": township_code, "v": version},
        )
    ).scalars().all()
    await session.commit()
    return len(cleared)


async def materialise(session, township_code: str) -> int:
    """D76: give the township's reference places their rows. Idempotent by 0007's index."""
    created = (
        await session.execute(
            text(
                "insert into place (origin, registry_no) "
                "select 'reference', rp.registry_no from reference_place rp "
                "where rp.publication_id = ("
                "  select id from place_publication order by detected_at desc limit 1"
                ") and rp.township_code = :tc "
                "and not exists ("
                "  select 1 from place p where p.origin = 'reference' "
                "  and p.registry_no = rp.registry_no"
                ") returning id"
            ),
            {"tc": township_code},
        )
    ).scalars().all()
    await session.commit()
    return len(created)


async def pending(session, township_code: str) -> list[tuple[int, str]]:
    """Places in this township not yet decided, each under the best name this project holds.

    **Undecided is `category_generated_at is null`, not `category is null`** — D79's decided
    absence carries provenance and no category, and re-asking it every pass is the measured
    hour this distinction exists to stop.

    **The name is D80's ladder: storefront sign → single brand → registered name** — the
    same precedence the screens read, because 悠旅生活事業股份有限公司 asked as itself is a
    legal entity, and asked as STARBUCKS COFFEE is a place with a category. The asked string
    goes into `category_input`, because the ladder's answer drifts as publications update
    and a stored verdict must say what it was a verdict about.
    """
    rows = (
        await session.execute(
            text(
                "select p.id, coalesce(storefront.name, brand.brand_name, rp.name) as name "
                "from place p "
                "join reference_place rp on rp.registry_no = p.registry_no "
                "left join lateral ("
                + STOREFRONT.format(registry="p.registry_no")
                + ") storefront on true "
                "left join lateral (" + SINGLE_BRAND.format(company="rp.name") + ") brand on true "
                "where p.origin = 'reference' and p.category_generated_at is null "
                "and rp.township_code = :tc "
                "and rp.publication_id = ("
                "  select id from place_publication order by detected_at desc limit 1"
                ") order by p.id"
            ),
            {"tc": township_code},
        )
    ).all()
    return [(row.id, row.name) for row in rows]


async def main(township_code: str, rag: bool = False, embed_key: str = "bge",
               k: int = 5) -> int:
    Session = pipeline_session_factory()
    retrieve_many = None
    embed_model = None
    try:
        if not available():
            print(
                f"model {MODEL} is not reachable — the service is behind a compose profile "
                "and is off unless a backfill is running. Nothing was written.",
                file=sys.stderr,
            )
            return 3

        version = RAG_PROMPT_VERSION if rag else PROMPT_VERSION

        # Everything the crib needs is checked before a single row is materialised, so a stale
        # crib costs nothing at all rather than a cleared township waiting to be re-done.
        if rag:
            async with Session() as session:
                try:
                    retrieve_many, embed_model = await crib_retriever(session, embed_key, k)
                except CribUnavailable as failure:
                    print(str(failure), file=sys.stderr)
                    return 3

        async with Session() as session:
            created = await materialise(session, township_code)
            cleared = await clear_superseded(session, township_code, version)
            todo = await pending(session, township_code)
        print(
            f"township {township_code}: {created} rows created, {cleared} cleared from an "
            f"older prompt, {len(todo)} to classify with {version}"
            + (f", {k} examples each retrieved by {embed_model}" if rag else "")
        )

        done = no_signal = refused = 0
        # Zero the retry counter so the line printed at the end is this pass's number and not a
        # total carried over from anything else that used the client in this process.
        reset_retries()
        for start in range(0, len(todo), BATCH):
            batch = todo[start : start + BATCH]
            # **Per-phase timing, added 2026-08-18 after a whole afternoon could not answer where a
            # pass's time goes.** Three passes bent — 松山 0.92 → 2.0, 北投 0.94 → 1.42, 大安
            # 1.09 → 1.72 — while the model's own reported work stayed flat at ~0.6 s a name and TCP
            # connect stayed at 0.07 ms. **The gap could not be attributed from outside**, because
            # ollama serves one request at a time: every measurement taken from a second client
            # queues behind this pass and reads the pass's own slowness back at you. That trap
            # caught both sessions investigating it. So the split is timed here, inside the only
            # client that never waits for itself, and printed per batch.
            #
            # Three phases, and they are the three candidates: the one embedding request, the k-NN
            # queries against the crib, and the model calls. Wall time for the batch is printed too,
            # so what the three do *not* account for is visible rather than inferred.
            batch_started = time.monotonic()
            retrieval_started = time.monotonic()
            neighbours = (
                None if retrieve_many is None
                else await retrieve_many([name for _, name in batch])
            )
            retrieval_s = time.monotonic() - retrieval_started
            model_s = 0.0
            results = []
            for index, (place_id, name) in enumerate(batch):
                asked_at = time.monotonic()
                # **The unload rides the LAST request of each window rather than being a call of
                # its own.** A separate unload request would be one more thing to fail, would need
                # its own retry policy, and would leave the pass in a state where the model is
                # loaded but nobody has asked it anything. `keep_alive: 0` on a request we are
                # making anyway cannot desynchronise from the work.
                asked_so_far = start + index
                unload = (asked_so_far + 1) % UNLOAD_EVERY == 0
                asker = (lambda p: ask(p, unload_after=True)) if unload else ask
                if neighbours is None:
                    outcome = classify_name(name, asker)
                else:
                    outcome = classify_name_rag(name, asker, neighbours[index])
                if unload:
                    print(
                        "  unloaded the model after {} rows (H43: keep_alive=0; ~10 s to reload)"
                        .format(asked_so_far + 1),
                        flush=True,
                    )
                model_s += time.monotonic() - asked_at
                if isinstance(outcome, Classified):
                    results.append((place_id, name, outcome.category, outcome.prompt_version))
                elif isinstance(outcome, NoSignal):
                    # A legal entity, not a place. D79: written as a decided absence —
                    # provenance and the asked string, category NULL — so the next pass
                    # skips it instead of paying for this answer again. Counted apart from
                    # a refusal because they mean opposite things.
                    results.append((place_id, name, None, outcome.prompt_version))
                    no_signal += 1
                else:
                    refused += 1
            write_started = time.monotonic()
            async with Session() as session:
                for place_id, asked, category, version in results:
                    await session.execute(
                        text(
                            "update place set category = :c, category_model = :m, "
                            "category_prompt_version = :v, category_generated_at = :t, "
                            "category_input = :i where id = :id"
                        ),
                        {
                            "c": category,
                            "m": MODEL,
                            "v": version,
                            "t": datetime.now(timezone.utc),
                            "i": asked,
                            "id": place_id,
                        },
                    )
                await session.commit()
            write_s = time.monotonic() - write_started
            batch_s = time.monotonic() - batch_started
            done += sum(1 for r in results if r[2] is not None)
            seen = done + no_signal + refused
            # `rest` is what the three phases do not explain. It should be near zero; if a pass
            # bends and `rest` is what grows, the cost is in this loop rather than in any of the
            # three, and that is a different search from any conducted on 2026-08-18.
            rest_s = batch_s - retrieval_s - model_s - write_s
            # **`model` was the largest column and the least divisible one.** The server reports its
            # own work in every reply, so the same number now splits into "the server working on
            # this prompt" and, by subtraction from `model`, "everything else the call cost".
            # `p_tok` is the prompt's token count as the server saw it — a rising `p_tok` would mean
            # the prompts themselves are growing, which is the one mechanism no external probe can
            # see, because a probe's prompt is fixed and these are not.
            served = take_samples()
            if served:
                def middle(field: str, scale: float = 1e6) -> float:
                    values = sorted(sample[field] / scale for sample in served)
                    return values[len(values) // 2]
                detail = (
                    "  p_tok {:.0f}  load {:.0f}ms  p_eval {:.0f}ms  eval {:.0f}ms"
                    "  server {:.2f}s".format(
                        middle("prompt_eval_count", 1.0), middle("load_duration"),
                        middle("prompt_eval_duration"), middle("eval_duration"),
                        sum(s["total_duration"] for s in served) / 1e9,
                    )
                )
            else:
                detail = ""
            print(
                f"  {seen}/{len(todo)}  written {done}  legal-entity {no_signal}  "
                f"unusable {refused}"
                f"  |  {batch_s / len(batch):.3f} s/name"
                f"  retrieve {retrieval_s:.2f}  model {model_s:.2f}"
                f"  write {write_s:.2f}  rest {rest_s:.2f}" + detail,
                flush=True,
            )

        # The retry count is part of the ruling, not a nicety: a link that drops one call in
        # fifty now succeeds silently and would otherwise read as a slow night. Printed even when
        # it is zero, because a line that only appears on a bad night is a line nobody trusts on
        # a good one.
        spent = retries_spent()
        print(
            f"done: {done} classified, {no_signal} decided legal entities (recorded, not "
            f"re-asked), {refused} unusable answers left pending, "
            f"{spent} connection-level retries spent"
        )
        return 0
    finally:
        await dispose_all()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="D75's backfill for one township, optionally with D88's crib."
    )
    parser.add_argument("township_code", help="the 8-digit 內政部 code, e.g. 63000090")
    parser.add_argument("--rag", action="store_true",
                        help="ask with the k nearest labelled names in the prompt (D88)")
    parser.add_argument("--embed", default="bge", dest="embed_key",
                        help="which embedder's crib to retrieve from: bge | qwen3e | arctic")
    parser.add_argument("--k", type=int, default=5,
                        help="how many neighbours to retrieve (1..20); ignored without --rag")
    arguments = parser.parse_args()
    if arguments.rag and not 1 <= arguments.k <= 20:
        # Refused rather than clamped, for the reason M10's runner refuses it: a silently
        # trimmed k would write provenance that disagreed with what was actually retrieved.
        parser.error("--k must be between 1 and 20; {} was asked for".format(arguments.k))
    raise SystemExit(asyncio.run(main(
        arguments.township_code, rag=arguments.rag, embed_key=arguments.embed_key,
        k=arguments.k,
    )))
