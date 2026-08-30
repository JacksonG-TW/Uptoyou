"""The model, as reached from inside the stack — and what to do when it is not there.

The service is behind a compose profile (ruled 2026-08-14), so **absence is the ordinary
case, not the failure case**. `available()` answers that question without raising, and the
runner uses it to record a skipped pass rather than a broken one — the same distinction
`ingest_run` already draws between *no change* and *failed*, and for the same reason: an
absence inferred from an error looks exactly like a bug.

The endpoint is an environment variable because the model is the one dependency that is
sometimes simply not running; D33's rule about credentials does not apply — there is no
credential here, only a host.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from upto.classify.transport import BACKOFF_S, COLD_BACKOFF_S, fetch

MODEL = os.environ.get("UPTO_MODEL", "qwen2.5:3b-instruct-q4_K_M")
HOST = os.environ.get("UPTO_MODEL_HOST", "ollama:11434")
TIMEOUT_S = int(os.environ.get("UPTO_MODEL_TIMEOUT", "180"))

# The retry lives in `transport`, because the ruling covers this client and the embedding one and
# the printed count has to be a single number across both. See that module for the whole argument;
# the short version is three attempts, connection-level failures only, and the original exception
# raised rather than wrapped.


def available() -> bool:
    """Is the model service up and holding the model? Never raises — absence is ordinary.

    **Deliberately not retried.** It is a question rather than a request, and it already answers
    "no" instead of raising. Retrying it would turn the ordinary case — the profile is off — into
    a three-second pause before the same answer.
    """
    try:
        with urllib.request.urlopen(f"http://{HOST}/api/tags", timeout=5) as response:
            tags = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return any(entry.get("name", "").startswith(MODEL.split(":")[0]) for entry in tags.get("models", []))


# --- what the server says about its own work, kept instead of discarded ------------------
#
# **Every `/api/generate` reply already carries five timing fields and this module was throwing
# them away** — `load_duration`, `prompt_eval_count`, `prompt_eval_duration`, `eval_count`,
# `eval_duration`. Caught by gpu-imggen 2026-08-18, and it is the cheapest instrument in the
# system: the body is already parsed to get the answer, so keeping five integers costs nothing,
# adds no request, and contends with nothing.
#
# **Why it matters more than a probe.** A second client cannot measure this pass — a single-slot
# server makes any external observer's latency a function of the observed workload, so both
# sessions investigating today's throughput bend produced a contaminated wall-time column. These
# numbers come from inside the responses this pass is already receiving, for **its own real RAG
# prompts**, on every call rather than one a minute.
#
# **`prompt_eval_count` is the sharp one.** It is the prompt's token count as the server saw it. If
# it grows across a pass, the prompts are growing — which would be a mechanism rather than a
# hypothesis, and would explain a bend that a fixed-prompt probe cannot see. If it is constant,
# that whole branch dies and the model work is exonerated for these prompts too.
#
# Samples accumulate and are taken away by the caller, the same shape as the retry counter: a batch
# reads its own numbers and leaves the list empty for the next one.
_samples: list[dict] = []

TIMING_FIELDS = (
    "load_duration", "prompt_eval_duration", "eval_duration",
    "prompt_eval_count", "eval_count", "total_duration",
)


def take_samples() -> list[dict]:
    """Return the timings collected since the last call, and clear them."""
    global _samples
    taken, _samples = _samples, []
    return taken


# **H43 — the model is unloaded every N rows, and N is PER MODEL. Owner-ruled 2026-08-30
# (「不改WSL，用卸載壓住。因為windows環境也需要用到記憶體」): the WSL2 ceiling stays at 7.7 GiB
# because the Windows side needs that memory, so the unload is the bound rather than a knob.**
#
# **The per-request cache cost is a property of (model × prompt version), and BOTH halves have
# already moved once.** Measured by the GPU session in a clean window — one runner between two
# unloads, requests counted from the server's own GIN log — on **prompt v7**:
#
#     gemma2:2b   ~103 MB per request   ->  N = 25
#     llama3.2:3b  ~79 MB               ->  N = 35
#     qwen2.5:7b   ~36 MB               ->  N = 50
#     qwen2.5:3b   ~23 MB               ->  N = 50
#
# **The 2B is the expensive one and the 7B is cheap — parameter count predicts nothing here.**
# That inversion has now held across two independent measurements, so sizing N from the biggest
# model would put the smallest one over the ceiling. At the figures above every entry peaks near
# 2.6 GB against ~6.5 GB available.
#
# **The history is kept because two of the numbers in it were wrong and the corrections matter.**
# A first figure of 15.5 MB/row came from ~120-token prompts and was withdrawn. A second, 17 MB on
# v6, turned out to be **a wrong divisor** rather than a measurement — so the apparent v6→v7 "4×"
# never existed, and the stacked-runner explanation this file carried for a few hours was for a
# gap that was not there. **The clean window measured no stacked neighbour.** What remains as the
# candidate mechanism is **distinctness**: ollama keeps one saved prompt state per *distinct*
# prompt, unbounded, which is why a fixed benchmark never reproduced any of this.
#
# **So: re-measure whenever the model changes OR the prompt changes.** A prompt edit is a memory
# change and nothing about editing a prompt looks like one.
#
# **An unknown model gets the smallest N in the map, never a default.** A model nobody has measured
# is the case that kills the box, and 25 costs reloads where a wrong 50 costs the pass.
#
# The price at N = 25 on a 3,000-row township is ~120 reloads ≈ 20 minutes; the whole-city pass on
# gemma is ~1,470 reloads ≈ +4 h. That is the cost of the ruling and it is the owner's to weigh.
#
# **⚠️ Still unexplained, and H43 says so: the 大同 pass.** 3,311 rows with no gap over 70 s on a
# 7.7 GiB box, and it completed. Either the growth bounds somewhere, or something frees states
# mid-pass. **Read H43 before raising any of these.**
UNLOAD_EVERY_BY_MODEL = {
    "gemma2:2b": 25,
    "llama3.2:3b": 35,
    "qwen2.5:7b-instruct-q4_K_M": 50,
    "qwen2.5:3b-instruct-q4_K_M": 50,
}

#: What an unmeasured model gets. The smallest in the map, deliberately — see above.
UNLOAD_EVERY_UNKNOWN = min(UNLOAD_EVERY_BY_MODEL.values())


def unload_every(model: str) -> int:
    """How many rows this model may cache before the runner unloads it.

    **Prefix-matched, because the tag carries a quantisation the map should not have to spell
    twice.** `qwen2.5:7b-instruct-q4_K_M` and a future `…-q5_K_M` are the same KV geometry and the
    same answer; an exact-match map would silently fall through to the unknown branch on a
    re-quantised pull, which is the safe direction but a confusing one.
    """
    for name, n in sorted(UNLOAD_EVERY_BY_MODEL.items(), key=lambda kv: -len(kv[0])):
        if model.startswith(name) or name.startswith(model):
            return n
    return UNLOAD_EVERY_UNKNOWN


def ask(prompt: str, unload_after: bool = False, cold: bool = False) -> str:
    """One completion, deterministic, short — the answer is at most a few characters.

    **`unload_after` sets `keep_alive: 0` on THIS request, which unloads the model the moment it
    answers.** See `UNLOAD_EVERY` in `upto.classify.run` for why and how often. It is a field on a
    request we already make: no second endpoint, no separate call, nothing to fail on its own.
    Verified 2026-08-30 against the local service by reading `/api/ps` on both sides — the model
    goes, **and a resident embedder stays**, which is what makes it safe in a `--rag` pass.
    """
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        # temperature 0 so a re-run of the same prompt version is as close to repeatable
        # as this kind of tool gets. D39 admits it is not fully reproducible.
        "options": {"temperature": 0, "num_predict": 8},
    }
    if unload_after:
        payload["keep_alive"] = 0
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://{HOST}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    # **`cold` is set by the caller on the request AFTER an unload, and it is not optional
    # politeness.** H52: a cold model on this path answers the first call with
    # `RemoteDisconnected` and the next one normally. The ordinary retry spends 2.5 s and a 7B
    # takes 14.8 s to reload, so without this the unload we added to save the box kills the pass
    # instead — measured, at row 50 of a qwen7b round.
    reply = fetch(request, TIMEOUT_S, "model", COLD_BACKOFF_S if cold else BACKOFF_S)
    # Durations are nanoseconds on the wire; counts are counts. Missing fields read as 0 rather
    # than raising — a server that stops reporting them must not stop the backfill.
    _samples.append({field: reply.get(field, 0) for field in TIMING_FIELDS})
    return reply["response"]
