"""The neighbour-vote baseline — what the crib alone predicts, with no model asked.

*Owner-ruled 2026-08-19 (「量」).*

**The question.** A RAG round hands the model five labelled neighbours and asks it to classify a name.
Gemma scores 66.0% pooled that way. **How much of that is the model, and how much is the neighbours?**
If the five retrieved names already vote the right answer, the generator is decoration on a lookup.

So this predicts by **majority vote of the k nearest labelled names** and nothing else. No LLM call, no
prompt, no generation — the same crib, the same embedder, the same leave-one-out rule, the same frozen
200, scored by the same `upto.evaluate.score` layers so the number lands beside gemma's in
`app/evaluation/`.

**Leave-one-out is not optional and is the reason `exclude_name` exists.** Every one of the frozen 200
is *in* the crib, so a neighbour search that did not exclude the asked name would retrieve its own gold
row and score the lookup rather than the method. The exclusion is by name, because 0019's UNIQUE
collapses repeated names within an embedder — one exclusion removes every copy of the asked string.

**Ties go to the nearest.** With k=8 and eight distinct labels a vote can tie every way; falling back to
the single closest neighbour is the only tiebreak that needs no extra assumption, and it makes k=1 the
degenerate case of the same rule rather than a separate code path.

**What the gap to the model's score means, and what it does not.** A large gap says the generator adds
something the neighbours do not have. **A small gap does not say the generator is useless** — it says
the generator is not adding much *on this crib, at this k, on these 200 rows*. The crib is 179 rows
drawn from one publication; a bigger or better-spread crib moves the baseline and the conclusion with
it. That caveat travels with the number or the number should not be quoted.

Run (needs the stack up and the arctic crib loaded — `examples load --embed arctic`):
    docker compose exec api python -m upto.evaluate.knn_vote            # k = 1, 3, 5, 8
    docker compose exec api python -m upto.evaluate.knn_vote --k 5      # one k
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import os
from datetime import datetime, timezone

from ..classify import embed as embedding
from ..classify import examples as example_store
from ..db import session_factory
from .score import TESTSET_PATH, load_testset

# Where a round file goes. **Never under `app/`** — D63: the report is public, the raw round file is
# not, and `score` writes the public copy itself.
OUTPUT_DIR = os.environ.get("UPTO_EVALUATION_DIR", "/tmp/evaluation")

EMBED_KEY = "arctic"


def vote(neighbours: list[dict]) -> tuple[str, list[str]]:
    """The majority label among `neighbours`, ties to the nearest. Returns (label, names)."""
    labels = [row["label"] for row in neighbours]
    counts = collections.Counter(labels)
    best = max(counts.values())
    tied = [label for label, n in counts.items() if n == best]
    if len(tied) == 1:
        return tied[0], [row["name"] for row in neighbours]
    # `neighbours` is nearest-first, so the first tied label encountered is the closest one.
    for label in labels:
        if label in tied:
            return label, [row["name"] for row in neighbours]
    return labels[0], [row["name"] for row in neighbours]  # pragma: no cover — unreachable


async def one_k(session, rows: list[dict], sha: str, k: int, embed_model: str) -> str:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Embedded in one batch: the crib's own loader does the same, and per-name calls were measured
    # 10.8x slower for no different answer.
    vectors = embedding.embed([row["name"] for row in rows], model=embed_model)

    out = []
    for index, (row, vector) in enumerate(zip(rows, vectors)):
        neighbours = await example_store.nearest(
            session, vector, embed_model, k=k, exclude_name=row["name"]
        )
        if not neighbours:
            # No neighbour at all after the exclusion. Recorded as a refusal, which `score` counts as
            # wrong — the honest reading, since the method produced no answer.
            out.append({"i": index, "name": row["name"], "layer": row.get("layer"),
                        "gold": row.get("gold"), "answer": None, "outcome": "refused",
                        "examples": [], "raw": "no neighbour after leave-one-out"})
            continue
        label, names = vote(neighbours)
        out.append({"i": index, "name": row["name"], "layer": row.get("layer"),
                    "gold": row.get("gold"), "answer": label, "outcome": "category",
                    "examples": names, "raw": "vote: " + ", ".join(
                        "{}={}".format(n["name"], n["label"]) for n in neighbours)})

    document = {
        # **Named for what it is.** `candidate` is not a model here and must not read like one: no
        # generator was asked, and a reader comparing this row to gemma's needs the name to say so.
        "candidate": "knn-vote",
        "model": "none — majority vote of the k nearest labelled names",
        "prompt_version": "knn-vote_{}_k{}".format(EMBED_KEY, k),
        # **Derived, never typed.** It was the literal string `"testset_v1.json"` until
        # 2026-08-30, when a second set arrived — a hand-typed name is a claim about which file
        # was read, and `load_testset()` below reads `TESTSET_PATH`. The two could disagree and
        # only the wrong one would be recorded.
        "testset": os.path.basename(TESTSET_PATH),
        "testset_sha256_at_run": sha,
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": out,
        "rag": {"embed_model": embed_model, "embed_key": EMBED_KEY, "k": k},
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "round_knn-vote_{}-k{}.json".format(EMBED_KEY, k))
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("k={}: {} rows -> {}".format(k, len(out), path))
    return path


async def main(ks: list[int]) -> int:
    rows, sha = load_testset()
    embed_model = embedding.resolve(EMBED_KEY)
    async with session_factory()() as session:
        for k in ks:
            await one_k(session, rows, sha, k, embed_model)
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, action="append",
                        help="repeatable; default 1, 3, 5, 8")
    arguments = parser.parse_args()
    return asyncio.run(main(arguments.k or [1, 3, 5, 8]))


if __name__ == "__main__":
    raise SystemExit(cli())
