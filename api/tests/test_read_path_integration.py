#!/usr/bin/env python3
"""Ticket 07's read path, against a real PostgreSQL.

Run inside the stack:
    docker compose exec api python /srv/tests/test_read_path_integration.py

The rows are planted rather than fetched, because the cases that matter are ones the live
data will not reliably present: an hour whose observation has not landed yet, an hour with
neither record, and two versions of one hour. The test builds its own database and drops it.

**The case the ticket names is the second one.** Inside the roughly ten-minute window before
an observation lands, the call must return the *forecast for that same hour* — never the
previous hour's observation. That is H15: a reading older than the hour it claims to describe
must never be returned silently.
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from upto.read.weather import ForecastJoinBroken, TownshipUnknown, reading_for  # noqa: E402
from upto.seed import township_station as seed  # noqa: E402
import _tempdb  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))
TEST_DB = "upto_readpath_check"

SEVEN = datetime(2026, 8, 11, 19, 0, tzinfo=TAIPEI)
SIX = SEVEN - timedelta(hours=1)

SHILIN = "63000110"      # 士林區 → 社子 C0A980, resolved by lowest altitude
STATION = "C0A980"


async def plant_observation(session, hour, temperature, detected_at, sha, weather="陰"):
    """`weather=None` plants the hour with `Weather` left out, which is not a hypothetical: one
    publication in a measured 25.5 hours did exactly that, at `ObsTime` 03:00, for nine of
    nineteen stations, with the temperature beside it present."""
    result = await session.execute(
        text(
            "insert into observation_publication (dataset_id, content_sha256, detected_at, payload_bytes) "
            "values ('O-A0001-001', :sha, :detected, 100) returning id"
        ),
        {"sha": sha, "detected": detected_at},
    )
    publication = result.scalar()
    planted = [("AirTemperature", temperature)]
    if weather is not None:
        planted.append(("Weather", weather))
    for element, value in planted:
        await session.execute(
            text(
                "insert into observation_reading (publication_id, station_id, station_name, county, "
                "town, town_code, observed_at, element, value) values (:p, :s, '社子', '臺北市', "
                "'士林區', :code, :hour, :element, :value)"
            ),
            {"p": publication, "s": STATION, "code": SHILIN, "hour": hour,
             "element": element, "value": value},
        )
    await session.commit()
    return publication


async def plant_forecast(session, hour, temperature, detected_at, sha, weather=None,
                         weather_code=None):
    result = await session.execute(
        text(
            "insert into forecast_publication (dataset_id, content_sha256, detected_at, payload_bytes) "
            "values ('F-D0047-061', :sha, :detected, 100) returning id"
        ),
        {"sha": sha, "detected": detected_at},
    )
    publication = result.scalar()
    rows = [("溫度", "Temperature", temperature)]
    if weather is not None:
        rows.append(("天氣現象", "Weather", weather))
    # `WeatherCode` shares the 天氣現象 element with `Weather` and is planted separately, because
    # the two are separately absent in principle — even though the current publication pairs them
    # perfectly (384 slots each, zero mismatches in either direction, measured 2026-08-18).
    if weather_code is not None:
        rows.append(("天氣現象", "WeatherCode", weather_code))
    for element, measure, value in rows:
        await session.execute(
            text(
                "insert into forecast_reading (publication_id, township_code, township, "
                "element, measure, slot_start, slot_end, value) values (:p, :code, '士林區', "
                ":element, :measure, :hour, :end, :value)"
            ),
            {"p": publication, "code": SHILIN, "element": element, "measure": measure,
             "hour": hour, "end": hour + timedelta(hours=1), "value": value},
        )
    await session.commit()
    return publication


async def scenario(test_url):
    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        await seed.load(test_url)

    # ---- the ticket's central case: the observation for the hour has not landed -----------
    # Six o'clock has an observation; seven o'clock has only a forecast. Asking for seven must
    # return the forecast for seven, never the observation for six.
    async with Session() as session:
        await plant_observation(session, SIX, "28.0", SIX + timedelta(minutes=9), "a" * 64)
        await plant_forecast(session, SEVEN, "31", SIX, "b" * 64, weather="多雲")

    async with Session() as session:
        reading = await reading_for(session, SHILIN, SEVEN)
    assert reading.kind == "forecast", "expected the forecast for that hour, got {}".format(reading.kind)
    assert reading.hour == SEVEN
    assert reading.measures["temperature_c"] == "31"
    assert reading.provenance.time_label == "detected", "a forecast stamp is a detection time (D42)"
    print("  window: the previous hour's observation was not offered")

    # ---- the home screen's weather icon reads a code, not a phrase (2026-08-18) -----------
    #
    # **The raw two-character string, never an integer.** The leading zero is part of the value
    # everywhere CWA publishes it, so a surface reconstructing it would be recovering information
    # this API had thrown away. **And the text cannot substitute:** code 15 publishes under two
    # different strings in the current publication — 短暫陣雨或雷雨 and 午後短暫雷陣雨 — and it is
    # that publication's *most common* condition, so a text→icon map is many-to-one on the majority
    # case rather than on a tail.
    coded = SEVEN + timedelta(hours=2)
    uncoded = SEVEN + timedelta(hours=3)
    async with Session() as session:
        await plant_forecast(session, coded, "30", SIX, "d" * 64, weather="晴",
                             weather_code="01")
        await plant_forecast(session, uncoded, "30", SIX, "e" * 64, weather="陰")
    async with Session() as session:
        reading = await reading_for(session, SHILIN, coded)
    assert reading.measures["weather_code"] == "01", reading.measures
    assert reading.measures["weather_text"] == "晴", reading.measures
    assert reading.measures["weather_code"] != 1, "the code must not have been made numeric"

    # **Separately absent — and the key is still there, holding `None`.** That is this payload's
    # existing contract for every measure the source did not publish, and it was asserted the wrong
    # way round here first: the test expected the key to be missing. Keeping the shape fixed is the
    # better contract for a surface, because a caller checks one thing (is the value null) rather
    # than two (is the key present, and is it null) — so a code-keyed icon draws nothing on a null
    # instead of guessing a glyph from a phrase.
    async with Session() as session:
        reading = await reading_for(session, SHILIN, uncoded)
    assert reading.measures["weather_text"] == "陰", reading.measures
    assert reading.measures["weather_code"] is None, reading.measures
    assert "weather_code" in reading.measures, "the key stays; only the value goes"
    print("  weather_code: the raw two-character code is passed through, and absent when the "
          "source omits it")

    # ---- the ordinary case: the observation has landed ------------------------------------
    async with Session() as session:
        await plant_observation(session, SEVEN, "29.5", SEVEN + timedelta(minutes=9), "c" * 64)
    async with Session() as session:
        reading = await reading_for(session, SHILIN, SEVEN)
    assert reading.kind == "observation", "the observation must win once it exists (D36)"
    assert reading.measures["temperature_c"] == "29.5"
    assert reading.station_id == STATION
    assert reading.provenance.time_label == "retrieved"
    print("  observation present: it wins over the forecast for the same hour")

    # ---- two versions of one hour: the later one answers ----------------------------------
    # Measured 2026-08-11: the observation is revised in place inside its own hour. Taking the
    # latest is an assumption flagged in _map.md, not a ruling — this test pins the current
    # behaviour so a ruling either way is a visible change.
    async with Session() as session:
        await plant_observation(session, SEVEN, "29.9", SEVEN + timedelta(minutes=40), "d" * 64)
    async with Session() as session:
        reading = await reading_for(session, SHILIN, SEVEN)
    assert reading.measures["temperature_c"] == "29.9", "expected the later revision of that hour"
    later_publication = reading.provenance.publication_id
    print("  revision: the later publication for that hour answered")

    # The earlier version is still there, which is what makes the assumption reversible and
    # what lets a round that pinned it still read as it did (D15).
    async with Session() as session:
        kept = await session.execute(
            text(
                "select count(distinct publication_id) from observation_reading "
                "where station_id = :s and observed_at = :hour"
            ),
            {"s": STATION, "hour": SEVEN},
        )
        assert kept.scalar() == 2, "an earlier version was overwritten"
    print("  revision: the earlier version is still stored")

    # ---- neither record: a stated absence, not a guess and not a crash --------------------
    empty_hour = SEVEN + timedelta(days=30)
    async with Session() as session:
        reading = await reading_for(session, SHILIN, empty_hour)
    assert reading.kind == "absent"
    assert not reading.present
    assert reading.absence_reason, "an absence has to say why"
    assert reading.measures == {}
    print("  absence: stated with a reason")

    # ---- an unknown township is an error, not an absence ----------------------------------
    async with Session() as session:
        try:
            await reading_for(session, "99999999", SEVEN)
            raise AssertionError("an unknown township code must not read as an absence")
        except TownshipUnknown:
            pass
    print("  unknown township: refused")

    # ---- a broken name join is an error, not an absence -----------------------------------
    # Since revision 0003 the join is on the geocode, so this can no longer be a misspelling.
    # It now means the ingest never ran for this code — still an error rather than an absence,
    # because reported as an absence it is indistinguishable from "no forecast this hour".
    async with Session() as session:
        await session.execute(text("delete from forecast_reading"))
        await session.execute(
            text("delete from observation_reading where observed_at = :hour"), {"hour": SEVEN}
        )
        await session.commit()
    async with Session() as session:
        try:
            await reading_for(session, SHILIN, SEVEN)
            raise AssertionError("a name that matches no forecast row must not read as an absence")
        except ForecastJoinBroken:
            pass
    print("  no forecast for the code at all: refused rather than reported as an absence")

    await containing_slot(Session)
    await absent_element(Session)

    await engine.dispose()
    print("read path: observation, fallback, revision, absence and both refusals all hold")
    return later_publication


async def absent_element(Session):
    """D58: **a measure the source left out is a key holding `None`, never a missing key.**

    Two different facts used to look identical in the response, because both were an absent key:
    *this dataset has no such measure* — the observation dataset carries no rain probability, ever
    — and *this publication left it out*, which was measured happening. The first is permanent and
    tells the caller to stop asking; the second is a hole in one hour.

    Planted here: an hour whose observation carries `AirTemperature` and no `Weather`.
    """
    hour = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    async with Session() as session:
        await plant_observation(session, hour, "27", hour + timedelta(minutes=9), "ab" * 32,
                                weather=None)
        # A forecast for the same hour, so a fallback would visibly succeed if one happened. It
        # must not: the observation exists, and mixing sources inside one answer would make `kind`
        # and the publication id a lie about half the card.
        await plant_forecast(session, hour, "31", hour - timedelta(hours=4), "cd" * 32,
                            weather="多雲")

    async with Session() as session:
        reading = await reading_for(session, SHILIN, hour)

    assert reading.kind == "observation", "the observation exists; it must answer"
    assert reading.measures["temperature_c"] == "27"

    assert "weather_text" in reading.measures, (
        "D58: a measure the source left out must still have a key — omitting it makes 'the "
        "dataset has no such measure' and 'this publication left it out' indistinguishable"
    )
    assert reading.measures["weather_text"] is None, (
        "the key must hold None, not the forecast's 多雲: an observation answer that borrows one "
        "field from the forecast makes its own publication id false for that field"
    )
    print("  absent element: the key is present and holds None, and no source is mixed in")

    assert "rain_probability_pct" not in reading.measures, (
        "the observation dataset carries no rain probability at all, so its key must be absent "
        "rather than None — that is the distinction D58 exists to make"
    )
    print("  absent element: a measure the dataset never carries has no key at all")


async def containing_slot(Session):
    """The 2026-08-12 ruling: a value is read from the slot that CONTAINS the hour.

    Planted to match what CWA actually publishes, which was measured on publication 27 rather
    than assumed:

      * hourly elements (`溫度`) carry **`slot_end` NULL**, spaced one hour near-term and
        **three hours further out** — the far-out ones are the reason a
        `coalesce(slot_end, slot_start + 1 hour)` fix is wrong, and they are planted here so
        that shortcut fails this test
      * three-hourly elements (`天氣現象`) carry `slot_end`, spanning 09:00–12:00 and so on

    Before the ruling the query matched `slot_start = :hour`, so one hour in three looked
    complete and the other two returned half a card with no error and no absence_reason.
    """
    nine = SEVEN.replace(hour=9)          # 09:00 Taipei — a block start
    ten = SEVEN.replace(hour=10)          # inside the 09:00–12:00 block
    eighteen = SEVEN.replace(hour=18)     # a far-out hourly slot, three hours wide, end NULL
    nineteen = SEVEN.replace(hour=19)     # inside it

    async with Session() as session:
        await session.execute(text("delete from forecast_reading"))
        await session.execute(text("delete from forecast_publication"))
        publication = (
            await session.execute(
                text(
                    "insert into forecast_publication (dataset_id, content_sha256, detected_at, "
                    "payload_bytes) values ('F-D0047-061', :sha, :detected, 100) returning id"
                ),
                {"sha": "c" * 64, "detected": SEVEN},
            )
        ).scalar()

        planted = [
            # 溫度: hourly at 09 and 10, then a three-hour spacing from 18 with NULL end.
            ("溫度", "Temperature", nine, None, "30"),
            ("溫度", "Temperature", ten, None, "31"),
            ("溫度", "Temperature", eighteen, None, "27"),
            ("溫度", "Temperature", eighteen + timedelta(hours=3), None, "25"),
            # 天氣現象: one three-hour block covering 09:00–12:00, with its end stated.
            ("天氣現象", "Weather", nine, nine + timedelta(hours=3), "多雲"),
        ]
        for element, measure, start, end, value in planted:
            await session.execute(
                text(
                    "insert into forecast_reading (publication_id, township_code, township, "
                    "element, measure, slot_start, slot_end, value) values (:p, :code, '士林區', "
                    ":element, :measure, :start, :end, :value)"
                ),
                {"p": publication, "code": SHILIN, "element": element, "measure": measure,
                 "start": start, "end": end, "value": value},
            )
        await session.commit()

    async with Session() as session:
        reading = await reading_for(session, SHILIN, ten)
    assert reading.kind == "forecast", reading.kind
    # The hourly element belongs to 10:00 itself.
    assert reading.measures["temperature_c"] == "31", reading.measures
    # The three-hourly one comes from the block that contains 10:00 and did not start on it.
    # This is the assertion the old `slot_start = :hour` query failed.
    assert reading.measures.get("weather_text") == "多雲", (
        "10:00 must read the 09:00–12:00 block; got {}".format(reading.measures)
    )
    start, end = reading.slots["weather_text"]
    assert start == nine and end == nine + timedelta(hours=3), reading.slots["weather_text"]
    print("  containing slot: 10:00 reads the 09:00–12:00 block, and says which block it was")

    async with Session() as session:
        reading = await reading_for(session, SHILIN, nineteen)
    # 19:00 sits inside an hourly-series slot that is three hours wide and stores NULL as its
    # end. A one-hour assumption returns nothing here, which is exactly the bug moved to the
    # far end of the horizon instead of fixed.
    assert reading.measures.get("temperature_c") == "27", (
        "19:00 must read the 18:00 slot, whose extent comes from the next slot's start, not "
        "from an assumed hour; got {}".format(reading.measures)
    )
    start, end = reading.slots["temperature_c"]
    assert (start, end) == (eighteen, eighteen + timedelta(hours=3)), reading.slots["temperature_c"]
    print("  containing slot: a NULL slot_end takes its extent from the next slot, not from +1h")

    # The last slot in a series covers its own start and nothing after it. Extending it would
    # invent a horizon the source never published — and a stale forecast presented as current
    # is worse than an absence, because D15 would pin it into a round.
    async with Session() as session:
        reading = await reading_for(session, SHILIN, eighteen + timedelta(hours=4))
    assert "temperature_c" not in reading.measures, (
        "an hour past the last slot must not inherit it: {}".format(reading.measures)
    )
    print("  containing slot: the last slot does not extend past itself")


async def with_temporary_database() -> int:
    """The shared helper (`_tempdb`): migrated twice, dropped afterwards whatever happens."""
    return await _tempdb.with_temporary_database(TEST_DB, lambda url, _environment: scenario(url))


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
