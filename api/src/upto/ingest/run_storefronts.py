"""Run the storefront ingest once — the entry point a scheduler calls, and a human can call.

    python -m upto.ingest.run_storefronts

`run_brands`' sequencing and exit codes, one source over:

    0  stored, or nothing to store — both are success
    1  the run failed: the source did not answer, or answered in a shape we do not know

Both leave an `ingest_run` row, with the publication on its own foreign key (0014).
`--file` re-runs a saved CSV and **never goes in a DAG**; `--force-parse` exists for the
integration test alone.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from . import runlog
from .foodtracer import FoodtracerUnavailable, Sheet, read_sheet
from .gradelist import (
    SCOPE,
    SOURCE,
    GradelistUnavailable,
    StorefrontResult,
    fetch,
    parse_storefronts,
)


@dataclass
class Verdict:
    source: str
    content_sha256: str
    stored: bool
    parsed: bool
    publication_id: Optional[int] = None
    names_offered: int = 0
    names_held: int = 0
    scanned: int = 0

    def line(self) -> str:
        if not self.parsed:
            return (
                "{}: no change (hash {}…) — nothing published since the last run, and the "
                "CSV was not parsed".format(self.source, self.content_sha256[:12])
            )
        return (
            "{}: {} publication {} — {} rows scanned, {} names offered, {} held "
            "(hash {}…)".format(
                self.source,
                "stored" if self.stored else "re-parsed into",
                self.publication_id,
                self.scanned,
                self.names_offered,
                self.names_held,
                self.content_sha256[:12],
            )
        )


async def ingest_sheet(
    store,
    sheet: Sheet,
    scope: str = SCOPE,
    force_parse: bool = False,
    parse: Callable[[bytes], StorefrontResult] = parse_storefronts,
) -> Verdict:
    """Claim the publication, and parse only if the claim said the content is new."""
    publication_id = await store.claim(sheet, scope)
    content_is_new = publication_id is not None

    if not content_is_new and not force_parse:
        previous = await store.held(sheet.source, sheet.content_sha256)
        await store.rollback()
        return Verdict(
            source=sheet.source,
            content_sha256=sheet.content_sha256,
            stored=False,
            parsed=False,
            publication_id=previous.publication_id if previous else None,
        )

    if publication_id is None:
        held = await store.held(sheet.source, sheet.content_sha256)
        if held is None:  # pragma: no cover — the claim said it exists one statement ago
            raise GradelistUnavailable(
                "{}: the publication vanished between the claim and the lookup".format(
                    sheet.source
                )
            )
        publication_id = held.publication_id

    parsed = parse(sheet.raw)
    offered = await store.write(publication_id, parsed.rows)
    held_now = await store.accepted(publication_id)
    await store.record_count(publication_id, held_now)
    await store.commit()
    return Verdict(
        source=sheet.source,
        content_sha256=sheet.content_sha256,
        stored=content_is_new,
        parsed=True,
        publication_id=publication_id,
        names_offered=offered,
        names_held=held_now,
        scanned=parsed.scanned,
    )


def run_record(verdict: Verdict, started_at: datetime, invoked_by: Optional[str]) -> runlog.RunRecord:
    """The verdict-to-ledger mapping, held to `run_places`'s three rules."""
    return runlog.RunRecord(
        source=verdict.source,
        started_at=started_at,
        outcome=runlog.STORED if verdict.stored else runlog.NO_CHANGE,
        rows_written=verdict.names_held if verdict.stored else 0,
        detail=verdict.line(),
        publication_id=verdict.publication_id if verdict.stored else None,
        invoked_by=invoked_by,
    )


async def ingest_once(
    sheet: Optional[Sheet] = None,
    force_parse: bool = False,
    url: Optional[str] = None,
) -> Verdict:
    """Fetch, then hand the sheet to the sequencing above with a real database behind it."""
    from ..db import pipeline_session_factory
    from .storefront_store import StorefrontStore

    Session = pipeline_session_factory(url)
    started = runlog.now()
    invoked_by = os.environ.get("UPTO_INVOKED_BY") or "cli"

    try:
        fetched = sheet if sheet is not None else fetch()
        async with Session() as session:
            verdict = await ingest_sheet(
                StorefrontStore(session), fetched, force_parse=force_parse
            )
    # The parent class, not `GradelistUnavailable`: the shared fetch raises the parent, and
    # catching only the subclass would let a transport failure skip the run row.
    except FoodtracerUnavailable as failure:
        async with Session() as session:
            await runlog.record(
                session,
                runlog.RunRecord(
                    source=SOURCE, started_at=started, outcome=runlog.FAILED,
                    detail=str(failure), invoked_by=invoked_by,
                ),
            )
        raise

    async with Session() as session:
        await runlog.record(session, run_record(verdict, started, invoked_by))
    return verdict


def main(argv=None) -> int:
    import argparse
    import asyncio
    from datetime import timezone

    parser = argparse.ArgumentParser(description="Run the storefront ingest once.")
    parser.add_argument(
        "--file",
        help="read a saved CSV instead of fetching; the hash comes from the file.",
    )
    parser.add_argument(
        "--force-parse",
        action="store_true",
        help="parse and write even when the content is already held (integration test only).",
    )
    args = parser.parse_args(argv)

    sheet = None
    if args.file:
        with open(args.file, "rb") as handle:
            sheet = read_sheet(handle.read(), datetime.now(timezone.utc), source=SOURCE)

    try:
        verdict = asyncio.run(ingest_once(sheet=sheet, force_parse=args.force_parse))
    except FoodtracerUnavailable as failure:
        print("{}: FAILED — {}".format(SOURCE, failure), file=sys.stderr)
        return 1

    print(verdict.line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
