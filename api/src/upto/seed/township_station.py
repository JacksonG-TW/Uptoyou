"""Ticket 06's seed — the twelve 臺北市 townships and the station each one reads.

Run it:  python -m upto.seed.township_station

**Every value here was measured, and the measurement is named.** Nine townships hold at least
one station; the station list and the altitudes come from `O-A0001-001` itself. Three hold
none, and their nearest was resolved once, offline, against 內政部國土測繪中心's
鄉鎮市區界線(TWD97經緯度) `TOWN_MOI_1140318`, whose datum is declared inside the file rather
than in its title (D32). **No coordinate arithmetic happens at run time and none happens
here** — this file is the result, not the calculation.

**Why a seed rather than a query.** The mapping changes when CWA adds or removes a station,
which is rare and never mid-round, and a run-time computation would make every read depend on
whichever publication happened to be latest. A row that can be read, quoted and pointed at is
what item 14 needs to answer for a reading's provenance.

**H25 is why the loader validates rather than trusts.** Seeded data that is too clean means the
code that copes with real data never runs, so the load checks its own claims against the
ingested observations and fails loudly instead of writing something plausible.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

# sqlalchemy and the engine are imported inside the functions that need them. The mapping and
# its self-check are pure data, and "tested without a database" has to mean without the
# database libraries too, or the tests only run where the stack already does.

TAIPEI = "臺北市"


@dataclass(frozen=True)
class Mapping:
    township_code: str
    township_name: str
    station_id: str
    station_name: str
    resolution: str
    distance_km: float | None = None
    margin_km: float | None = None
    source_note: str | None = None


# The nine that hold a station. Where more than one sits in the township, the lowest
# `StationAltitude` wins (D26) and the losing candidates are named in the note, because a
# tiebreak nobody can see is a tiebreak nobody can check.
IN_TOWNSHIP = [
    Mapping("63000010", "松山區", "C0AH70", "松山", "town_code"),
    Mapping("63000020", "信義區", "C0AC70", "信義", "town_code"),
    Mapping(
        "63000030", "大安區", "A0A010", "臺灣大學", "lowest_altitude",
        source_note="臺灣大學 17 m beat 大安森林 18 m",
    ),
    Mapping("63000050", "中正區", "466920", "臺北", "town_code"),
    Mapping(
        "63000080", "文山區", "C0AC80", "文山", "lowest_altitude",
        source_note="文山 40 m beat 國三甲005K 60 m — altitude drops the freeway sensor as a side effect",
    ),
    Mapping(
        "63000090", "南港區", "CAA040", "國三S016K", "town_code",
        source_note=(
            "the only instrument in the district, and a freeway sensor. 0.70 km from the "
            "centroid where the nearest non-freeway station is 信義 at 4.55 km"
        ),
    ),
    Mapping("63000100", "內湖區", "C0A9F0", "內湖", "town_code"),
    Mapping(
        "63000110", "士林區", "C0A980", "社子", "lowest_altitude",
        source_note="社子 11 m beat 天母 35, 科教館 60, 文化大學 424, 平等 426",
    ),
    Mapping(
        "63000120", "北投區", "C2AA10", "中八仙", "lowest_altitude",
        source_note="中八仙 16 m beat 石牌 37, 陽明山 607, 鞍部 838, 大屯山 1079",
    ),
]

# The three that hold none — D32. Distance and margin are the measurement, kept because a
# seeded row with no evidence is a guess wearing a schema.
OFFLINE = [
    Mapping(
        "63000040", "中山區", "C0AH70", "松山", "offline_centroid",
        distance_km=2.65, margin_km=1.03,
        source_note="centroid 25.069850, 121.538347 — TOWN_MOI_1140318, TWD97; 2nd was 科教館 at 3.68 km",
    ),
    Mapping(
        "63000060", "大同區", "466920", "臺北", "offline_centroid",
        distance_km=2.93, margin_km=0.68,
        source_note="centroid 25.064003, 121.513216 — TOWN_MOI_1140318, TWD97; 2nd was 科教館 at 3.61 km",
    ),
    Mapping(
        "63000070", "萬華區", "466920", "臺北", "offline_centroid",
        distance_km=1.99, margin_km=1.93,
        source_note="centroid 25.029365, 121.497356 — TOWN_MOI_1140318, TWD97; 2nd was 大安森林 at 3.92 km",
    ),
]

MAPPINGS = IN_TOWNSHIP + OFFLINE

# 臺北市 has twelve townships. Stating the number separately from the list is the point: a
# row quietly dropped from MAPPINGS would otherwise load cleanly and read as complete.
EXPECTED_TOWNSHIPS = 12

UPSERT = """
insert into township_station
    (township_code, township_name, station_id, station_name, resolution,
     distance_km, margin_km, source_note)
values
    (:township_code, :township_name, :station_id, :station_name, :resolution,
     :distance_km, :margin_km, :source_note)
on conflict (township_code) do update set
    township_name = excluded.township_name,
    station_id    = excluded.station_id,
    station_name  = excluded.station_name,
    resolution    = excluded.resolution,
    distance_km   = excluded.distance_km,
    margin_km     = excluded.margin_km,
    source_note   = excluded.source_note
"""


class SeedRefused(RuntimeError):
    """The seed did not match reality. Loading it anyway is how a wrong lookup goes unnoticed."""


def check_self_consistent() -> None:
    """Everything checkable without a database, checked before one is touched."""
    if len(MAPPINGS) != EXPECTED_TOWNSHIPS:
        raise SeedRefused(
            "臺北市 has {} townships and this seed carries {}. A township with no mapping is a "
            "loud failure at load time, never a null at read time.".format(
                EXPECTED_TOWNSHIPS, len(MAPPINGS)
            )
        )
    codes = [m.township_code for m in MAPPINGS]
    if len(set(codes)) != len(codes):
        raise SeedRefused("two rows claim the same township code")
    for mapping in MAPPINGS:
        if mapping.resolution == "offline_centroid" and mapping.distance_km is None:
            raise SeedRefused("{} was resolved offline and carries no distance".format(mapping.township_name))
        if mapping.resolution != "offline_centroid" and mapping.distance_km is not None:
            raise SeedRefused("{} carries a distance it did not need".format(mapping.township_name))


async def check_against_ingested(session) -> list[str]:
    """Check the seed against what the ingest actually saw. H25's whole point.

    Two claims are checkable and both are checked:

    * a station this seed names must exist in the observations;
    * a township this seed resolved *by code* must actually hold that station.

    Returns notes rather than raising where the ingest simply has no data yet — a fresh
    database is a legitimate state, and refusing to seed it would make the stack unbootable.
    """
    from sqlalchemy import text

    notes: list[str] = []
    result = await session.execute(
        text("select count(*) from observation_reading where county = :county"),
        {"county": TAIPEI},
    )
    if not result.scalar():
        return ["no ingested observations yet — the seed could not be checked against them"]

    # One station appears in every publication, and rows written before 0002 carry no
    # town_code. `distinct` returned both shapes and the later one won at random, which
    # silently downgraded every check to the weaker name comparison — max() takes the code
    # wherever any publication has it.
    known = await session.execute(
        text(
            "select station_id, max(town_code) as town_code, max(town) as town "
            "from observation_reading where county = :county group by station_id"
        ),
        {"county": TAIPEI},
    )
    stations = {row.station_id: (row.town_code, row.town) for row in known}

    for mapping in MAPPINGS:
        if mapping.station_id not in stations:
            raise SeedRefused(
                "{} maps to station {} ({}), which appears in no ingested observation".format(
                    mapping.township_name, mapping.station_id, mapping.station_name
                )
            )
        town_code, town_name = stations[mapping.station_id]
        if mapping.resolution == "offline_centroid":
            continue
        if town_code is None:
            notes.append(
                "{}: station {} predates the town_code column, checked by name instead".format(
                    mapping.township_name, mapping.station_id
                )
            )
            if town_name and town_name != mapping.township_name:
                raise SeedRefused(
                    "{} maps to station {}, which the observations place in {}".format(
                        mapping.township_name, mapping.station_id, town_name
                    )
                )
            continue
        if town_code != mapping.township_code:
            raise SeedRefused(
                "{} ({}) maps to station {}, which the observations place in town code {}".format(
                    mapping.township_name, mapping.township_code, mapping.station_id, town_code
                )
            )
    return notes


async def load(url: str | None = None) -> int:
    from sqlalchemy import text

    from ..db import pipeline_session_factory

    check_self_consistent()
    async with pipeline_session_factory(url)() as session:
        notes = await check_against_ingested(session)
        for note in notes:
            print("seed: note —", note)
        for mapping in MAPPINGS:
            await session.execute(text(UPSERT), vars(mapping))
        await session.commit()
        total = await session.execute(text("select count(*) from township_station"))
        count = total.scalar()
    if count != EXPECTED_TOWNSHIPS:
        raise SeedRefused("after loading, township_station holds {} rows".format(count))
    print("seed: {} townships mapped, {} of them resolved offline".format(count, len(OFFLINE)))
    return 0


def main() -> int:
    try:
        return asyncio.run(load())
    except SeedRefused as refused:
        print("seed: REFUSED — {}".format(refused), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
