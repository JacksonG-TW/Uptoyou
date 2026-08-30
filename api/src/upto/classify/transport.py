"""One retry policy for both model calls — owner-ruled 2026-08-18, D75 amended.

**Why it exists.** 松山's backfill died at row 400 of 3,324 on
`http.client.RemoteDisconnected: Remote end closed connection without response`, raised inside the
generation client's `urlopen`. The relay was healthy either side of it — checked from the host and
from inside the container, all three models visible — so the drop was transient, and one blip cost
2,900 names their place in the queue.

**Why it is one module rather than a copy in each client.** The ruling covers `model.ask` and
`embed.embed`, and the embedding side is the one the batching change made worse: since a commit
batch now asks for 25 names in a single request, a dropped embed call costs 25 rows rather than 1.
Two copies of a retry policy drift, and the *count* has to be one number — a run that retried twice
on the generator and once on the embedder spent three retries, and a reader chasing a flaky link
wants that total rather than two half-answers. The crib load and the evaluation rounds inherit the
policy by using the same client, which the owner named as the point rather than a side effect.

**Bounded, and connection-level only.** Three attempts, then the original failure is raised **as it
always was** — not wrapped — so no caller's `except` changes meaning and the traceback still names
the link that failed. The rejected branch is unbounded or open-ended retry, which papers over a
genuinely dead tunnel; the cost accepted is that a dead tunnel is discovered about thirty seconds
later than before, and that is the whole cost.

**A retry is for a call that never got an answer, never for an answer we did not like.** Two
exclusions carry that, and both are easy to get wrong:

- `urllib.error.HTTPError` is re-raised immediately **even though it subclasses `URLError`**. A 400
  or a 404 *is* the server answering; asking three times gets the same answer three times and turns
  a clear error into a slow one.
- A reply whose body will not parse is also an answer, so decoding happens **outside** the retried
  block. Re-asking there would be asking the model to change its mind about something it already
  said.

**The count is printed, and that is part of the ruling rather than a nicety.** A link that drops one
call in fifty now succeeds silently and reads as a slow night; `retries_spent()` is what a backfill
prints so it shows up as a number instead.

---

**Measured 2026-08-19: this policy does not survive a cold model load, and that is a calibration
question for the owner rather than a bug.** The 信義 pass died in its **first** batch —
`EmbedUnavailable: snowflake-arctic-embed2 … Remote end closed connection without response`, zero
rows written — after another workload on the GPU box (SDXL, by agreement) had evicted the models.
The retry behaved exactly as ruled: attempt 1, wait 0.5 s, attempt 2, wait 2.0 s, attempt 3, raise.
**Total window 2.5 s.** Hand-measured immediately afterwards, on the same box, cold:

    embed  (snowflake-arctic-embed2)  10.48 s
    generate (gemma2:2b)             20.98 s

So the policy is short by a factor of four on the embedder and eight on the generator. **It is not
mis-ruled** — it was ruled for 松山's mid-run blip, which is a sub-second event, and stretching the
steady-state window to thirty seconds would make a genuinely dead tunnel take thirty seconds *per
call* to report across every one of ~150 batches, turning a fast clear exit 3 into a slow one. That
is the trade the ruling already rejected, and widening the backoff re-opens it.

**The shape that does not re-open it** — recommended, not built, because the count and the window are
owner-ruled: warm both models once **before** the row loop, with a generous one-off timeout, and let
the steady-state policy stand untouched. A known ~30 s startup cost becomes a startup cost instead of
a fatal, and nothing about a call in flight changes. Cost: one extra call per run, and a new place the
CLI can fail. Today's pass was launched against models warmed by hand, so nothing is blocked on the
answer.
"""

from __future__ import annotations

import http.client
import json
import sys
import time
import urllib.error
import urllib.request

RETRIES = 3
BACKOFF_S = (0.5, 2.0)  # slept after the first failure, then after the second

# **The schedule for the one request that follows an unload (H43 + H52).** A model that has just
# been unloaded is COLD, and H52's finding is that a cold model on this path presents as **down**,
# not as slow: the first call comes back `RemoteDisconnected` and the retry a few seconds later
# answers normally. The ordinary schedule above spends **2.5 s across three attempts** — it was
# sized for a dropped tunnel, not for a load — and a 7B measured at **14.8 s** to reload never gets
# a fourth chance. That is exactly how qwen7b died at row 50 of a 200-row round.
#
# Five attempts, **27 s of waiting**, which covers 14.8 s with room for a card that has to evict an
# embedder first. **Longer timeouts would not have helped** — the failure is a refusal, not a hang,
# so what is needed is more attempts spread wider, and H52 says so in those words.
COLD_BACKOFF_S = (2.0, 5.0, 8.0, 12.0)

# A dropped call and a dropped connection are the same class of event here, and both are `OSError`
# subclasses in practice — `RemoteDisconnected` is one. `http.client.HTTPException` is listed anyway
# because not every member of that family is an `OSError`, and the one that killed 松山 is the one
# this must not miss.
TRANSIENT = (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError)

_retried = 0


def retries_spent() -> int:
    """How many connection-level retries this process has spent, across both clients."""
    return _retried


def reset_retries() -> None:
    """Zero the counter. A caller measuring one pass calls this before it starts."""
    global _retried
    _retried = 0


def fetch(request: urllib.request.Request, timeout: int, what: str,
          backoff: tuple = BACKOFF_S) -> dict:
    """One HTTP call, decoded, retried on a connection-level failure only.

    `what` names the caller in the retry line — `model` or `embed` — because a run that retried
    should say *which* link dropped, and the two go to the same host over the same tunnel.

    `backoff` is the sleep schedule and its length sets the attempt count. Pass `COLD_BACKOFF_S`
    for the first request after an unload; the default is the ordinary one.
    """
    global _retried
    attempts = len(backoff) + 1
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError:
            raise  # the server answered; that is not a dropped call
        except TRANSIENT as failure:
            if attempt == attempts:
                raise
            _retried += 1
            pause = backoff[attempt - 1]
            print(
                f"  {what} call failed ({type(failure).__name__}: {failure}) — attempt "
                f"{attempt} of {attempts}, retrying in {pause}s",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(pause)
        else:
            # Outside the retried block on purpose: a body that will not parse is an answer.
            return json.loads(body)
    raise AssertionError("unreachable: the loop either returns or raises")
