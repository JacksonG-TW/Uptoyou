"""The database engine, async end to end, and built on first use rather than on import.

H1 is the reason there is no synchronous path here at all. FastAPI handlers run on one
event loop shared by every connected client; a synchronous driver blocks that loop for the
whole query, and while it is blocked nobody is served. The hazard notes that the most likely
route into it is *following a working example*, because most tutorials use the synchronous
mode — so the async engine is the only one available, and there is no sync alternative to
reach for by accident.

**Why the engine is lazy.** It used to be created at import time from an environment
variable. D33 rules that operational credentials reach a task as an **Airflow Connection**,
which a DAG can only read once it is running — after the module would already have been
imported. Binding at import forced the URL into the environment, which is the arrangement
D33 exists to reject. Now a caller may pass a URL it just read from a Connection, and the
environment variable is only the fallback the API uses.
"""

import os
import sys
from typing import Dict

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

DATABASE_URL_VAR = "UPTO_DATABASE_URL"

_engines: Dict[str, AsyncEngine] = {}


def database_url() -> str:
    """The fallback URL, and it fails loudly when absent.

    H16's mitigation asks the stack to fail at startup with a clear message when a bootstrap
    variable is missing, rather than failing later inside a request where it reads as an
    application bug.
    """
    url = os.environ.get(DATABASE_URL_VAR)
    if not url:
        raise RuntimeError(
            "{} is not set, and no URL was passed. The API reads it from the environment; a "
            "DAG passes one built from its Airflow Connection (D33).".format(DATABASE_URL_VAR)
        )
    return _checked(url)


def _checked(url: str) -> str:
    if "+asyncpg" not in url:
        raise RuntimeError(
            "the database URL must use the asyncpg driver (postgresql+asyncpg://...). A "
            "synchronous driver blocks the event loop for every connected client — see H1."
        )
    return url


def engine_for(url: str | None = None) -> AsyncEngine:
    resolved = _checked(url) if url else database_url()
    if resolved not in _engines:
        _engines[resolved] = create_async_engine(
            resolved,
            # One API worker (H2), so the pool is small on purpose rather than by omission.
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            echo=False,
        )
    return _engines[resolved]


def session_factory(url: str | None = None) -> async_sessionmaker:
    return async_sessionmaker(engine_for(url), expire_on_commit=False)


# A15 / D115 — the three roles, and which variable each tool reads.
#
# **`DATABASE_URL_VAR` above is the SERVER's, and since A15 it is the server's alone.** The api
# container is the entry point for three different things — uvicorn, the pipeline CLIs and the
# lineage tool — so one variable cannot serve all three without handing every one of them the
# widest role. Each tool names its own below; `engine_for` already took an explicit URL, which is
# the door D33 built for exactly this ("a caller may pass a URL it just read from a Connection").
INGEST_URL_VAR = "UPTO_INGEST_DATABASE_URL"
LINEAGE_URL_VAR = "UPTO_LINEAGE_DATABASE_URL"


def _role_url(variable: str, what: str) -> str:
    """The URL for one role, or the owner's with a loud line saying the fallback fired.

    **The fallback exists for the build-and-drop integration tests and for nothing else.** Those
    create their own database, run as its owner and set only `UPTO_DATABASE_URL` — A15 keeps them
    that way on purpose, because a test that had to be granted before it could run would be
    asserting the grants rather than the behaviour.

    **It is loud because a silent one would undo D115.** A production container missing its
    variable would otherwise quietly connect as the widest role available and every refusal this
    ticket exists to produce would stop happening, with nothing on any screen. So the fallback
    prints, and `test_role_grants.py` asserts that in the *running* stack all three variables are
    set — the fallback's correctness in a test and its absence in production are two different
    checks and both are made.
    """
    url = os.environ.get(variable)
    if url:
        return _checked(url)
    print(
        "db: {} is not set — {} is falling back to {}, which is the OWNER's connection. "
        "That is correct only in a build-and-drop test; in the stack it means the role split "
        "(D115) is not in force for this process.".format(variable, what, DATABASE_URL_VAR),
        file=sys.stderr,
        flush=True,
    )
    return database_url()


def pipeline_session_factory(url: str | None = None) -> async_sessionmaker:
    """`upto_ingest` — the six ingest CLIs, the classifier, the seed CLIs.

    An explicit `url` still wins — that is a DAG handing over what it read from its Airflow
    Connection (D33), and it is the path the five source CLIs already take.

    D115: this role may not read `member`, `principal`, `preference`, `round`, `proposal`,
    `weight_contribution`, `trip`, `member_roll` or `device_secret`. **The pipeline never sees a
    person** (§3.0, D14), and since A15 the database is what says so rather than a habit.
    """
    return session_factory(url or _role_url(INGEST_URL_VAR, "the pipeline"))


def lineage_session_factory(url: str | None = None) -> async_sessionmaker:
    """`upto_lineage` — SELECT on exactly what `queries.READABLE_TABLES` names.

    H20's boundary was a Python list; since A15 it is a GRANT, and the list is the second line.
    A tool that reaches past it now fails at the database rather than at a code review.
    """
    return session_factory(url or _role_url(LINEAGE_URL_VAR, "the lineage tool"))


async def dispose_all() -> None:
    for engine in list(_engines.values()):
        await engine.dispose()
    _engines.clear()
