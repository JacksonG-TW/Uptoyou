"""MVP item 14 — where a reading came from, answered over stored rows only.

The reveal panel answers *why this place?* for a person. This answers it for a model, over the
same records. At this point the pipeline has written ingest rows only, so this covers ingest —
there are no weight contributions yet.

**H20 is designed in here rather than added later, and that is the whole reason this module is
narrow.** The hazard is that a lineage tool is built to be *useful*, and the most useful answer
is the complete one: the trail runs into `weight_contribution`, whose `private`-channel rows
carry a member and a reason its owner was promised nobody would see (D13, §3.0). Answered
completely, *"why did this place lose?"* is H3 firing through a door nobody watches — it is not
a browser payload, so the network tab that would catch H3 never sees it.

**So the boundary is structural, not a filter applied at the end.** These functions can only
read four tables — publications, readings, runs and the township map. **There is no query here
that mentions a member, a channel, or a weight**, and a test asserts the tool refuses rather
than relying on nothing having asked. When the weight engine lands, the aggregate-only rule
H20 states is a new function with its own test, not a widened one of these.

**Nothing is computed and presented as recorded.** Every field returned is a column. Where a
number would have to be derived, the answer says so instead — which is why a publication's
reading count is queried rather than remembered.

**A forecast's timestamp is a detection time** (D42): CWA never says when a forecast was
published, so every answer carries the label with the value and never the value alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# `text` is imported inside each function that runs SQL. The refusal and the label rules are
# pure, and a test that needs neither a database nor its driver is the test H20 asks for.

FORECAST_DATASET = "F-D0047-061"
OBSERVATION_DATASET = "O-A0001-001"

# The only tables this module may read. Stated as data so the test can assert it, rather than
# left as a property of whatever the queries happen to say today.
READABLE_TABLES = frozenset(
    {
        "forecast_publication",
        "forecast_reading",
        "observation_publication",
        "observation_reading",
        "place_publication",
        "reference_place",
        "ingest_run",
        "township_station",
        # **Added 2026-08-19 when H20 was narrowed for `explain_round` (D108, `06c9f9f`).** D108's
        # commitment is worthless unless somebody can recompute it, and recomputing needs the round
        # and the member **set** — the decider is drawn from that set, so the ids are an input to the
        # arithmetic rather than a fact about people being disclosed.
        "round",
        "member",
        # **Added 2026-08-27 for A12/RR-8 (revision 0030).** It holds a round id and the primary key
        # of one `forecast_reading` row — no member, no preference, no reason. The reading it names
        # is the one every rain factor in the round was measured against, and the place standing on
        # it produces no contribution (D43), so nothing else in the schema can name it.
        "round_forecast_baseline",
    }
)

# Named so the refusal can quote them. **Narrowed 2026-08-19 from `member` to a member's private
# facts** (owner, with D55's narrowing the same day): who rolled is a public act — everybody performs
# it, visibly, in the same moment, on purpose — while what somebody *wants* is not. So a member id may
# be read to verify a roll; a member's preference, contribution, reason or channel may not.
FORBIDDEN_SUBJECTS = ("preference", "contribution", "reason", "private channel")


ROUND_COMMITMENT = """
select id, circle_id, status, die1, die2, winning_place_id, seed_commit, outcome_seed, seat_ids
from round where id = :round_id
"""

ROUND_SEATS = """
select id from member where circle_id = :circle_id order by id
"""


class LineageRefused(PermissionError):
    """The question asks for something H20 forbids, and the refusal is the answer.

    Raised rather than answered partially, because a partial answer to "why did this place
    lose" is the shape that looks like the feature working.
    """


@dataclass
class Answer:
    """Every answer carries what it was asked and which rows it stands on."""

    question: str
    found: bool
    detail: Dict[str, Any] = field(default_factory=dict)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    note: Optional[str] = None


def _time_label(dataset_id: str) -> str:
    """A forecast stamp is a detection time; an observation's is when we retrieved it."""
    return "detected_at" if dataset_id == FORECAST_DATASET else "retrieved_at"


READING_SOURCE_FORECAST = """
select p.id as publication_id, p.dataset_id, p.content_sha256, p.detected_at, p.payload_bytes,
       r.township_code, r.township, r.element, r.measure, r.slot_start, r.slot_end, r.value,
       run.id as run_id, run.outcome, run.invoked_by, run.started_at, run.finished_at
from forecast_reading r
join forecast_publication p on p.id = r.publication_id
left join ingest_run run on run.forecast_publication_id = p.id
where r.township_code = :township_code and r.slot_start = :hour
  and r.element = :element and r.measure = :measure
order by p.detected_at desc
"""

READING_SOURCE_OBSERVATION = """
select p.id as publication_id, p.dataset_id, p.content_sha256, p.detected_at, p.payload_bytes,
       r.station_id, r.station_name, r.town_code, r.observed_at, r.element, r.value,
       run.id as run_id, run.outcome, run.invoked_by, run.started_at, run.finished_at
from observation_reading r
join observation_publication p on p.id = r.publication_id
left join ingest_run run on run.observation_publication_id = p.id
where r.station_id = :station_id and r.observed_at = :hour and r.element = :element
order by p.detected_at desc
"""


async def forecast_reading_source(
    session, township_code: str, hour: datetime, element: str, measure: str
) -> Answer:
    """Every stored version of one forecast reading, newest first.

    Plural on purpose: the same described hour is published repeatedly and D18 keeps every
    version, so "where did this come from" has more than one true answer and the caller is
    entitled to see that rather than be handed the latest as though it were the only one.
    """
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(READING_SOURCE_FORECAST),
            {"township_code": township_code, "hour": hour, "element": element, "measure": measure},
        )
    ).mappings().all()
    label = _time_label(FORECAST_DATASET)
    return Answer(
        question="forecast reading source",
        found=bool(rows),
        detail={
            "township_code": township_code,
            "hour": hour.isoformat(),
            "element": element,
            "measure": measure,
            "versions": len(rows),
            "time_label": label,
            "time_label_note": (
                "the forecast carries no publication time, so this is when the ingest first "
                "saw the content — never present it as a publication time (D42)"
            ),
        },
        rows=[
            {
                "publication_id": row["publication_id"],
                "dataset_id": row["dataset_id"],
                "content_sha256": row["content_sha256"],
                label: row["detected_at"].isoformat(),
                "value": row["value"],
                "slot_start": row["slot_start"].isoformat(),
                "slot_end": row["slot_end"].isoformat() if row["slot_end"] else None,
                "township": row["township"],
                "run": _run_of(row),
            }
            for row in rows
        ],
        note=None if rows else "no stored forecast reading matches that township, hour and measure",
    )


async def observation_reading_source(
    session, station_id: str, hour: datetime, element: str
) -> Answer:
    from sqlalchemy import text

    rows = (
        await session.execute(
            text(READING_SOURCE_OBSERVATION),
            {"station_id": station_id, "hour": hour, "element": element},
        )
    ).mappings().all()
    label = _time_label(OBSERVATION_DATASET)
    return Answer(
        question="observation reading source",
        found=bool(rows),
        detail={
            "station_id": station_id,
            "hour": hour.isoformat(),
            "element": element,
            "versions": len(rows),
            "time_label": label,
            "time_label_note": (
                "the observation states its own ObsTime, which is the hour described; this "
                "stamp is only when the ingest retrieved it"
            ),
        },
        rows=[
            {
                "publication_id": row["publication_id"],
                "dataset_id": row["dataset_id"],
                "content_sha256": row["content_sha256"],
                label: row["detected_at"].isoformat(),
                "observed_at": row["observed_at"].isoformat(),
                "value": row["value"],
                "station_name": row["station_name"],
                "town_code": row["town_code"],
                "run": _run_of(row),
            }
            for row in rows
        ],
        note=None if rows else "no stored observation matches that station, hour and element",
    )


def _run_of(row) -> Optional[Dict[str, Any]]:
    """The run that wrote a publication, where one is recorded.

    Nullable rather than assumed: the publications written before `ingest_run` existed have no
    run, and inventing one would be exactly the *computed and presented as recorded* failure
    this module refuses.
    """
    if row["run_id"] is None:
        return None
    return {
        "run_id": row["run_id"],
        "outcome": row["outcome"],
        "invoked_by": row["invoked_by"],
        "started_at": row["started_at"].isoformat(),
        "finished_at": row["finished_at"].isoformat(),
    }


RUN = """
select id, source, started_at, finished_at, outcome, rows_written, detail, invoked_by,
       forecast_publication_id, observation_publication_id, place_publication_id
from ingest_run where id = :run_id
"""

# Two statements rather than one with `(:source is null or source = :source)`. asyncpg cannot
# infer the type of a parameter that appears only against NULL and a text column, and fails with
# AmbiguousParameterError — a driver limit rather than bad SQL. A cast would work; two plain
# statements read better than explaining a cast.
RUN_HISTORY_ALL = """
select id, source, started_at, finished_at, outcome, rows_written, invoked_by
from ingest_run
order by started_at desc, id desc
limit :limit
"""

RUN_HISTORY_FOR_SOURCE = """
select id, source, started_at, finished_at, outcome, rows_written, invoked_by
from ingest_run
where source = :source
order by started_at desc, id desc
limit :limit
"""


async def run_detail(session, run_id: int) -> Answer:
    """What one run did — including a run that wrote nothing.

    A no-change run is the ordinary outcome, about twenty of twenty-four daily forecast runs
    (D42), and ticket 09 requires it to be **lineage worth pointing at rather than an
    absence**. It is a row here, described as such, and distinguishable from a run that failed.
    """
    from sqlalchemy import text

    row = (await session.execute(text(RUN), {"run_id": run_id})).mappings().first()
    if row is None:
        return Answer(
            question="run detail",
            found=False,
            detail={"run_id": run_id},
            note="no run with that id is recorded",
        )
    publication_id = (
        row["forecast_publication_id"]
        or row["observation_publication_id"]
        or row["place_publication_id"]
    )
    written = None
    if publication_id is not None:
        # **`rows_newly_stored`, not `rows_written`, and the rename is the point** (H32's second
        # half, closed by ruling 2026-08-18). The column counts rows the database *accepted* as
        # new. A rows-only replay rebuilds every row of a table and records `no_change` with a
        # count of 0, because the claim short-circuits on a hash already held — so a reader
        # summing "rows written" sees a backfill as a no-op. The ledger is not changing; what it
        # is called here is, because this is the sentence a model reads back to a person.
        written = {
            "publication_id": publication_id,
            "rows_newly_stored": row["rows_written"],
            "rows_newly_stored_means": "rows the database accepted as new. A replay that rebuilt "
                                       "an entire table reports 0 here and says what it did in "
                                       "`verdict` — see the run's detail line, not this count.",
        }
    return Answer(
        question="run detail",
        found=True,
        detail={
            "run_id": row["id"],
            "source": row["source"],
            "outcome": row["outcome"],
            "outcome_meaning": {
                "stored": "the source published content the ingest had not held before",
                "no_change": "the source answered and republished nothing — a success, and the "
                             "ordinary outcome for the forecast (D42). **A rows-only replay also "
                             "records no_change**: the claim short-circuits on a hash already "
                             "held, so the rebuild is in `verdict` and not in any count",
                "failed": "the source did not answer usefully; this is not the same as no_change",
            }[row["outcome"]],
            "started_at": row["started_at"].isoformat(),
            "finished_at": row["finished_at"].isoformat(),
            "invoked_by": row["invoked_by"],
            "verdict": row["detail"],
            "wrote": written,
        },
        note=None,
    )


async def run_history(session, source: Optional[str] = None, limit: int = 20) -> Answer:
    from sqlalchemy import text

    if source is None:
        rows = (await session.execute(text(RUN_HISTORY_ALL), {"limit": limit})).mappings().all()
    else:
        rows = (
            await session.execute(
                text(RUN_HISTORY_FOR_SOURCE), {"source": source, "limit": limit}
            )
        ).mappings().all()
    return Answer(
        question="run history",
        found=bool(rows),
        detail={"source": source, "returned": len(rows)},
        rows=[
            {
                "run_id": row["id"],
                "source": row["source"],
                "outcome": row["outcome"],
                # Same rename as `run detail` above, same reason: a count of rows *newly
                # stored*, which a replay leaves at 0 however much it rewrote.
                "rows_newly_stored": row["rows_written"],
                "invoked_by": row["invoked_by"],
                "started_at": row["started_at"].isoformat(),
            }
            for row in rows
        ],
        note=None if rows else "no runs recorded yet",
    )


PUBLICATION_FORECAST = """
select p.id, p.dataset_id, p.content_sha256, p.detected_at, p.payload_bytes,
       (select count(*) from forecast_reading r where r.publication_id = p.id) as reading_rows,
       (select count(distinct r.township_code) from forecast_reading r where r.publication_id = p.id) as townships
from forecast_publication p where p.id = :publication_id
"""

PUBLICATION_OBSERVATION = """
select p.id, p.dataset_id, p.content_sha256, p.detected_at, p.payload_bytes,
       (select count(*) from observation_reading r where r.publication_id = p.id) as reading_rows,
       (select count(distinct r.station_id) from observation_reading r where r.publication_id = p.id) as stations
from observation_publication p where p.id = :publication_id
"""


async def publication_detail(session, dataset_id: str, publication_id: int) -> Answer:
    """What one publication holds. The counts are queried, never remembered."""
    from sqlalchemy import text

    statement = (
        PUBLICATION_FORECAST if dataset_id == FORECAST_DATASET else PUBLICATION_OBSERVATION
    )
    row = (
        await session.execute(text(statement), {"publication_id": publication_id})
    ).mappings().first()
    if row is None:
        return Answer(
            question="publication detail",
            found=False,
            detail={"dataset_id": dataset_id, "publication_id": publication_id},
            note="no publication with that id in that dataset",
        )
    label = _time_label(dataset_id)
    body = {
        "publication_id": row["id"],
        "dataset_id": row["dataset_id"],
        "content_sha256": row["content_sha256"],
        label: row["detected_at"].isoformat(),
        "payload_bytes": row["payload_bytes"],
        "reading_rows": row["reading_rows"],
    }
    body["townships" if dataset_id == FORECAST_DATASET else "stations"] = (
        row["townships"] if dataset_id == FORECAST_DATASET else row["stations"]
    )
    return Answer(question="publication detail", found=True, detail=body)


def refuse(subject: str) -> None:
    """H20's boundary, as a function so the refusal has one wording and one test.

    The tool answers over `contextual` and `commercial` in full and over `private` **only in
    aggregate** — that a private contribution applied and its numeric effect, never whose or
    why. None of that is reachable from here at all: the weight engine is unbuilt and this
    module reads no table that carries a member or a channel. Until it does, the honest answer
    to a question about one is a refusal that says why.
    """
    raise LineageRefused(
        "this tool answers lineage over ingested rows and cannot answer about {}. The private "
        "weight channel is answerable only in aggregate — that a contribution applied and its "
        "numeric effect, never whose or why (H20, D13) — and the weight engine is not built, so "
        "no such row exists to aggregate. Asking a person's reason out of a lineage tool is the "
        "leak this boundary exists to stop.".format(subject)
    )


# A12 / RR-8 — the reading every rain factor in a round was measured against (revision 0030).
# **Joined to `forecast_reading` for the value rather than storing a copy of it (D28):** the number
# lives in the publication, and the composite FK is what guarantees it is still there to read.
ROUND_BASELINE = """
select b.township_code, b.publication_id, b.element, b.measure, b.slot_start,
       r.value as probability, p.detected_at as publication_detected_at
  from round_forecast_baseline b
  join forecast_reading r
    on r.publication_id = b.publication_id and r.township_code = b.township_code
   and r.element = b.element and r.measure = b.measure and r.slot_start = b.slot_start
  join forecast_publication p on p.id = b.publication_id
 where b.round_id = :round_id
"""

async def explain_round(session, round_id: int) -> Answer:
    """D108's verification, recomputed rather than asserted — the point of the whole mechanism.

    The commitment is worth nothing unless somebody can check it, and **verifiability nobody
    exercises is trust** — that was named as a cost when the mechanism was proposed, and this is the
    payment. Everything here is derived from the revealed seed by the same module the round used, then
    compared against what the round stored. The answer is not *we say this was fair*; it is *here is
    the arithmetic, and here is where it agrees*.

    **Member ids, never nicknames** — the trade offered when H20 was narrowed and the one the owner
    took. The ids are an input to the arithmetic (the decider is drawn from the member set); a
    nickname would be a fact about a person that verification does not need.

    **It carries the hex-decode warning, and that is not decoration.** Found by the frontend session
    checking the commitment by hand: the seed is 32 bytes *written as hex*, and hashing the ASCII
    string produces a digest matching nothing. A person who tries the obvious thing first gets a
    mismatch, and **the honest conclusion available to them at that point is that the product is
    lying.** One sentence closes a route to exactly the wrong belief about the thing this proves.

    An open round reveals no seed and says so: before close, a member holding it could compute the
    winner and then choose whether to tap, which is the preference D91 forbids.
    """
    from sqlalchemy import text  # noqa: PLC0415 — the module keeps SQL imports local (see the top)

    from ..engine import draw  # noqa: PLC0415 — the round's own module, never a second copy

    question = "recompute round {} from its revealed seed".format(round_id)
    row = (await session.execute(text(ROUND_COMMITMENT), {"round_id": round_id})).mappings().first()
    if row is None:
        return Answer(question=question, found=False, rows=[], note="no such round.")

    decode = (
        "The seed is 32 bytes WRITTEN AS HEX. Decode before hashing — "
        "sha256(bytes.fromhex(revealed_seed)), not sha256 of the text. Hashing the string is the "
        "obvious first attempt and matches nothing, which reads as a broken commitment when it is "
        "only a decoding mistake."
    )
    if row["seed_commit"] is None:
        return Answer(
            question=question,
            found=True,
            detail={"status": row["status"]},
            rows=[{"status": row["status"], "commitment": None}],
            note="this round predates revision 0026 and carries no commitment. It cannot be given "
                 "one now: a commitment made after the places were known would not be a commitment.",
        )
    if row["status"] != "closed":
        return Answer(
            question=question,
            found=True,
            detail={"status": row["status"]},
            rows=[{"status": row["status"], "seed_commit": row["seed_commit"],
                   "revealed_seed": None}],
            note="the round is open, so the seed is not revealed and the arithmetic cannot be checked "
                 "yet — a member holding it early could compute the winner and then choose whether "
                 "to tap, which is what the commitment prevents. " + decode,
        )

    seed = bytes(row["outcome_seed"])
    # **The seats pinned on the round, never live membership — and this line was wrong once already.**
    # `explain_round` found the live-read bug in the *roll* and then reproduced it in itself: it read
    # `member` by circle, so a member joining after the round still moved the recomputed decider and
    # the verdict stayed `false` after the roll was fixed. **A verifier that reads a different
    # question from the thing it verifies is worse than no verifier**, because its disagreement is
    # indistinguishable from a real one.
    pinned = list(row["seat_ids"] or [])
    ids = pinned or list(
        (await session.execute(text(ROUND_SEATS), {"circle_id": row["circle_id"]})).scalars().all()
    )
    decider = draw.deciding_member(seed, ids) if ids else None
    derived = draw.deciding_pair(seed, ids) if ids else None
    stored = (row["die1"], row["die2"])

    rows: List[Dict[str, Any]] = [{
        "commitment_published_at_open": row["seed_commit"],
        # Said out loud, because the verdict below means different things in the two cases: a round
        # predating revision 0027 has no pinned seats, so its decider is recomputed against today's
        # membership and a mismatch proves nothing about the round.
        "seats_pinned_at_open": bool(pinned),
        "seed_revealed_at_close": seed.hex(),
        # Each check states what was compared, not just a boolean nobody can trace back.
        "sha256_of_decoded_seed_equals_commitment": draw.verify(seed.hex(), row["seed_commit"]),
        "deciding_member_id": decider,
        "pair_derived_from_seed": list(derived) if derived else None,
        "pair_stored_on_the_round": list(stored) if stored[0] is not None else None,
        "stored_pair_equals_derived_pair": (derived == stored) if derived else None,
        "verdict": (
            "the stored result is what the committed seed produces"
            if derived == stored
            else "seats were not pinned when this round ran, so the decider cannot be recomputed"
            if not pinned
            else "MISMATCH — the stored result is not what the committed seed produces"
        ),
        "winning_place_id": row["winning_place_id"],
    }]
    for member_id in ids:
        rows.append({
            "member_id": member_id,
            "pair_derived_from_seed": list(draw.pair_for_member(seed, member_id)),
            "counts": member_id == decider,
        })

    # **A12 / RR-8 — the reading the rain factors were measured against, named.** D71 is relative:
    # a place's factor is `1 − gap/120` against the pool's lowest 降雨機率, and the place standing
    # on that lowest reading produces no contribution at all (D43). So without this the round's
    # arithmetic could not be reconstructed from its own rows — every factor would be a gap from a
    # number nothing recorded. Revision 0030 pins it; this reports it.
    baseline = (
        await session.execute(text(ROUND_BASELINE), {"round_id": round_id})
    ).mappings().first()
    if baseline is None:
        # **An absence with a shape (D112), and it is not the same as a baseline of zero.** No
        # reference place, no township, no reading for the hour, or a publication carrying none of
        # the pool's townships — in every case nothing was compared, which is a different fact from
        # a comparison that found no difference.
        rows.append({
            "rain_baseline": None,
            "note": "no rain comparison happened in this round — no baseline reading was recorded. "
                    "A round whose townships all held the same probability DOES record one and "
                    "stores no factors; this is the other case.",
        })
    else:
        rows.append({
            "rain_baseline_township": baseline["township_code"],
            "rain_baseline_probability": baseline["probability"],
            "rain_baseline_publication_id": baseline["publication_id"],
            "rain_baseline_slot_start": baseline["slot_start"],
            "rain_baseline_measure": baseline["measure"],
            "rain_baseline_publication_detected_at": baseline["publication_detected_at"],
            # **The factors themselves are deliberately not read here, and the boundary said so
            # first.** Reporting them meant selecting from `weight_contribution`, and both of this
            # module's structural guards fired: the table is outside `READABLE_TABLES` and the word
            # `reason` is in `FORBIDDEN_SUBJECTS`. That table holds a member's private preference
            # rows, and a filter to `contributor = 'weather'` narrows the rows without narrowing the
            # *reach* — the guard is structural precisely so a well-meaning filter cannot open it.
            # The baseline is what RR-8 asked for; a caller who has the round's factors can check
            # them against it, and `test_engine_load_integration.py` asserts the one-publication
            # rule where the credential to see contributions exists.
            "note": "every rain factor in this round is 1 − (that township's 降雨機率 − {}) / 120, "
                    "clamped at 0.5. The baseline township itself carries no record (D43).".format(
                        baseline["probability"]
                    ),
        })

    return Answer(question=question, found=True,
                  detail={"status": row["status"], "member_count": len(ids)},
                  rows=rows, note=decode)
