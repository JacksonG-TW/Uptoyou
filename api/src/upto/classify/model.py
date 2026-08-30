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

from upto.classify.transport import fetch

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


def ask(prompt: str, unload_after: bool = False) -> str:
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
    reply = fetch(request, TIMEOUT_S, "model")
    # Durations are nanoseconds on the wire; counts are counts. Missing fields read as 0 rather
    # than raising — a server that stops reporting them must not stop the backfill.
    _samples.append({field: reply.get(field, 0) for field in TIMING_FIELDS})
    return reply["response"]
