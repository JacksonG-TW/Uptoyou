"""Run item 11's ingest once — the entry point a scheduler calls, and a human can call.

    python -m upto.ingest.run_places

Item 10's equivalent is `upto.ingest.run`, and this is a second module rather than a second
`--dataset` value on that one: item 10 requires a CWA key and refuses to start without it,
where item 11 needs no credential at all (D33), so folding them together would either
demand a key this ingest never uses or make that module's own check conditional.

**The order of operations is the decision this file exists to hold.**

    fetch 17 MB  →  hash it  →  claim the publication  →  *only if new*  →  parse 99 MB

D34 schedules a daily fetch against a monthly file, so twenty-nine runs a month find nothing
new. Those runs must be **silent successes** — not warnings, not errors — and they must not
decompress the CSV. The claim is what tells them so, and it costs one insert.

**Three exit codes, and the middle one is unusual on purpose.**

    0  stored, or nothing to store — both are success
    1  the run failed: the source did not answer, or answered in a shape we do not know
    2  **the archive stamp and the content hash disagree about whether anything changed** —
       the alarm D34 asked for. The line on stdout says which of the two happened, because
       both are possible: content moved with a still stamp (stored), or the stamp moved with
       still content (nothing stored).

**All three leave an `ingest_run` row, which is ticket 09's requirement and was missing here.**
`stored`; `no_change` for both the silent no-op and a forced re-parse; `failed` for exit 1. Exit
code 2 is not a fourth outcome — by the time a disagreement is raised the rows are already
written, so it is recorded inside that row's `detail`. `run_record` below holds the mapping.

Why a disagreement is non-zero rather than a printed warning: whatever the run decided to
write it has already written before this code is returned, so nothing is in doubt except the
*label* — and a warning on the stdout of a green task is a fact filed where nobody looks. A
red task here means "come and read this", never "the rows are missing". The cost is a red task
for a data-quality event, which has to be narrated in the demo rather than shown, exactly as
D34 already admits for the twenty-nine no-ops.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional

from . import runlog
from .fda import (
    SCOPE,
    SOURCE,
    Archive,
    FdaUnavailable,
    ParseResult,
    Unresolved,
    fetch_archive,
    parse_places,
    read_archive,
)

# How many unresolved addresses the verdict names before it stops listing them. The count is
# always exact; the examples are so the report is actionable without a database. Every one of
# them is re-derivable afterwards:
#   select registry_no, address_raw from reference_place
#    where publication_id = <id> and township_code is null;
EXAMPLES = 5


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
    unresolved: List[Unresolved] = field(default_factory=list)
    alarms: List[str] = field(default_factory=list)
    scanned: int = 0

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
            "{}: {} publication {} — {} places offered, {} held, {} with no township "
            "(hash {}…, stamp {})".format(
                self.source,
                "stored" if self.stored else "re-parsed into",
                self.publication_id,
                self.rows_offered,
                self.rows_held,
                len(self.unresolved),
                self.content_sha256[:12],
                self.stamp_label,
            )
        )

    def township_report(self) -> List[str]:
        """A place whose address yields no township is reported, never silently dropped (D28)."""
        if not self.unresolved:
            return []
        counted = {}
        for row in self.unresolved:
            counted[row.reason] = counted.get(row.reason, 0) + 1
        lines = [
            "{}: {} of {} places carry no township — {}".format(
                self.source,
                len(self.unresolved),
                self.rows_offered,
                ", ".join("{} {}".format(count, reason) for reason, count in sorted(counted.items())),
            )
        ]
        for row in self.unresolved[:EXAMPLES]:
            lines.append("  {}  {}  [{}]".format(row.registry_no, row.address_raw, row.reason))
        if len(self.unresolved) > EXAMPLES:
            lines.append("  … {} more, all of them `where township_code is null`".format(
                len(self.unresolved) - EXAMPLES
            ))
        return lines

    def exit_code(self) -> int:
        return 2 if self.alarms else 0


def disagreements(archive: Archive, previous, content_is_new: bool) -> List[str]:
    """Compare the two version signals, and say so loudly when they contradict each other.

    D34 stores both precisely so this comparison exists: the stamp is the meaningful label and
    the hash is what catches it lying. D35's table names the two failure modes, and each one is
    a sentence here rather than a number a reader has to interpret.
    """
    if previous is None:
        return []
    stamp_moved = archive.archive_stamp != previous.archive_stamp
    alarms: List[str] = []
    if content_is_new and not stamp_moved:
        alarms.append(
            "DISAGREEMENT: the content changed and the archive stamp did not (still {}). "
            "Under a stamp key these two publications would have merged into one — this is "
            "the case D35 rejected the stamp as a key for.".format(archive.stamp_label())
        )
    if not content_is_new and stamp_moved:
        alarms.append(
            "DISAGREEMENT: the archive stamp moved to {} and the content did not change. "
            "Either the file is repackaged per request or the publisher rebuilt it unchanged; "
            "under a stamp key this run would have minted a publication for the same "
            "36,000-odd rows.".format(archive.stamp_label())
        )
    if not content_is_new and archive.content_sha256 != previous.content_sha256:
        alarms.append(
            "DISAGREEMENT: the served file reverted to content already held ({}…), which is "
            "not what a monthly refresh does.".format(archive.content_sha256[:12])
        )
    return alarms


async def ingest_archive(
    store,
    archive: Archive,
    scope: str = SCOPE,
    force_parse: bool = False,
    parse: Callable[[bytes], ParseResult] = parse_places,
) -> Verdict:
    """Claim the publication, and parse only if the claim said the content is new.

    `store` is anything carrying `PlaceStore`'s methods, and `parse` is injectable for one
    reason: **the guarantee that an unchanged day does not parse 99 MB is invisible from
    outside**. A test that hands in a parser which raises is the only way to hold it, and a
    seam that exists for a test is better than a property that exists in a comment.

    `force_parse` deliberately breaks that guarantee, and it is not a convenience. H14 requires
    item 11's test to run the ingest twice **with the short-circuit disabled**, because a test
    that passes only because the ingest declined to write proves nothing about the constraint.
    """
    previous = await store.latest(archive.source)
    publication_id = await store.claim(archive, scope)
    content_is_new = publication_id is not None
    alarms = disagreements(archive, previous, content_is_new)

    if not content_is_new and not force_parse:
        # The ordinary outcome, twenty-nine days in thirty. Nothing was written, so the
        # transaction is closed rather than committed, and the CSV is never touched.
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
            raise FdaUnavailable(
                "{}: the publication vanished between the claim and the lookup".format(
                    archive.source
                )
            )
        publication_id = held.publication_id

    parsed = parse(archive.raw)
    offered = await store.write(publication_id, parsed.rows)
    held_now = await store.accepted(publication_id)
    await store.record_counts(publication_id, held_now, len(parsed.unresolved))
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
        unresolved=parsed.unresolved,
        alarms=alarms,
        scanned=parsed.scanned,
    )


def run_record(verdict: Verdict, started_at: datetime, invoked_by: Optional[str]) -> runlog.RunRecord:
    """Turn a verdict into ticket 09's run row. Separate from the write so it needs no database.

    **Three things this mapping has to get right, and each one is a constraint in revision 0005
    rather than a preference.**

    *A run that stored nothing must attach no publication.* A no-op's verdict carries the
    **previous** publication's id, because its printed line names what is still current — but
    `ck_ingest_run_stored_has_publication` reads `(outcome = 'stored') = (exactly one
    publication attached)`, so passing that id through would fail the insert. It would also be
    the wrong claim: this run did not write those rows.

    *`--force-parse` is a `no_change` too.* It parses and offers every row, and the database
    accepts none of them (H14's test is that fact). `rows_written` is what landed, so it is
    `rows_held` rather than `rows_offered` — a column called *written* may not report an offer.

    *An alarm is not a failure.* Exit code 2 means the stamp and the hash disagree, and by then
    whatever the run decided to write is already written, so the outcome stays `stored` or
    `no_change`. The disagreement goes into `detail` instead: a row reading as an ordinary
    no-op while the run raised an alarm is exactly the *indistinguishable from an absence*
    failure `runlog` was built to prevent, and `detail` is where the runner's own words belong.
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
    archive: Optional[Archive] = None,
    force_parse: bool = False,
    url: Optional[str] = None,
) -> Verdict:
    """Fetch, then hand the archive to the sequencing above with a real database behind it.

    sqlalchemy is imported here rather than at the top for the reason the township seed gives:
    the sequencing is testable without a database, and that has to mean without the database
    libraries too, or the tests only run where the stack already does.

    **The run is recorded here and not inside `ingest_archive`**, which is where item 10's
    `run.py` puts it too. Two reasons, and neither is symmetry: `ingest_archive` is handed a
    *store* rather than a session precisely so its sequencing can be tested with no database at
    all, and the row has to be written **after** the attempt in its own transaction — the no-op
    path has just rolled its transaction back, and a failure has no transaction to ride on.

    Ticket 09 requires a run that wrote nothing to be answerable. Until this call existed item
    11 left no `ingest_run` row on any path, so its daily no-ops — twenty-nine in thirty (D34) —
    were as unrecoverable as item 10's were before `runlog` was written.
    """
    from ..db import pipeline_session_factory
    from .fda_store import PlaceStore

    Session = pipeline_session_factory(url)
    started = runlog.now()
    # Lineage over a scheduled run and over a hand-triggered one are different answers to "why
    # does this row exist" — item 10's DAG sets this, and item 11's now does as well.
    invoked_by = os.environ.get("UPTO_INVOKED_BY") or "cli"

    try:
        fetched = archive if archive is not None else fetch_archive()
        async with Session() as session:
            verdict = await ingest_archive(PlaceStore(session), fetched, force_parse=force_parse)
    except FdaUnavailable as failure:
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

    parser = argparse.ArgumentParser(description="Run item 11's reference ingest once.")
    parser.add_argument(
        "--file",
        help=(
            "read a saved archive instead of fetching. Re-runs a past day without the 17 MB "
            "download; the hash and the stamp come from the file, so the run is the same run."
        ),
    )
    parser.add_argument(
        "--force-parse",
        action="store_true",
        help=(
            "parse and write even when the content is already held. H14's test needs the "
            "short-circuit disabled so that what it tests is the constraint rather than this "
            "module's good behaviour."
        ),
    )
    args = parser.parse_args(argv)

    archive = None
    if args.file:
        with open(args.file, "rb") as handle:
            archive = read_archive(handle.read(), datetime.now(timezone.utc), source=SOURCE)

    try:
        verdict = asyncio.run(ingest_once(archive=archive, force_parse=args.force_parse))
    except FdaUnavailable as failure:
        # A source that did not answer is a failure. A source that answered the same bytes as
        # yesterday is not, and the two must not share an exit code.
        print("{}: FAILED — {}".format(SOURCE, failure), file=sys.stderr)
        return 1

    print(verdict.line())
    for line in verdict.township_report():
        print(line)
    for alarm in verdict.alarms:
        print("{}: {}".format(SOURCE, alarm), file=sys.stderr)
    return verdict.exit_code()


if __name__ == "__main__":
    sys.exit(main())
