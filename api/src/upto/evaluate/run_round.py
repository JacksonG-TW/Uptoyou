"""D64's evaluation round: one candidate model, the 200 frozen names, one file of answers.

    docker compose --profile model up -d ollama
    docker compose exec api python -m upto.evaluate.run_round qwen   # or gemma, llama
    python3 -m upto.evaluate.run_round gemini          # host-side; the key never enters the stack
    docker compose exec api python -m upto.evaluate.run_round qwen --rag   # D88
    docker compose exec api python -m upto.evaluate.run_round qwen --rag --embed arctic
    docker compose exec api python -m upto.evaluate.run_round qwen --rag --k 8   # M10

**`--rag` is a second prompt, not a second runner.** It asks through
`classify_name_rag` with five retrieved neighbours from `example_embedding` (D88), stamps
`RAG_PROMPT_VERSION`, and therefore writes `round_<name>_v5-rag-2026-08-15.json` — a
different file, so resume, model-pinning and the scorer all work unchanged and no round is
ever mixed with a plain one.

**`--embed` is the second axis, and the prompt version does not move with it.** D88's
amendment, owner-ruled 2026-08-17: the matrix is 3 embedders × 3 generators, and the embedder
is a *retrieval* variable — the prompt text is byte-identical whichever one retrieved the
cribs, so bumping `RAG_PROMPT_VERSION` would claim a change that did not happen. The file
name carries the embedder instead: **`bge` keeps the existing
`round_<name>_v5-rag-2026-08-15.json`**, because the three rounds already scored under it
were embedded by bge-m3 and are the matrix's first column — renaming them would be re-running
them for nothing — and every other embedder appends its key,
`round_<name>_v5-rag-2026-08-15_<key>.json`. The round document records `rag.embed_model` and
`rag.embed_key`, and a stored round refuses to be continued by a different embedder for the
same reason it refuses a different generator: one round is one measurement.

**`--k` is M10's third axis, owner-ruled, and it follows `--embed`'s rules exactly.** The number
of retrieved cribs is a retrieval variable too, so the prompt version does not move with it
either; **k=5 keeps writing the file name it already writes** (every round on disk was retrieved
at five, and renaming them would be re-running them for nothing) and any other k appends `_k<k>`
after the embedder — `round_gemma_v5-rag-2026-08-15_arctic_k1.json`, or
`round_gemma_v5-rag-2026-08-15_k8.json` for bge. `rag.k` records the real k, 1 to 20; outside
that it is refused rather than clamped, and a stored round refuses to be continued at a
different k for the reason it refuses a different embedder: one round is one measurement.

**`gemini --rag` is refused, and it is a rule rather than a limitation.** The crib carries
the owner's gold labels, and gold does not leave this machine; the hosted baseline stays at
the plain prompt permanently. (It is also true that the database publishes no host port, so
a host-side round could not reach the store anyway — but the rule stands on the first
reason, which would survive someone publishing the port.)

Five candidates: D64's local slate — `qwen` · `gemma` · `llama`, three contenders from three
makers, all self-hostable per D63 — plus `gemini`, the hosted baseline that enters the
evaluation and nothing else (D84's last line), plus `qwen7b`, a fourth
contender since D64's gate was amended on 2026-08-30 to name the machine the DAG calls (see
`LOCAL_MODELS`). All are asked
through `upto.classify.classify_name`, so a round measures **the shipped validation path**,
not a second copy of it written for the evaluation — an answer this runner accepts is exactly
an answer the backfill would have written, and an answer it refuses is a row the backfill
would have left pending.

**The round is a file, not a number.** Every row is kept — asked name, layer, the gold it was
asked under, the answer, the outcome — because a score with no rows behind it cannot be
argued with, and D64's rule is one public commit per round. Scoring is a separate module
reading this file: `python -m upto.evaluate.score <round-file>`.

**Resumable, and the resume rule is deliberately strict.** The file is written every 10
answers and the next run continues at the first unanswered row — 200 names at the probed
7.24 s is ~24 minutes for qwen, and a free-tier hosted round is bounded by a daily quota
rather than by time, so an interrupted round that had to start over would be a round nobody
runs twice. A stored answer is inherited **only** while it sits in an unbroken prefix and the
name at its index still reads the same; the frozen set is frozen against re-drawing, not
against the owner's corrections, and an answer about an amended string is not an answer about
this row.

**The model string is pinned before the round, never negotiated during it.** D84's instrument
walks an alias chain because it wants freshness; an evaluation wants the opposite, and a round
that silently changed model half-way would produce a score that is a score of nothing. If the
pinned model stops answering, the round saves and stops, and a stored round refuses to be
continued by a different model.

Exit codes: **0** the round is complete · **1** the candidate failed in a way that is not a
wait (the message says how) · **2** usage, a missing key, or a round file that disagrees with
what was asked for · **3** come back later — the model service is down or the daily quota is
spent — **and progress is saved**, which is the ordinary case rather than a failure, the same
distinction `ingest_run` draws between no change and failed.

No credential is ever printed, stored in the round file, or passed into a subprocess: the
Gemini key is read from `~/.keys/gemini_api_key` (override `UPTO_GEMINI_KEY_FILE`) and held
in memory for the run.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from upto.classify.classify import Classified, NoSignal, classify_name, classify_name_rag
# `upto.classify.embed` is standard library only — it reaches Ollama over urllib and nothing
# else — so naming it here does not break the import discipline `examples` is kept out for.
from upto.classify.embed import DEFAULT_EMBED_KEY, EMBED_MODELS
from upto.classify.prompt import NO_SIGNAL, PROMPT_VERSION, RAG_PROMPT_VERSION
from upto.evaluate.score import TESTSET_PATH, load_testset

SAVE_EVERY = 10

# D88's k, recorded in every round file it produces. Changing it is a different round, not a
# tweak — which is why the number is written into the document rather than only living here.
RAG_K = 5

# M10's ceiling. A k above this is refused rather than clamped: 20 cribs is already most of a
# prompt, and silently trimming a typo'd `--k 200` would write a file whose `rag.k` disagreed
# with the command that produced it. The floor is 1 — `--k 0` is a plain round asked for under
# a retrieval file name, which is the one thing the naming rule exists to prevent.
RAG_K_MAX = 20

# **H43 — the model is unloaded every N answers, and for prompt v7 N is 50.**
#
# **This runner did not have the unload and the classifier did, which is the whole reason it
# mattered.** `classify/run.py` has carried `UNLOAD_EVERY` since 2026-08-30; a round is the same
# workload — one distinct prompt per row against a resident model — and nobody carried the fix
# across. Measured on the live v7 gemma round before it was stopped: **one runner, 77 generate
# calls, `llama-server` 1,966 → 5,856 MB, the box down to 130 MB available.** A 200-row round
# needs ~13 GB at that rate on a 7.7 GiB box: it cannot finish.
#
# **N is a property of the PROMPT VERSION, not of the model, and that is the rule to carry.** The
# per-row cache cost measured ~17 MB on v6's real prompts and ~65–78 MB on v7's. **Re-measure N
# whenever the prompt moves** — a prompt edit is a memory change, which is not how anyone reads a
# prompt edit.
#
# **⚠️ The 4× is NOT explained by the prompt being longer, and I have checked rather than assumed.**
# Rendered and counted: `RAG_INSTRUCTION` went **389 → 593** tokens v6 → v7 (×1.53), and
# `INSTRUCTION` 519 → 697 (×1.34). A KV cache is **linear** in tokens, so ×1.5 of prompt should be
# ×1.5 of cache and not ×4. Two things could account for the rest and neither is established: the
# sample was taken in the window where the warm-up had left **stacked runners** with
# `keep_alive: 30m` (since fixed), so RSS attributed to one runner may include a neighbour's; and
# the same v6 prompt measured 9.9 MB synthetic against ~17 MB live, so the instrument itself
# carries a ~1.7× spread. **50 is therefore a floor chosen to be obviously safe on tonight's worst
# number, not a figure derived from an understood model.** Read H43 before raising it.
UNLOAD_EVERY = 50

# D64's local slate, owner-ruled 2026-08-14: three contenders, three makers, all under the
# 4 GB EC2 class's ~2.5 GB resident line (gemma3:4b failed that gate and was replaced by
# gemma2:2b). One CLI name per model; the string is pinned here and written into the round.
#
# **`qwen7b` is a FOURTH CONTENDER since 2026-08-30, and it was a ceiling probe for six hours in
# between — the change is a ruling, not a correction.** It was added under D64's original gate,
# which it fails: ~4.7 GB resident against a ~2.5 GB line written for the 4 GB EC2 class the
# product was once going to be deployed on. **The owner then amended D64** (「我想先測出贏多少，
# 這才是決定性的關鍵，外接機器沒關係，可以證明我們是混和雲」): the resident gate is the VRAM of the
# machine the DAG actually calls — the GPU box, 8 GB, with 7B + arctic measured at 6.9 GB — and
# the model is chosen on measured lift under one prompt version with the 3× cost column beside it.
# So the slate is four, and the number that decides is the lift, not the size.
#
# **The gate names a machine now, and that is the load-bearing part.** "~2.5 GB" with no machine
# named is exactly what let a 7B look like a contender and then like a probe within one day.
#
# **⚠️ `qwen` (3B) is under the Qwen RESEARCH LICENSE — non-commercial. Read H63 before it goes
# anywhere near a DAG or a shipped image.** Evaluation rounds are exactly the permitted use, so
# its presence here is fine and its presence in `classify.run`'s default would not be. `qwen7b`
# and `llama` are Apache-2.0 and carry no such limit; `gemma2` is under Google's Gemma terms.
LOCAL_MODELS = {
    "qwen": "qwen2.5:3b-instruct-q4_K_M",
    "gemma": "gemma2:2b",
    "llama": "llama3.2:3b",
    # **The tag is provisional until the GPU session confirms what it pulled** (asked
    # 2026-08-30). Written in the parallel spelling of the 3B line above; if the box holds a
    # differently-spelled tag, this string is what the round records and the two must be made to
    # agree HERE rather than by passing an override, because the round file's `model` field is
    # the only durable record of what answered.
    "qwen7b": "qwen2.5:7b-instruct-q4_K_M",
}
OLLAMA_URL = os.environ.get("UPTO_OLLAMA_URL", "http://ollama:11434").rstrip("/")
OLLAMA_TIMEOUT_S = int(os.environ.get("UPTO_OLLAMA_TIMEOUT", "180"))

# **Pinned, and no fallback chain — owner-ruled 2026-08-14 after measuring this account's free
# tier: `flash` and `3.5-flash` allow 20 requests a day, `flash-lite` allows 500.** A 200-name
# round does not fit in 20, so the chain D84's instrument uses would have spent its daily
# allowance on the first 20 names and finished the round on a *different* model — a score
# belonging to neither. The instrument wants freshness and availability; an evaluation wants
# one model string, fixed before the round and written into the file.
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
GEMINI_KEY_FILE = os.environ.get("UPTO_GEMINI_KEY_FILE", "~/.keys/gemini_api_key")
GEMINI_TIMEOUT_S = int(os.environ.get("UPTO_GEMINI_TIMEOUT", "60"))
# 500 a day is room to spare for 200 names, so the gap is politeness against the per-minute
# allowance rather than rationing: 2 s puts a round at ~7 minutes of waiting.
GEMINI_SLEEP_S = float(os.environ.get("UPTO_GEMINI_SLEEP", "2"))
GEMINI_TRIES = 5


class ComeBackLater(Exception):
    """The candidate cannot answer now and will be able to later. Progress is saved: exit 3."""


class CandidateFailed(Exception):
    """The candidate failed in a way waiting will not fix: exit 1."""


class UsageError(Exception):
    """The run was asked for something it cannot do — a bad name, no key: exit 2."""


# --- where the rounds live ------------------------------------------------------------


def evaluation_dir(start: str | None = None) -> str:
    """The repo-root `evaluation/` directory, resolved without pointing above `app/`.

    `UPTO_EVALUATION_DIR` wins outright — it is what the container uses, where the checkout's
    shape is not visible. Otherwise walk up from this file for a repository root (a `.git`,
    or the private repo's `app/` + `doc/` pair); the same walk lands on the public repo's own
    root after D47's extract, because there `app/` *is* the root. Failing both, `./evaluation`
    under the current directory — a stated fallback rather than a guess that writes somewhere
    surprising.
    """
    override = os.environ.get("UPTO_EVALUATION_DIR")
    if override:
        return os.path.abspath(os.path.expanduser(override))
    here = start or os.path.dirname(os.path.abspath(__file__))
    path = here
    while True:
        if os.path.isdir(os.path.join(path, ".git")) or (
            os.path.isdir(os.path.join(path, "app")) and os.path.isdir(os.path.join(path, "doc"))
        ):
            return os.path.join(path, "evaluation")
        parent = os.path.dirname(path)
        if parent == path:
            return os.path.abspath("evaluation")
        path = parent


def round_path(candidate: str, prompt_version: str = PROMPT_VERSION,
               embed_key: str | None = None, k: int | None = None) -> str:
    """Where a round is written. `embed_key` is D88's second axis and `bge` is spelled by omission.

    The default embedder appends nothing, and that is a compatibility rule rather than
    tidiness: `round_qwen_v5-rag-2026-08-15.json` and its two siblings are already scored and
    committed as the bge column of the matrix (2026-08-15), and a suffix here would make them
    unreachable by the runner that wrote them.

    **`k` is M10's third axis and `5` is spelled by omission, for the same compatibility
    reason.** Every round on disk was retrieved at k=5, so k=5 must keep writing the name it
    already writes — bge at k=5 stays `round_<name>_v5-rag-2026-08-15.json`. Any other k
    appends `_k<k>` *after* the embedder, so the suffix order reads the way the matrix does:
    generator, prompt, embedder, k.
    """
    suffix = ""
    if embed_key and embed_key != DEFAULT_EMBED_KEY:
        suffix = "_" + embed_key
    if k is not None and k != RAG_K:
        suffix += f"_k{k}"
    return os.path.join(evaluation_dir(), f"round_{candidate}_{prompt_version}{suffix}.json")


def save(path: str, document: dict) -> None:
    """Write whole, then move into place — a crash mid-write must not eat the round so far."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".partial"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    os.replace(temporary, path)


# --- the resume decision, pure so it can be tested --------------------------------------


def resume_point(stored: list[dict], gold_rows: list[dict]) -> tuple[list[dict], int]:
    """Which stored answers survive, and where the next ask starts.

    Only an unbroken prefix is inherited, and only while the stored row's name still matches
    the set at that index. A gap means the file was hand-edited or a save was lost — asking
    around it would produce a round whose row order no longer means what the index says; a
    name change means the owner amended the set and that answer is about a different string.
    Both cases cost re-asking a suffix, which is the cheap half of the trade.
    """
    answered = {row["i"]: row for row in stored if isinstance(row.get("i"), int)}
    kept: list[dict] = []
    for index, gold_row in enumerate(gold_rows):
        row = answered.get(index)
        if row is None or row.get("name") != gold_row.get("name"):
            break
        kept.append(row)
    return kept, len(kept)


# --- the candidates ---------------------------------------------------------------------


class Local:
    """A local candidate, asked over Ollama's HTTP API. Standard library, like everything here."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = LOCAL_MODELS[name]

    def check(self) -> None:
        try:
            with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=10) as response:
                tags = json.load(response)
        except (urllib.error.URLError, OSError, ValueError) as error:
            # **A name that does not resolve and a service that is off raise the same `URLError`,
            # and exit 3 says "ordinary, come back later" for both.** That bit on 2026-08-19: the
            # `edge`/`data` network split left a four-day-old `ollama` container alone on
            # `upto_default`, so `ollama:11434` stopped resolving from the api container — and a
            # round would have reported the designed quiet day for a misconfiguration. The exit
            # code is unchanged (waiting genuinely is the right action for both), but the sentence
            # now says which, because "the service is off" sends the reader to the wrong command.
            if isinstance(getattr(error, "reason", None), socket.gaierror):
                raise ComeBackLater(
                    f"the NAME in {OLLAMA_URL} does not resolve ({error.reason}) — this is DNS, "
                    "not a service that is off. Most likely the container is not on the same "
                    "compose network as this one: `docker compose --profile model up -d "
                    "--force-recreate ollama` puts it back on `data`. A network change only covers "
                    "the containers it recreates."
                )
            raise ComeBackLater(
                f"the model service at {OLLAMA_URL} is not answering ({error}). It sits behind "
                "a compose profile and is off unless a backfill or a round is running: "
                "`docker compose --profile model up -d ollama`."
            )
        held = [entry.get("name", "") for entry in tags.get("models", [])]
        if not any(entry.startswith(self.model.split(":")[0]) for entry in held):
            raise ComeBackLater(
                f"{OLLAMA_URL} is up but does not hold {self.model} — pull it once: "
                f"`docker compose exec ollama ollama pull {self.model}`."
            )

    def ask(self, prompt: str, unload_after: bool = False) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            # temperature 0 and a short budget: the answer is a few characters, and a
            # re-run of the same prompt version should land as close to identical as this
            # kind of tool gets. D39 admits it is not fully reproducible.
            "options": {"temperature": 0, "num_predict": 8},
        }
        if unload_after:
            # H43 — see `UNLOAD_EVERY` below. The classifier has carried this since
            # 2026-08-30; the round runner did not, and a v7 gemma round took the box to
            # 130 MB free in 77 requests before anyone noticed.
            payload["keep_alive"] = 0
        body = json.dumps(payload).encode()
        request = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_S) as response:
                return json.load(response)["response"]
        except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
            raise ComeBackLater(f"{self.model} stopped answering: {error}")


class Gemini:
    """The hosted baseline: one pinned model, plain generation, no search grounding, temp 0.

    **Ungrounded on purpose, and not only because the free tier refuses grounding (D84).** The
    evaluation asks what a model knows about a name, which is the same question the local
    candidate is asked; handing one candidate a search engine would measure a different task
    and the two scores would not be comparable.
    """

    name = "gemini"

    def __init__(self, key: str) -> None:
        self._key = key  # held in memory for the run; never printed, never written
        self.model = GEMINI_MODEL
        self._last_call = 0.0

    def check(self) -> None:
        pass  # nothing to check without spending a call, and calls are the rationed thing

    def _post(self, prompt: str) -> str:
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0},
        }
        request = urllib.request.Request(
            GEMINI_ENDPOINT.format(self.model),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=GEMINI_TIMEOUT_S) as response:
            reply = json.load(response)
        candidate = (reply.get("candidates") or [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])
        return "\n".join(part["text"] for part in parts if "text" in part).strip()

    def ask(self, prompt: str, unload_after: bool = False) -> str:
        """`unload_after` is accepted and ignored — there is nothing local to unload.

        **Accepted rather than absent, and that is the bug this signature prevents.** The round
        loop hands `unload_after=True` on every Nth row without knowing which candidate it holds;
        a hosted candidate whose `ask` lacked the keyword would raise `TypeError` at row 50 of a
        gemini round — after fifty of a rationed daily quota had been spent. Found by
        `test_classify_rag` before it could happen.
        """
        gap = GEMINI_SLEEP_S - (time.monotonic() - self._last_call)
        if gap > 0:
            time.sleep(gap)
        delay = 8.0
        last: Exception | None = None
        for attempt in range(GEMINI_TRIES):
            try:
                answer = self._post(prompt)
            except urllib.error.HTTPError as error:
                last = error
                if error.code not in (429, 500, 503):
                    detail = error.read().decode("utf-8", "replace")[:300]
                    raise CandidateFailed(f"HTTP {error.code} from the Gemini API: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
                # OSError is load-bearing on the host: its Python 3.9 raises socket.timeout,
                # which is an OSError and NOT TimeoutError until 3.10 — without it a mid-round
                # read timeout escaped the retry loop whole (measured: a round died at 40/200).
                last = error
            else:
                self._last_call = time.monotonic()
                return answer
            if attempt < GEMINI_TRIES - 1:
                print(f"  (rate-limited or unreachable, waiting {delay:.0f}s — "
                      f"attempt {attempt + 2} of {GEMINI_TRIES})", file=sys.stderr)
                time.sleep(delay)
                delay *= 2
        raise ComeBackLater(
            f"{self.model} refused {GEMINI_TRIES} times in a row ({last}) — on this account's "
            "free tier that is the daily allowance spent (measured: 500 requests a day for "
            "flash-lite). Answers so far are saved; re-run tomorrow and the round continues "
            "where it stopped."
        )


def read_key(path: str = GEMINI_KEY_FILE) -> str:
    expanded = os.path.expanduser(path)
    key = ""
    if os.path.exists(expanded):
        with open(expanded, encoding="utf-8") as handle:
            key = handle.read().strip()
    if not key:
        raise UsageError(
            f"no key at {expanded} (missing or empty) — save one there, chmod 600. It is never "
            "stored in this repository, never printed, and never written into a round file."
        )
    return key


def build_candidate(name: str):
    if name in LOCAL_MODELS:
        return Local(name)
    if name == "gemini":
        return Gemini(read_key())
    raise UsageError(
        f"unknown candidate {name!r} — it is one of {', '.join(LOCAL_MODELS)}, or `gemini`"
    )


# --- one row --------------------------------------------------------------------------


def answer_row(index: int, gold_row: dict, ask, examples_for=None) -> dict:
    """Ask one name through the shipped validation path and record what came back.

    The three outcomes are the three `classify_name` returns and they are kept apart for the
    reason D79 keeps them apart in the database: a legal-entity verdict is a decision the
    model reached, a refusal is an answer nobody can use, and collapsing them would make the
    score unable to tell a confident wrong answer from a broken one.

    `examples_for` is D88's retrieval, absent by default. Given, it returns this name's
    neighbours and the row records **which names were offered** — labels are already in the
    store, and keeping the asked names is what lets a wrong answer be traced to a misleading
    crib rather than only to the model.
    """
    examples: list[tuple] = []
    if examples_for is None:
        outcome = classify_name(gold_row["name"], ask)
    else:
        examples = examples_for(gold_row["name"])
        outcome = classify_name_rag(gold_row["name"], ask, examples)
    row = {
        "i": index,
        "name": gold_row["name"],
        "layer": gold_row.get("layer"),
        "gold": gold_row.get("label"),
        "answer": None,
        "outcome": "refused",
    }
    if examples_for is not None:
        # Names only. The labels and subtypes are in the store under those names, so keeping
        # them here would duplicate a table into 200 round rows to say nothing new.
        row["examples"] = [example[0] for example in examples]
    if isinstance(outcome, Classified):
        row["answer"] = outcome.category
        row["outcome"] = "category"
    elif isinstance(outcome, NoSignal):
        # The sentinel is a label in the frozen set (D82), so it is recorded as the answer it
        # is — a verdict — and not as an absence the scorer would have to reconstruct.
        row["answer"] = NO_SIGNAL
        row["outcome"] = "no_signal"
    else:
        # The raw string is kept, truncated: a refusal that cannot be read back costs a full
        # re-run of the round to diagnose, and a round is minutes-to-a-day of work.
        row["raw"] = (outcome.raw or "")[:200]
    return row


def rag_examples(digest: str, embed_model: str, k: int = RAG_K):
    """D88's per-name crib lookup, or a UsageError if the store cannot honestly supply one.

    **Imported here rather than at module level, and that is load-bearing.** The example
    store reaches SQLAlchemy; the host Python that runs `test_evaluate_score.py` has none,
    and that test asserts this module imports nothing beyond the standard library and
    `upto.classify`. A plain round must stay runnable there.

    The digest check is the stale-cache refusal, and after 0019 it is **per embedder**: the
    table is a derived copy of `testset_v1.json`, D82 freezes that file against re-drawing but
    not against the owner's corrections, and a round asked with cribs built from amended-away
    labels would report a number about neither set. Each embedder's rows carry their own
    digest, so a fresh load of one says nothing about the staleness of another.

    Both the query vector and the neighbour search name the same `embed_model`. That is the
    whole of what keeps a round inside one vector space: an embedder asked for the query and
    a different one's rows searched would return five well-formed neighbours of nothing.
    """
    from upto.classify import embed as embedding
    from upto.classify import examples as example_store

    stored = example_store.stored_sha_sync(embed_model)
    if stored is None:
        raise UsageError(
            f"example_embedding holds no {embed_model} rows — D88's crib has never been loaded "
            "for this embedder. Run `docker compose exec api python -m upto.classify.examples "
            f"load --embed <key>` first; `… examples status` lists what is loaded."
        )
    if stored != digest:
        raise UsageError(
            f"example_embedding's {embed_model} rows were built from test set {stored} and the "
            f"file now hashes to {digest} — the owner amended a label under the crib. Re-run "
            "`docker compose exec api python -m upto.classify.examples load --embed <key>`."
        )

    def examples_for(name: str) -> list[tuple[str, str]]:
        try:
            vector = embedding.embed([name], model=embed_model)[0]
        except embedding.EmbedUnavailable as error:
            raise ComeBackLater(
                f"{error} — the embedding model sits behind the same compose profile as the "
                "candidate: `docker compose --profile model up -d ollama`."
            ) from None
        # Leave-one-out: the asked name is itself in the store, and retrieving its own gold
        # row would hand the model the exam answer (D82, D88).
        neighbours = example_store.nearest_sync(
            vector, embed_model, k=k, exclude_name=name
        )
        # Three-element cribs: the prompt prints the subtype when the store holds one, and
        # NULL everywhere is what the frozen set gives today (0018).
        return [(row["name"], row["label"], row["subtype"]) for row in neighbours]

    return examples_for


USAGE = (
    "usage: python -m upto.evaluate.run_round <qwen|gemma|llama|gemini> "
    "[--rag [--embed <{}>] [--k <1-{}>]]".format("|".join(EMBED_MODELS), RAG_K_MAX)
)


def main(argv: list[str]) -> int:
    arguments = list(argv)
    rag = "--rag" in arguments
    if rag:
        arguments.remove("--rag")
    embed_key: str | None = None
    k_asked: str | None = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--embed":
            if index + 1 >= len(arguments):
                print(USAGE, file=sys.stderr)
                return 2
            embed_key = arguments[index + 1]
            del arguments[index : index + 2]
            continue
        if argument.startswith("--embed="):
            embed_key = argument.split("=", 1)[1]
            del arguments[index]
            continue
        if argument == "--k":
            if index + 1 >= len(arguments):
                print(USAGE, file=sys.stderr)
                return 2
            k_asked = arguments[index + 1]
            del arguments[index : index + 2]
            continue
        if argument.startswith("--k="):
            k_asked = argument.split("=", 1)[1]
            del arguments[index]
            continue
        index += 1
    if len(arguments) != 1 or arguments[0].startswith("-"):
        print(USAGE, file=sys.stderr)
        return 2
    if embed_key is not None and not rag:
        # An embedder is a retrieval setting and a plain round retrieves nothing. Accepting it
        # here would write a round file whose name and metadata claimed a variable the run
        # never used.
        print(
            "--embed only means something with --rag: a plain round retrieves no examples, so "
            "there is no embedding model in it to choose.",
            file=sys.stderr,
        )
        return 2
    if k_asked is not None and not rag:
        # Same reason as `--embed`, and M10 does not change it: a plain round retrieves nothing,
        # so there is no number of examples in it to set.
        print(
            "--k only means something with --rag: a plain round retrieves no examples, so there "
            "is no number of them to choose.",
            file=sys.stderr,
        )
        return 2
    k = RAG_K
    if k_asked is not None:
        # Strict digits, then the range. `--k 3.5` and `--k five` are typos, and a typo that
        # became a default would write a k=5 round under a command that asked for something
        # else — the same failure the empty `--embed ''` refusal exists to stop.
        if not k_asked.isdigit() or not 1 <= int(k_asked) <= RAG_K_MAX:
            print(
                f"--k takes a whole number from 1 to {RAG_K_MAX} — got {k_asked!r}. It is the "
                "number of retrieved cribs per name (D88), and it is refused rather than "
                "clamped so `rag.k` in the round file is always what was asked for.",
                file=sys.stderr,
            )
            return 2
        k = int(k_asked)
    # `is None`, not `or`: an empty `--embed ''` is a typo to refuse, not an omission to
    # default. Falling back would run a bge round under a command that asked for something.
    if embed_key is None:
        embed_key = DEFAULT_EMBED_KEY
    if rag and embed_key not in EMBED_MODELS:
        print(
            f"unknown embedder {embed_key!r} — it is one of {', '.join(EMBED_MODELS)}. The key "
            "is pinned to a model string in `upto.classify.embed`, because a round is a "
            "measurement of one named model.",
            file=sys.stderr,
        )
        return 2
    name = arguments[0]
    if rag and name == "gemini":
        # Refused before the key is even read. The crib is the owner's gold labels and gold
        # never leaves this machine (D88), so the hosted baseline is a plain-prompt candidate
        # permanently. It is separately true that the database publishes no host port.
        print(
            "gemini does not run with --rag: the retrieved examples are the owner's own gold "
            "labels, and gold does not leave this machine (D88). The hosted baseline stays at "
            "the plain prompt.",
            file=sys.stderr,
        )
        return 2
    try:
        candidate = build_candidate(name)
    except UsageError as error:
        print(str(error), file=sys.stderr)
        return 2

    gold_rows, digest = load_testset()
    prompt_version = RAG_PROMPT_VERSION if rag else PROMPT_VERSION
    path = round_path(name, prompt_version, embed_key if rag else None, k if rag else None)

    examples_for = None
    document = {
        "candidate": name,
        "model": getattr(candidate, "model", None),
        "prompt_version": prompt_version,
        "testset": os.path.basename(TESTSET_PATH),
        "testset_sha256_at_run": digest,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished_at": None,
        "rows": [],
    }
    if rag:
        embed_model = EMBED_MODELS[embed_key]
        try:
            examples_for = rag_examples(digest, embed_model, k)
        except UsageError as error:
            print(str(error), file=sys.stderr)
            return 2
        # `embed_model` is the pinned string and `embed_key` is what was typed. Both are kept:
        # the string is what a later reader has to match a vector space against, the key is
        # what names this cell of the matrix and what the file name carries. `k` is the real k
        # this run retrieves with, never the constant — M10's scan is unreadable otherwise.
        document["rag"] = {"embed_model": embed_model, "embed_key": embed_key, "k": k}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            existing = json.load(handle)
        if existing.get("candidate") != name or existing.get("prompt_version") != prompt_version:
            print(
                f"{path} holds a {existing.get('candidate')} round at prompt "
                f"{existing.get('prompt_version')}, and this is {name} at {prompt_version}. "
                "Move it aside rather than mixing two rounds in one file.",
                file=sys.stderr,
            )
            return 2
        stored_model = existing.get("model")
        if stored_model and stored_model != candidate.model:
            print(
                f"{path} was answered by {stored_model} and this run would answer with "
                f"{candidate.model}. One round is one model — move the file aside and start a "
                "round for the new one.",
                file=sys.stderr,
            )
            return 2
        if rag:
            # The third pin, and it is the same rule as the other two: one round is one
            # measurement. A file half-answered under bge-m3's neighbours and half under
            # arctic's would score a candidate that never existed — and unlike the generator,
            # this one is invisible in the file name for the default embedder, which is
            # exactly why it has to be refused from the metadata.
            stored_embed = (existing.get("rag") or {}).get("embed_model")
            if stored_embed and stored_embed != embed_model:
                print(
                    f"{path} was answered with cribs retrieved by {stored_embed} and this run "
                    f"would retrieve with {embed_model}. One round is one embedding model — "
                    "move the file aside and start a round for the new one.",
                    file=sys.stderr,
                )
                return 2
            # The fourth pin, M10's, and it is the embed refusal's shape for the embed
            # refusal's reason: a file half-answered with one crib and half with eight scores a
            # candidate that never existed. k=5 is invisible in the file name by the
            # compatibility rule, so like the embedder it has to be refused from the metadata.
            stored_k = (existing.get("rag") or {}).get("k")
            if stored_k is not None and stored_k != k:
                print(
                    f"{path} was answered with {stored_k} retrieved examples per name and this "
                    f"run would retrieve {k}. One round is one k — move the file aside and "
                    "start a round for the new one.",
                    file=sys.stderr,
                )
                return 2
        kept, start = resume_point(existing.get("rows", []), gold_rows)
        # The stored document wins, then this run's own facts are written back over it — the
        # model it will actually answer with, and D88's retrieval settings, which describe
        # this run rather than the one that wrote the file.
        rag_settings = document.get("rag")
        document = dict(existing, rows=kept, finished_at=None)
        document["model"] = candidate.model
        if rag_settings is not None:
            document["rag"] = rag_settings
        dropped = len(existing.get("rows", [])) - len(kept)
        print(f"resuming {path}: {start} answers kept"
              + (f", {dropped} dropped (a gap, or the set was amended under them)"
                 if dropped else "")
              + f", {len(gold_rows) - start} to ask")
    else:
        start = 0
        print(f"new round: {name} against {len(gold_rows)} names, prompt {prompt_version}"
              + (f", {k} examples each retrieved by {embed_model}" if rag else ""))

    try:
        candidate.check()
    except ComeBackLater as error:
        print(str(error), file=sys.stderr)
        return 3

    rows = document["rows"]
    status = 0
    try:
        for index in range(start, len(gold_rows)):
            # **The unload rides the last request of each window** — a field on a request we are
            # making anyway, so it cannot desynchronise from the work. `index` is the row's place
            # in the FROZEN SET, not in this run, so a resumed round unloads on the same rows the
            # first attempt would have: a round that resumes at row 120 must not start its window
            # count from zero and drift.
            unload = (index + 1) % UNLOAD_EVERY == 0
            asker = (lambda p: candidate.ask(p, unload_after=True)) if unload else candidate.ask
            rows.append(answer_row(index, gold_rows[index], asker, examples_for))
            if unload:
                print(f"  unloaded the model after row {index + 1} "
                      f"(H43: keep_alive=0, ~10 s to reload)", flush=True)
            document["model"] = candidate.model
            if len(rows) % SAVE_EVERY == 0:
                save(path, document)
                decided = sum(1 for row in rows if row["outcome"] != "refused")
                print(f"  {len(rows)}/{len(gold_rows)}  decided {decided}  "
                      f"unusable {len(rows) - decided}", flush=True)
    except ComeBackLater as error:
        print(f"\n{error}", file=sys.stderr)
        status = 3
    except CandidateFailed as error:
        print(f"\n{error}", file=sys.stderr)
        status = 1
    except KeyboardInterrupt:
        print("\ninterrupted — answers so far are saved; re-run to continue", file=sys.stderr)
        status = 3

    if status == 0 and len(rows) == len(gold_rows):
        document["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(path, document)
    decided = sum(1 for row in rows if row["outcome"] != "refused")
    print(f"{len(rows)}/{len(gold_rows)} answered by {document['model']} — {decided} decided, "
          f"{len(rows) - decided} unusable. Written to {path}")
    if status == 0:
        print(f"score it: python -m upto.evaluate.score {path}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
