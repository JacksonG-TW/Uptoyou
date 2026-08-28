"""Write a Publication, or discover it is not new and say so quietly.

H14 is the hazard this file exists for: **an ingest that cannot be run twice.** The hourly
schedule guarantees the same content arrives repeatedly — about twenty of twenty-four daily
forecast runs carry nothing new (D42) — so "already have it" is the *normal* outcome and has
to be a silent success rather than an error or a duplicate row.

The mechanism is the unique constraint on (dataset_id, content_sha256), not a prior SELECT.
A check-then-insert is a race even with one worker, because a retry and a scheduled run can
overlap; `ON CONFLICT DO NOTHING` lets the database decide, which is the writer-that-is-not-
the-application argument PostgreSQL was chosen on (D5).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import signature
from . import cwa
from .cwa import FORECAST_DATASET, Publication


@dataclass(frozen=True)
class StoreResult:
    dataset_id: str
    content_sha256: str
    stored: bool          # False means the content was already held — a silent success
    publication_id: int | None
    rows_written: int

    def line(self) -> str:
        """One log line. A no-op has to read as success, not as a warning."""
        if not self.stored:
            return "{}: no change (hash {}…) — nothing published since the last run".format(
                self.dataset_id, self.content_sha256[:12]
            )
        return "{}: stored publication {} with {} readings (hash {}…)".format(
            self.dataset_id, self.publication_id, self.rows_written, self.content_sha256[:12]
        )


INSERT_PUBLICATION = """
insert into {table}
    (dataset_id, content_sha256, detected_at, payload_bytes, column_signature, column_names)
values
    (:dataset_id, :content_sha256, :detected_at, :payload_bytes,
     :column_signature, :column_names)
on conflict (dataset_id, content_sha256) do nothing
returning id
"""

# **A18: the observation publication says what it kept, and that is why it needs its own insert.**
# `stored_scope` exists on this table alone — the other publication tables store everything their
# source publishes, and a column asserting a filter that does not exist would be D112 inverted. The
# duplication is six column names; the alternative is a conditional column list built at runtime,
# which is harder to read than the statement it saves.
INSERT_OBSERVATION_PUBLICATION = """
insert into observation_publication
    (dataset_id, content_sha256, detected_at, payload_bytes, column_signature, column_names,
     stored_scope)
values
    (:dataset_id, :content_sha256, :detected_at, :payload_bytes,
     :column_signature, :column_names, :stored_scope)
on conflict (dataset_id, content_sha256) do nothing
returning id
"""

INSERT_FORECAST_READING = """
insert into forecast_reading
    (publication_id, township_code, township, element, measure, slot_start, slot_end, value)
values (:publication_id, :township_code, :township, :element, :measure, :slot_start, :slot_end, :value)
on conflict (publication_id, township_code, element, measure, slot_start) do nothing
"""

INSERT_OBSERVATION_READING = """
insert into observation_reading
    (publication_id, station_id, station_name, county, town, town_code, observed_at, element, value)
values (:publication_id, :station_id, :station_name, :county, :town, :town_code, :observed_at, :element, :value)
on conflict (publication_id, station_id, element, observed_at) do nothing
"""


async def store_publication(session: AsyncSession, publication: Publication) -> StoreResult:
    forecast = publication.dataset_id == FORECAST_DATASET
    table = "forecast_publication" if forecast else "observation_publication"

    parameters = {
        "dataset_id": publication.dataset_id,
        "content_sha256": publication.content_sha256,
        "detected_at": publication.detected_at,
        "payload_bytes": publication.payload_bytes,
        # D102 / M3: the payload's shape — the key set of one reading-bearing record, since a
        # JSON feed has no header. `NULL` on a publication that predates the signature.
        "column_signature": publication.column_signature or None,
        "column_names": signature.as_json(publication.column_names),
    }
    if forecast:
        statement_sql = INSERT_PUBLICATION.format(table=table)
    else:
        statement_sql = INSERT_OBSERVATION_PUBLICATION
        # A18: recorded as policy, not as outcome — it says which county's rows this run would keep,
        # so a publication that legitimately kept nothing is still distinguishable from one written
        # before the filter existed (`NULL`).
        parameters["stored_scope"] = cwa.STORED_COUNTY
    inserted = await session.execute(text(statement_sql), parameters)
    publication_id = inserted.scalar()

    if publication_id is None:
        # Already held. Nothing is written and nothing is wrong.
        await session.commit()
        return StoreResult(publication.dataset_id, publication.content_sha256, False, None, 0)

    if forecast:
        rows = [
            {
                "publication_id": publication_id,
                "township_code": row.township_code,
                "township": row.township,
                "element": row.element,
                "measure": row.measure,
                "slot_start": row.slot_start,
                "slot_end": row.slot_end,
                "value": row.value,
            }
            for row in publication.forecast_rows
        ]
        statement = INSERT_FORECAST_READING
    else:
        # **A18: the filter is here, and here is the point.** The hash above and D102's signature
        # were both taken from the whole payload, so D42's change detection still asks "did their
        # file change" rather than "did our policy". Only the keeping narrows.
        kept = [row for row in publication.observation_rows if cwa.in_stored_scope(row.county)]
        rows = [
            {
                "publication_id": publication_id,
                "station_id": row.station_id,
                "station_name": row.station_name,
                "county": row.county,
                "town": row.town,
                "town_code": row.town_code,
                "observed_at": row.observed_at,
                "element": row.element,
                "value": row.value,
            }
            for row in kept
        ]
        statement = INSERT_OBSERVATION_READING

    if rows:
        await session.execute(text(statement), rows)
    await session.commit()
    return StoreResult(publication.dataset_id, publication.content_sha256, True, publication_id, len(rows))
