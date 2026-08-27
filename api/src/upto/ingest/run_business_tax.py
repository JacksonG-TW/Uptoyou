"""Run D85's tax-registry ingest once — the entry point a scheduler calls, and a human can.

    python -m upto.ingest.run_business_tax

`run_places`' shape, because this source has `run_places`' problem: a large zip, two version
signals, and an expensive parse that must not run on a day nothing was published.

**The order of operations is the decision this file exists to hold.**

    fetch 66 MB  →  hash it  →  claim the publication  →  *only if new*  →
    read the reference 統編 from the database  →  parse 320 MB, keeping ~14.5k rows

**Three exit codes, and the middle one is unusual on purpose.**

    0  stored, or nothing to store — both are success
    1  the run failed: the source did not answer, or answered in a shape we do not know
    2  **the file's own stamp and the content hash disagree about whether anything changed.**
       The line on stdout says which of the two happened, because both are possible: content
       moved with a still stamp (stored), or the stamp moved with still content (nothing
       stored). D77, D78 and D81 have no exit 2 — their sources are bare CSVs with no second
       signal. This one states its own extract date in row 2, so the comparison exists again.

**All three leave an `ingest_run` row** (ticket 09): `stored`; `no_change` for both the silent
no-op and a forced re-parse; `failed` for exit 1. A disagreement is not a fourth outcome — by
the time one is raised the rows are already written, so it is recorded inside that row's
`detail`, and `run_record` below holds the mapping.

**The filter set is read from the database, not passed in.** Which 統編 are worth keeping is a
fact about what item 11 last stored; an operator who could override it could store a slice
nobody can explain afterwards.

`--file` re-runs a saved archive without the 66 MB download and **never goes in a DAG** — item
11's rule, restated because this is a file where it would be tempting: a local file in a DAG
turns the operator's hand-run mistakes into pipeline history. `--force-parse` exists for the
integration test alone.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Iterable, List, Optional

from . import runlog
from .fia import (
    SCOPE,
    SOURCE,
    FiaUnavailable,
    TaxArchive,
    TaxResult,
    fetch_archive,
    parse_rows,
    read_archive,
)


@dataclass
class Verdict:
    source: str
    content_sha256: str
    stamp_label: str
    stored: bool
    parsed: bool
    publication_id: Optional[int] = None
    rows_offered: int = 0
    rows_held: int = 0
    scanned: int = 0
    wanted: int = 0
    alarms: List[str] = field(default_factory=list)

    def line(self) -> str:
        """One line, and a no-op has to read as success rather than as a warning."""
        if not self.parsed:
            return (
                "{}: no change (hash {}…, stamp {}) — nothing published since the last run, "
                "and the CSV was not parsed".format(
                    self.source, self.content_sha256[:12], self.stamp_label
                )
            )
        return (
            "{}: {} publication {} — {} rows scanned, {} matched against {} reference "
            "numbers, {} held (hash {}…, stamp {})".format(
                self.source,
                "stored" if self.stored else "re-parsed into",
                self.publication_id,
                self.scanned,
                self.rows_offered,
                self.wanted,
                self.rows_held,
                self.content_sha256[:12],
                self.stamp_label,
            )
        )

    def exit_code(self) -> int:
        return 2 if self.alarms else 0


def disagreements(archive: TaxArchive, previous, content_is_new: bool) -> List[str]:
    """Compare the two version signals, and say so loudly when they contradict each other.

    D34 stores both precisely so this comparison exists: the stamp is the meaningful label and
    the hash is what catches it lying. Each failure mode is a sentence rather than a number a
    reader has to interpret.
    """
    if previous is None:
        return []
    stamp_moved = archive.file_stamp != previous.file_stamp
    alarms: List[str] = []
    if content_is_new and not stamp_moved:
        alarms.append(
            "DISAGREEMENT: the content changed and the file's own stamp did not (still {}). "
            "Under a stamp key these two publications would have merged into one — the case "
            "D35 rejected the stamp as a key for.".format(archive.stamp_label())
        )
    if not content_is_new and stamp_moved:
        alarms.append(
            "DISAGREEMENT: the file's own stamp moved to {} and the content did not change. "
            "Either the extract is rebuilt daily from unchanged data or the archive is "
            "repackaged per request; under a stamp key this run would have minted a "
            "publication for the same rows.".format(archive.stamp_label())
        )
    if not content_is_new and archive.content_sha256 != previous.content_sha256:
        alarms.append(
            "DISAGREEMENT: the served file reverted to content already held ({}…), which is "
            "not what a forward-moving extract does.".format(archive.content_sha256[:12])
        )
    return alarms


async def ingest_archive(
    store,
    archive: TaxArchive,
    scope: str = SCOPE,
    force_parse: bool = False,
    parse: Callable[[bytes, Iterable[str]], TaxResult] = parse_rows,
) -> Verdict:
    """Claim the publication, and parse only if the claim said the content is new.

    `store` is anything carrying `BusinessTaxStore`'s methods, and `parse` is injectable for
    one reason: **the guarantee that an unchanged day does not decompress 320 MB is invisible
    from outside**. A test that hands in a parser which raises is the only way to hold it.

    `force_parse` deliberately breaks that guarantee, and it is not a convenience — H14 wants
    the ingest run twice with the short-circuit disabled, because a test that passes only
    because the ingest declined to write proves nothing about the constraint.
    """
    previous = await store.latest(archive.source)
    publication_id = await store.claim(archive, scope)
    content_is_new = publication_id is not None
    alarms = disagreements(archive, previous, content_is_new)

    if not content_is_new and not force_parse:
        # The ordinary outcome. Nothing was written, so the transaction is closed rather than
        # committed, and the CSV is never touched.
        await store.rollback()
        return Verdict(
            source=archive.source,
            content_sha256=archive.content_sha256,
            stamp_label=archive.stamp_label(),
            stored=False,
            parsed=False,
            publication_id=previous.publication_id if previous else None,
            alarms=alarms,
        )

    if publication_id is None:
        held = await store.held(archive.source, archive.content_sha256)
        if held is None:  # pragma: no cover — the claim said it exists one statement ago
            raise FiaUnavailable(
                "{}: the publication vanished between the claim and the lookup".format(
                    archive.source
                )
            )
        publication_id = held.publication_id

    # Read after the claim, never before: on a no-change day this query is not run either.
    wanted = await store.reference_business_nos()
    parsed = parse(archive.raw, wanted)
    offered = await store.write(publication_id, parsed.rows)
    held_now = await store.accepted(publication_id)
    await store.record_count(publication_id, held_now)
    await store.commit()
    return Verdict(
        source=archive.source,
        content_sha256=archive.content_sha256,
        stamp_label=archive.stamp_label(),
        stored=content_is_new,
        parsed=True,
        publication_id=publication_id,
        rows_offered=offered,
        rows_held=held_now,
        scanned=parsed.scanned,
        wanted=parsed.wanted,
        alarms=alarms,
    )


def run_record(verdict: Verdict, started_at: datetime, invoked_by: Optional[str]) -> runlog.RunRecord:
    """Turn a verdict into ticket 09's run row — `run_places`' three rules, unchanged.

    A run that stored nothing attaches no publication (the CHECK reads `(outcome = 'stored') =
    (exactly one publication attached)`); a `--force-parse` re-run is a `no_change` whose
    `rows_written` is what landed rather than what was offered; and an alarm is not a failure,
    so it goes into `detail` while the outcome stays `stored` or `no_change`.
    """
    detail = verdict.line()
    if verdict.alarms:
        detail = "\n".join([detail] + verdict.alarms)
    return runlog.RunRecord(
        source=verdict.source,
        started_at=started_at,
        outcome=runlog.STORED if verdict.stored else runlog.NO_CHANGE,
        rows_written=verdict.rows_held if verdict.stored else 0,
        detail=detail,
        publication_id=verdict.publication_id if verdict.stored else None,
        invoked_by=invoked_by,
    )


async def ingest_once(
    archive: Optional[TaxArchive] = None,
    force_parse: bool = False,
    url: Optional[str] = None,
) -> Verdict:
    """Fetch, then hand the archive to the sequencing above with a real database behind it.

    sqlalchemy is imported here rather than at the top, so the sequencing stays testable
    without a database — which has to mean without the database libraries too, or the tests
    only run where the stack already does.

    **The run is recorded here and not inside `ingest_archive`**: that function is handed a
    *store* rather than a session precisely so it needs no database, and the row has to be
    written after the attempt in its own transaction — the no-op path has just rolled its
    transaction back, and a failure has no transaction to ride on.
    """
    from ..db import pipeline_session_factory
    from .business_tax_store import BusinessTaxStore

    Session = pipeline_session_factory(url)
    started = runlog.now()
    # A scheduled run and a hand-triggered one are different answers to "why does this row
    # exist" — absent, every run records itself as `cli`, which is a wrong fact.
    invoked_by = os.environ.get("UPTO_INVOKED_BY") or "cli"

    try:
        fetched = archive if archive is not None else fetch_archive()
        async with Session() as session:
            verdict = await ingest_archive(
                BusinessTaxStore(session), fetched, force_parse=force_parse
            )
    except FiaUnavailable as failure:
        # A source that did not answer is a failure; a source that answered the same bytes as
        # yesterday is not. The row is written before the exception continues, because `main`
        # owns the exit code and this function must not decide it.
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

    parser = argparse.ArgumentParser(description="Run D85's tax-registry ingest once.")
    parser.add_argument(
        "--file",
        help=(
            "read a saved archive instead of fetching. Re-runs a past day without the 66 MB "
            "download; the hash and the stamp come from the file, so the run is the same run. "
            "Human-only — it never goes in a DAG (item 11's rule)."
        ),
    )
    parser.add_argument(
        "--force-parse",
        action="store_true",
        help=(
            "parse and write even when the content is already held. The integration test needs "
            "the short-circuit disabled so that what it tests is the constraint rather than "
            "this module's good behaviour."
        ),
    )
    args = parser.parse_args(argv)

    archive = None
    if args.file:
        with open(args.file, "rb") as handle:
            archive = read_archive(handle.read(), datetime.now(timezone.utc), source=SOURCE)

    try:
        verdict = asyncio.run(ingest_once(archive=archive, force_parse=args.force_parse))
    except FiaUnavailable as failure:
        print("{}: FAILED — {}".format(SOURCE, failure), file=sys.stderr)
        return 1

    print(verdict.line())
    for alarm in verdict.alarms:
        print("{}: {}".format(SOURCE, alarm), file=sys.stderr)
    return verdict.exit_code()


if __name__ == "__main__":
    sys.exit(main())
