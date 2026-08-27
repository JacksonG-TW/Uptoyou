"""A8 — when a new place publication lands, classify what it brought, once the card is free.

*Owner-ruled 2026-08-19: ① Asset, ② Sensor. Ticket `doc/issues/A8-airflow-asset-sensor.md`.*

**No cron. This DAG is scheduled on an asset**, `place_publication`, emitted by
`upto_place_reference_ingest` **only when its run actually stored** — a `no_change` day emits nothing
and this never wakes. That is the whole point of the pair: the classifier runs because there is new
data, not because it is three in the morning.

**The sensor exists because the model service comes and goes, and the relay does not.** The relay is a
resident user unit with lingering enabled; what is intermittent is Ollama on the GPU box, which is
taken for exclusive image windows of 25–40 minutes (announced before and after, ~0.9 GPU-h a week).
So a pass that starts while the card is busy must **wait**, not fail — `mode="reschedule"` frees the
worker slot between pokes instead of holding one for up to twelve hours.

**Strict, not best-effort** (gpu-imggen's ask, 2026-08-19): it passes only when the card will actually
serve **both** ruled models. A pass that starts with the generator up and the embedder missing dies in
its first batch having written nothing, which is worse than waiting — measured on 信義, where an evicted
embedder met the ruled 2.5 s retry window against a 10.5 s cold load.

**The poke asks by calling, and the first version asked by listing, which was wrong.** It read
`/api/tags` and passed when both models appeared. **`/api/tags` reports models installed on disk, not
models the card can serve.** Taking the card for an image window **evicts** models from VRAM; it does
not uninstall them, so the tag list is identical throughout a window and the sensor passed straight
through the condition it exists to detect. Caught by the evaluator reading this file rather than by
spending a GPU window on it, and confirmed here: with the card idle and **nothing** resident,
`/api/tags` returned three models and `/api/ps` returned zero.

**`/api/ps` alone is the tempting swap and it is also wrong**, in the opposite direction: a model is
resident only *after* a call, so a completely free, idle card lists nothing and a sensor watching `ps`
would wait for ever — a failure that looks like patience, which is harder to notice than a crash.

So the poke performs **one minimal generate**. It is the only question whose answer is what the
classifier will actually experience, and it has a useful side effect: a poke that succeeds leaves the
model **warm**, which is exactly the cold-load protection a pass needs (H43: the ruled 2.5 s retry
window against an 11.7 s cold load).

**One pass at a time, sequentially, and deliberately not a mapped task.** `upto.classify.run` takes
one township, so a fan-out would be the obvious shape and the wrong one: parallel passes would each
hold the same card and contend, which is the condition that cost 信義's opening 2.19× (H40). One task
walks the townships in order; each commits per 25 rows, so an interruption costs at most 25.

**The boundary is announced in the log, before the work starts** (gpu-imggen's second ask). Their
server-side capture is sliced by time, and a boundary drawn from where somebody *noticed* is
systematically late and dilutes toward "no effect" — that is H40, learned the expensive way. So this
prints `A8 PASS BOUNDARY START <iso>` before the first request and `… END <iso>` after the last,
greppable in the task log, so a window can be sliced against the run rather than against a guess.

**What this DAG does not do: yield.** Once a pass starts it holds the card until it finishes, and
there is no signal that can take it back. That is the intended use — the card is the classifier's by
default — and it is recorded here rather than discovered: if an image window ever needs to preempt a
running pass, that is a lock and a different ticket.

**Throughput falls across a long pass and that is not a defect** — roughly 2× over five thousand
names, all of it inside the model server's own service time while every duration it reports stays
flat. Read `doc/build-hazards.md` H43 before treating a slowing pass as a bug in this DAG.
"""

from __future__ import annotations

import os
import sys
import subprocess
import urllib.error
import urllib.request
import json
from datetime import datetime, timedelta, timezone

from airflow.hooks.base import BaseHook
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.sdk import Asset, dag, task

# H46 — Airflow 3 does not put the dags folder on `sys.path` (Airflow 2 did), so a sibling import
# inserts it. Read `doc/build-hazards.md` H46 before moving this to `PYTHONPATH`.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _alerts import send_failure_alert

# A15 / D115: the pipeline runs as `upto_ingest`, which can read nothing that names a
# person (§3.0, D14). `upto_postgres` is the owner's connection and no DAG uses it.
POSTGRES_CONNECTION = "upto_ingest_postgres"

PLACE_PUBLICATION = Asset("place_publication")

# The ruled pair (map; every decided row in the database carries the first of these). **Both are
# required** — the classifier needs the generator to answer and the embedder to build each name's
# five retrieved neighbours, and it dies on the first batch without either.
MODEL = "gemma2:2b"
EMBEDDER = "snowflake-arctic-embed2"

# `UPTO_MODEL_HOST` and `UPTO_MODEL` are the classifier's variables. **`UPTO_OLLAMA_URL` is a
# different tool's and it does exist** — `evaluate/run_round.py:119`, the evaluation round runner's
# own model service, defaulting to the compose container `http://ollama:11434`. This comment said it
# existed nowhere in the codebase until 2026-08-19, when the evaluator grepped it; the true claim was
# only ever "not the classifier's", and overreaching made a real variable unfindable.
#
# `172.17.0.1:11434` is what the relay exposes to the containers — the same address that was
# connection-refused *before* the relay existed, which is the measurement the relay was built to
# answer rather than a contradiction of it.
MODEL_HOST = os.environ.get("UPTO_MODEL_HOST", "172.17.0.1:11434")

POKE_SECONDS = 90
TIMEOUT_HOURS = 12

# **Longer than a cold load and shorter than a poke interval.** A cold load measured 11.7 s under load
# on the GPU box, so a timeout below that would read a *free but cold* card as busy — the sensor would
# refuse the card at exactly the moment it became available. 30 s leaves margin without letting a
# blocked call straddle two pokes.
POKE_TIMEOUT_SECONDS = 30


def _database_url() -> str:
    connection = BaseHook.get_connection(POSTGRES_CONNECTION)
    return "postgresql+asyncpg://{}:{}@{}:{}/{}".format(
        connection.login, connection.password, connection.host,
        connection.port or 5432, connection.schema,
    )


# Townships of the **current** publication holding rows with no verdict. `place.category_generated_at`
# is the stamp a decided row carries; `reference_place` is joined so the answer is scoped to the
# publication the asset event was emitted for rather than to whatever `place` happens to hold.
UNVERDICTED = """
with latest as (
    select id from place_publication order by detected_at desc, id desc limit 1
)
select rp.township_code, count(*) as pending
  from reference_place rp
  join latest on rp.publication_id = latest.id
  left join place p
    on p.registry_no = rp.registry_no and p.origin = 'reference'
 where p.id is null or p.category_generated_at is null
 group by rp.township_code
having count(*) > 0
 order by count(*) desc
"""


@dag(
    dag_id="upto_place_classify_backfill",
    description="A8 — classify a new place publication's undecided rows, once the GPU is free",
    # **An asset, never a cron.** Both would be wrong together: a cron would run it on days with
    # nothing new, and `catchup` would queue a run per missed interval for a card that can serve one
    # pass at a time.
    schedule=[PLACE_PUBLICATION],
    start_date=datetime(2026, 8, 19),
    catchup=False,
    max_active_runs=1,
    default_args={
        # A10 — one Telegram message per failed task, after the retries are spent. It never
        # raises, and it is silently absent when the `telegram_alerts` Connection is not
        # there, which is the designed state for a stack nobody is watching.
        "on_failure_callback": send_failure_alert,
        "retries": 0,
        "depends_on_past": False,
    },
    tags=["classify", "A8", "gpu", "asset-triggered"],
)
def upto_place_classify_backfill():
    @task.sensor(
        task_id="model_service_up",
        poke_interval=POKE_SECONDS,
        timeout=timedelta(hours=TIMEOUT_HOURS),
        # **`reschedule`, not `poke`.** A poke-mode sensor holds a worker slot for the whole wait; at
        # a twelve-hour timeout that is a slot gone for half a day, and this stack has few. Reschedule
        # releases it between checks, which is the difference between *waiting* and *blocking*.
        mode="reschedule",
        # No retries: a reschedule sensor that times out has already waited twelve hours, and trying
        # again would wait twelve more without anybody deciding to.
        retries=0,
    )
    def model_service_up() -> bool:
        """True only when the card actually **serves** both ruled models. Strict, by ask.

        **It asks by calling, not by listing.** `/api/tags` reports what is installed on disk and
        answers the same during an image window as outside one — taking the card evicts models from
        VRAM without uninstalling them. `/api/ps` reports what is resident, and a model becomes
        resident only *after* a call, so a completely free idle card lists nothing and a sensor
        watching it would wait for ever. Neither question is the one that matters. **The question that
        matters is «will this card answer me», and the only way to ask it is to ask.**

        One minimal generate against the model and one one-token embed against the embedder. If both
        answer, the pass can start — **and the models are now warm**, which is the cold-load protection
        the ruled 2.5 s retry window cannot provide for itself (H43).

        **Any failure is *not ready*, never *failed*.** Refused connection, timeout, VRAM error, a body
        that will not parse — operationally all of them mean *not yet*, and all are ordinary during an
        image window. Failing here would turn a 25-minute window into a red DAG somebody clears by hand.

        **One case is knowingly unmeasured, and it is recorded rather than assumed away: a generate
        that succeeds *slowly* under VRAM pressure.** Nobody has measured what Ollama does while SDXL
        holds ~7 GB of an 8 GB card — error, block, or slow success. Error and block both land in the
        `except` below and read correctly as *not ready*. **Slow success would pass this sensor and let
        a pass start into a contended card**, which costs throughput (信義's opening ran 2.19× slow,
        H40) and costs no correctness — the pass still commits per 25 and still finishes. That is the
        tolerable one of the three, which is why this ships before the measurement rather than after.
        The evaluator has the measurement queued for a real window.
        """
        def answers(path: str, payload: dict, what: str) -> bool:
            request = urllib.request.Request(
                "http://{}{}".format(MODEL_HOST, path),
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=POKE_TIMEOUT_SECONDS) as response:
                    body = json.loads(response.read())
            except urllib.error.HTTPError as refused:
                # **The service answered and said no.** Caught before `URLError` (its parent) so the
                # two are distinguishable in the log: a 500 from a card that cannot fit the model is
                # *not ready*, and it is a different fact from nobody being there at all.
                print("{} not ready — the service answered {}: {}".format(
                    what, refused.code, refused))
                return False
            except (urllib.error.URLError, OSError, TimeoutError) as unavailable:
                # **Nobody is there, or nobody answered in time.** gpu-imggen's point: *unreachable*
                # is a third state and should not read the same as *busy*. **The action is the same
                # — wait — and that is deliberate**: the relay restarting, the GPU box rebooting and
                # an image window are all things that end on their own, and failing here would turn
                # any of them into a red DAG somebody clears by hand. So the *record* distinguishes
                # them and the *behaviour* does not, which is the honest split rather than a guess
                # about which absences deserve a failure.
                print("{} not reachable at {} (a different fact from busy): {}".format(
                    what, MODEL_HOST, unavailable))
                return False
            except ValueError as unparseable:
                print("{} answered with something that is not JSON: {}".format(what, unparseable))
                return False
            if not isinstance(body, dict) or body.get("error"):
                print("{} answered with an error: {}".format(what, str(body)[:300]))
                return False
            print("{} answered".format(what))
            return True

        # `num_predict: 1` and `keep_alive` left at the service default: the point is to make the card
        # load and answer, not to hold it. One token is enough to prove both.
        generator = answers(
            "/api/generate",
            {"model": MODEL, "prompt": "1", "stream": False, "options": {"num_predict": 1}},
            "generator {}".format(MODEL),
        )
        embedder = answers(
            "/api/embed",
            {"model": EMBEDDER, "input": "1"},
            "embedder {}".format(EMBEDDER),
        )
        if generator and embedder:
            print("both ruled models served by {} — and now warm".format(MODEL_HOST))
            return True
        return False

    @task(task_id="classify_new_publication")
    def classify_new_publication() -> str:
        """Walk the current publication's undecided townships, one pass at a time.

        Sequential on purpose — see the module docstring on why a mapped task would be the wrong
        shape for a single card.
        """
        pending = PostgresHook(postgres_conn_id=POSTGRES_CONNECTION).get_records(UNVERDICTED)
        if not pending:
            print("nothing undecided in the current publication — the asset fired and there is no "
                  "work, which is a real state rather than an error")
            return "no work"

        interpreter = os.environ.get("UPTO_PYTHON", "/opt/upto/venv/bin/python")
        source = os.environ.get("UPTO_SRC", "/opt/upto/src")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = source
        environment["UPTO_DATABASE_URL"] = _database_url()
        environment["UPTO_INVOKED_BY"] = "airflow"
        environment["UPTO_MODEL_HOST"] = MODEL_HOST
        environment["UPTO_MODEL"] = MODEL
        # Unbuffered, so the per-batch timing lines reach the task log as they happen rather than in
        # one block at exit. 信義's columns were lost to a buffered pipe; they are the only record of
        # a pass's shape and they are not reconstructable afterwards.
        environment["PYTHONUNBUFFERED"] = "1"

        # **The boundary, announced before the first request** — gpu-imggen slices a server-side
        # capture by time, and a boundary drawn from where somebody noticed is late in one direction
        # every time (H40). Printed in a fixed, greppable form for that reason.
        started = datetime.now(timezone.utc).isoformat()
        print("A8 PASS BOUNDARY START {} — {} township(s), {} rows undecided".format(
            started, len(pending), sum(row[1] for row in pending)))

        done, failed = [], []
        for township_code, count in pending:
            print("--- {} : {} undecided".format(township_code, count))
            finished = subprocess.run(
                [interpreter, "-m", "upto.classify.run", township_code,
                 "--rag", "--embed", "arctic"],
                env=environment, capture_output=True, text=True,
            )
            if finished.stdout:
                print(finished.stdout.strip())
            stderr = (finished.stderr or "").strip()
            # **Exit 3 is the model service being down, and it is ordinary rather than a failure**
            # (D75): nothing was written and a later run resumes. It ends the walk, because every
            # remaining township would meet the same absent service.
            if finished.returncode == 3:
                print("{}: the model service went away mid-walk — exit 3, nothing written, "
                      "stopping here. The next asset event resumes.".format(township_code))
                break
            if finished.returncode != 0:
                failed.append(township_code)
                print("{}: exit {} — {}".format(township_code, finished.returncode, stderr[-500:]))
                break
            done.append(township_code)

        ended = datetime.now(timezone.utc).isoformat()
        print("A8 PASS BOUNDARY END {} — {} township(s) completed".format(ended, len(done)))

        if failed:
            raise RuntimeError(
                "classify failed on {} after completing {}. Rows already decided are committed — "
                "the pass commits per 25 — so this is 'come and read the log', not 'nothing "
                "happened'.".format(", ".join(failed), ", ".join(done) or "none")
            )
        return "{} township(s): {}".format(len(done), ", ".join(done) or "none")

    model_service_up() >> classify_new_publication()


upto_place_classify_backfill()
