"""The API. One endpoint so far, and it is the one the stack's health depends on.

Nothing about the product is here yet. The build order puts the pipeline first, so the
first real endpoints arrive after the ingest tables exist.
"""

import os
import socket
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Response, status
from sqlalchemy import text

from .db import dispose_all, session_factory
from .read.weather import ForecastJoinBroken, TownshipUnknown, reading_for
from .live import router as live_router
from .schema_guard import check_or_exit
from .stream import listener_status, listening
from .preferences import router as preferences_router
from .rounds import router as rounds_router

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """The instance's one `LISTEN` connection, opened with the app and closed with it.

    **This is what makes more than one instance possible** (owner 「Notify」, 2026-09-11): events
    are published as `pg_notify` inside the writing transaction and every instance fans out to its
    own subscribers from here. With one instance it is a no-op in effect — the instance hears its
    own notification — which is why it can be shipped and gated before a second one exists.
    """
    # **Before anything is served, and before the listener.** `migrate` left the stack's boot so
    # N instances cannot race one migration (owner 「一次」), which also removed `api`'s
    # `depends_on` on it — and with it D115's «a failed migration stops the API one container
    # earlier». The guarantee is structural again rather than a step in a deploy script: this
    # refuses to serve a schema that is not the one the code ships against, on every path
    # including a plain `up` on a development machine (the evaluator's catch).
    await check_or_exit(session_factory)
    async with listening():
        yield


app = FastAPI(
    lifespan=lifespan,
    title="Up to you",
    summary="Decide one meal, without anybody having to give something up first.",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)
app.include_router(rounds_router)
app.include_router(live_router)
app.include_router(preferences_router)


#: Which of N instances answered. `HOSTNAME` is the container id under compose and the pod name
#: under anything else; the `gethostname()` fallback covers a bare `uvicorn`. **Not decoration:**
#: with a load balancer in front, «one instance is deaf» and «the stack is deaf» produce the same
#: `curl` unless the answer says who gave it, and that was the whole of H81's invisibility.
INSTANCE = os.environ.get("HOSTNAME") or socket.gethostname()


@app.get("/health")
async def health(response: Response) -> dict:
    """Answer only after the database has answered.

    A health check that reports the process is alive tells the orchestrator nothing worth
    acting on. compose gates the proxy on this endpoint, so it has to mean *the stack can
    serve a request*, which includes reaching the database.

    **Since 2026-09-11 it also means «and this instance can still hear the circle».** An instance
    whose `LISTEN` connection has died answers every request correctly and moves nobody's screen
    ever again — and the stream's heartbeat is generated locally, so it does not even go quiet.
    Reported here, a deaf instance is one a load balancer stops sending members to and one
    `--wait` refuses; unreported, it was invisible and permanent. It answers **503 while degraded
    and keeps serving reads**, which is the whole point: the process is useful and not whole.
    """
    try:
        async with session_factory()() as session:
            await session.execute(text("select 1"))
    except Exception as failure:  # noqa: BLE001 — the reason belongs in the body
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        # **`instance` is in every branch, and this one needed it most** (the reviewer's note,
        # 2026-09-11). H81's argument is that behind a load balancer «one instance is deaf» and
        # «the stack is deaf» produce the same `curl` — and the branch where that matters is the
        # one that says something is wrong. An unhealthy answer that will not say who gave it
        # sends the reader to the whole stack for a fault that may be in one container.
        return {"status": "unhealthy", "database": "unreachable", "instance": INSTANCE,
                "detail": str(failure)[:200]}
    listener = listener_status()
    if listener["stream_listener"] != "up":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "reachable", "instance": INSTANCE, **listener}
    return {"status": "ok", "database": "reachable", "instance": INSTANCE, **listener}


@app.get("/weather")
async def weather(
    township: str = Query(..., description="內政部 township code, e.g. 63000040 for 中山區"),
    hour: datetime = Query(..., description="the hour described, with an offset — 2026-08-11T19:00:00+08:00"),
) -> dict:
    """Ticket 07's one call: the observation for that hour, else the forecast for that hour.

    The response always says which of the two answered and which stored row it came from,
    because D15's snapshot must be able to pin exactly what a round read.

    This is not a product endpoint. D20 rules where weather may appear on a screen — the home
    screen, as information, never as a reason, and never on a decision screen — and none of
    those screens exist yet. This exists so the read path can be exercised end to end.
    """
    if hour.tzinfo is None:
        # H17: a timestamp without a zone cannot be compared with anything here. Refusing is
        # the only honest answer, since guessing the offset is what the hazard is about.
        raise HTTPException(status_code=422, detail="hour must carry a UTC offset")
    async with session_factory()() as session:
        try:
            reading = await reading_for(session, township, hour)
        except TownshipUnknown as unknown:
            raise HTTPException(status_code=404, detail=str(unknown)) from None
        except ForecastJoinBroken as broken:
            # Not a 404: the data is there and the join is wrong, which is an operator problem
            # rather than a client one.
            raise HTTPException(status_code=500, detail=str(broken)) from None
    body = {
        "kind": reading.kind,
        "township_code": reading.township_code,
        "township_name": reading.township_name,
        "hour": reading.hour.isoformat(),
        "measures": reading.measures,
    }
    if reading.slots:
        # Which slot each measure came from. Since the 2026-08-12 ruling a value may be read
        # from the block containing the hour — 10:00's 天氣 from the 09:00–12:00 block — so the
        # hour alone no longer says what was read, and D15's snapshot needs this to pin it.
        body["slots"] = {
            label: {
                "start": start.isoformat(),
                # None on the last slot of a series: the source gave no end and inventing one
                # would extend a horizon it never published.
                "end": end.isoformat() if end is not None else None,
            }
            for label, (start, end) in reading.slots.items()
        }
    if reading.station_id:
        body["station"] = {"id": reading.station_id, "name": reading.station_name}
    if reading.provenance:
        body["source"] = {
            "publication_id": reading.provenance.publication_id,
            "dataset_id": reading.provenance.dataset_id,
            "content_sha256": reading.provenance.content_sha256,
            # The label is part of the answer, not decoration: a forecast's stamp is when we
            # detected it, because CWA never says when it was published (D42).
            reading.provenance.time_label + "_at": reading.provenance.detected_at.isoformat(),
            "time_label": reading.provenance.time_label,
        }
    if not reading.present:
        body["absence_reason"] = reading.absence_reason
    return body


@app.on_event("shutdown")
async def dispose_engines() -> None:
    await dispose_all()
