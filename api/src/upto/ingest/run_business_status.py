"""Run the registry-status ingest once — the entry point a scheduler calls, and a human can.

    python -m upto.ingest.run_business_status

`run_brands`' sequencing and exit codes (0 stored or no change; 1 failed), the ledger row on
its own foreign key (0016). `--file` re-runs a saved CSV and **never goes in a DAG**;
`--force-parse` exists for the integration test alone. The roster updates monthly, so a
daily schedule would be twenty-nine silent no-ops — the same arithmetic item 11 lives with.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from . import runlog
from .foodtracer import FoodtracerUnavailable, Sheet, read_sheet
from .gcis import (
    SCOPE,
    SOURCE,
    GcisUnavailable,
    StatusResult,
    fetch,
    parse_statuses,
)


@dataclass
class Verdict:
    source: str
    content_sha256: str
    stored: bool
    parsed: bool
    publication_id: Optional[int] = None
    rows_offered: int = 0
    rows_held: int = 0
    numbers: int = 0
    scanned: int = 0

    def line(self) -> str:
        if not self.parsed:
            return (
                "{}: no change (hash {}…) — nothing published since the last run, and the "
                "CSV was not parsed".format(self.source, self.content_sha256[:12])
            )
        return (
            "{}: {} publication {} — {} rows scanned, {} tuples offered, {} held, "
            "{} distinct numbers (hash {}…)".format(
                self.source,
                "stored" if self.stored else "re-parsed into",
                self.publication_id,
                self.scanned,
                self.rows_offered,
                self.rows_held,
                self.numbers,
                self.content_sha256[:12],
            )
        )


async def ingest_sheet(
    store,
    sheet: Sheet,
    scope: str = SCOPE,
    force_parse: bool = False,
    parse: Callable[[bytes], StatusResult] = parse_statuses,
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
            raise GcisUnavailable(
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
        rows_offered=offered,
        rows_held=held_now,
        numbers=parsed.numbers,
        scanned=parsed.scanned,
    )


def run_record(verdict: Verdict, started_at: datetime, invoked_by: Optional[str]) -> runlog.RunRecord:
    """The verdict-to-ledger mapping, held to `run_places`'s three rules."""
    return runlog.RunRecord(
        source=verdict.source,
        started_at=started_at,
        outcome=runlog.STORED if verdict.stored else runlog.NO_CHANGE,
        rows_written=verdict.rows_held if verdict.stored else 0,
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
    from .business_store import BusinessStore

    Session = pipeline_session_factory(url)
    started = runlog.now()
    invoked_by = os.environ.get("UPTO_INVOKED_BY") or "cli"

    try:
        fetched = sheet if sheet is not None else fetch()
        async with Session() as session:
            verdict = await ingest_sheet(
                BusinessStore(session), fetched, force_parse=force_parse
            )
    # The parent class: the shared fetch raises it, and a transport failure must not skip
    # the run row.
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

    parser = argparse.ArgumentParser(description="Run the registry-status ingest once.")
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
