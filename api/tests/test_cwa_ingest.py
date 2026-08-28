#!/usr/bin/env python3
"""Item 10's ingest, tested without a network or a database.

Run: python3 app/api/tests/test_cwa_ingest.py

Everything here is a pure function on a payload, which is why the parsing and the hashing
were separated from the fetching in the first place. The fixtures are trimmed real shapes,
not invented ones — the field names and the nesting are what CWA actually sends.
"""

import json
import os
import ssl
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.ingest import cwa  # noqa: E402

TAIPEI = timezone(timedelta(hours=8))


def forecast_payload(temperature="32", noise="anything"):
    return {
        "success": "true",
        # Envelope noise: present in real responses, different on every call, and must not
        # reach the hash — otherwise every hourly run looks like a new publication.
        "result": {"resource_id": noise, "fields": [{"id": noise}]},
        "records": {
            "Locations": [
                {
                    "LocationsName": "臺北市",
                    "Location": [
                        {
                            "LocationName": "中山區",
                            "Geocode": "63000040",
                            # Present in the real payload and deliberately never read: no datum
                            # is stated for them anywhere (H23), so D26 declines to store them.
                            "Latitude": "25.069850",
                            "Longitude": "121.538347",
                            "WeatherElement": [
                                {
                                    "ElementName": "溫度",
                                    "Time": [
                                        {
                                            "DataTime": "2026-08-11T18:00:00+08:00",
                                            "ElementValue": [{"Temperature": temperature}],
                                        }
                                    ],
                                },
                                {
                                    "ElementName": "舒適度指數",
                                    "Time": [
                                        {
                                            "DataTime": "2026-08-11T18:00:00+08:00",
                                            "ElementValue": [
                                                {"ComfortIndex": "29", "ComfortIndexDescription": "悶熱"}
                                            ],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ]
        },
    }


def observation_payload(temperature="30.5", weather="陰"):
    return {
        "success": "true",
        "records": {
            "Station": [
                {
                    "StationName": "臺北",
                    "StationId": "466920",
                    "ObsTime": {"DateTime": "2026-08-11T18:00:00+08:00"},
                    "GeoInfo": {"CountyName": "臺北市", "TownName": "中正區"},
                    "WeatherElement": {
                        "AirTemperature": temperature,
                        "Weather": weather,
                        "WindSpeed": "-99",
                        "Now": {"Precipitation": "2.0"},
                    },
                },
                # **A18: a station outside 臺北市 lives in this fixture on purpose.** The live
                # payload is 876 stations of which 19 are Taipei's, so a fixture with only a Taipei
                # station cannot tell a working filter from no filter at all — it is the same
                # coinciding-value trap H50 records, one layer down.
                {
                    "StationName": "板橋",
                    "StationId": "466880",
                    "ObsTime": {"DateTime": "2026-08-11T18:00:00+08:00"},
                    "GeoInfo": {"CountyName": "新北市", "TownName": "板橋區"},
                    "WeatherElement": {
                        "AirTemperature": "29.0",
                        "Weather": "多雲",
                        "WindSpeed": "-99",
                        "Now": {"Precipitation": "0.0"},
                    },
                },
            ]
        },
    }


class TheStoredScope(unittest.TestCase):
    """A18 — the observation ingest keeps 臺北市 and stores nothing else.

    **Parsing is not filtering, and the split matters.** The parse must still see every station,
    because D42 hashes the whole payload and D102 takes `column_signature` from it; a filter one
    step earlier would make the hash a hash of our policy rather than of their file. So these two
    facts are asserted separately: the parse returns both stations, and the predicate keeps one.

    The store's own use of the predicate needs a database and is asserted in
    `test_ingest_integration.py`; what is pinned here is the rule it applies.
    """

    def test_the_parse_still_sees_every_station(self):
        counties = {row.county for row in cwa.parse_observation(observation_payload())}
        self.assertEqual(counties, {"臺北市", "新北市"})

    def test_the_predicate_keeps_taipei_and_drops_the_rest(self):
        kept = [row for row in cwa.parse_observation(observation_payload())
                if cwa.in_stored_scope(row.county)]
        self.assertTrue(kept)
        self.assertEqual({row.county for row in kept}, {"臺北市"})
        self.assertEqual({row.station_id for row in kept}, {"466920"})

    def test_the_other_spelling_is_kept_too(self):
        """H24: an exact match against one spelling would drop every row the day CWA writes 台北市,
        and it would do it silently — a publication of zero rows and a ledger saying the fetch
        worked. The fold is the same one every stored name goes through."""
        self.assertTrue(cwa.in_stored_scope("台北市"))
        self.assertTrue(cwa.in_stored_scope("臺北市"))

    def test_nothing_else_is_in_scope(self):
        for county in ("新北市", "臺南市", "臺中市", "", None):
            with self.subTest(county=county):
                self.assertFalse(cwa.in_stored_scope(county))

    def test_the_forecast_needs_no_filter_and_has_none(self):
        """`F-D0047-061` IS the Taipei township forecast — the dataset id is the county, and
        `ForecastRow` carries no county field to filter on. Measured 2026-08-28: its latest
        publication held 6,720 rows over twelve township codes, all prefixed 63000."""
        self.assertEqual(cwa.FORECAST_DATASET, "F-D0047-061")
        for row in cwa.parse_forecast(forecast_payload()):
            self.assertTrue(row.township_code.startswith("63000"))
        self.assertFalse(hasattr(cwa.ForecastRow, "county"))


class ForecastParsing(unittest.TestCase):
    def test_geocode_is_the_key(self):
        """D26: by identifier wherever an identifier exists. The payload carries one."""
        for row in cwa.parse_forecast(forecast_payload()):
            self.assertEqual(row.township_code, "63000040")
            self.assertEqual(row.township, "中山區")

    def test_a_location_without_a_geocode_is_skipped(self):
        payload = forecast_payload()
        del payload["records"]["Locations"][0]["Location"][0]["Geocode"]
        with self.assertRaises(cwa.CwaUnavailable):
            cwa.parse_forecast(payload)

    def test_coordinates_are_never_carried(self):
        """The payload states no datum for them, so storing one is H23. A row has no field
        for a coordinate at all, which is stronger than choosing not to fill one."""
        fields = cwa.ForecastRow.__dataclass_fields__
        for forbidden in ("latitude", "longitude", "lat", "lon"):
            self.assertNotIn(forbidden, fields)

    def test_element_and_measure_are_separate(self):
        rows = {(r.element, r.measure): r.value for r in cwa.parse_forecast(forecast_payload())}
        self.assertEqual(rows[("溫度", "Temperature")], "32")
        self.assertEqual(rows[("舒適度指數", "ComfortIndexDescription")], "悶熱")

    def test_one_element_carrying_two_measures_makes_two_rows(self):
        rows = [r for r in cwa.parse_forecast(forecast_payload()) if r.element == "舒適度指數"]
        self.assertEqual(len(rows), 2)

    def test_timestamps_carry_an_offset(self):
        for row in cwa.parse_forecast(forecast_payload()):
            self.assertIsNotNone(row.slot_start.tzinfo, "H17: a stamp without a zone is the hazard")

    def test_empty_payload_is_a_failure_not_an_empty_success(self):
        with self.assertRaises(cwa.CwaUnavailable):
            cwa.parse_forecast({"records": {"Locations": []}})


class ObservationParsing(unittest.TestCase):
    """**These read one named station, not "the station".**

    The fixture carries two since A18 (臺北 466920 and 板橋 466880, so the scope filter has
    something to drop), and `{r.element: r for r in …}` silently keeps whichever station the loop
    saw last. Three tests here asserted 466920's values through exactly that dict and started
    reading 板橋's the moment a second station existed — passing before, failing after, and neither
    was about the station they meant. Selecting by id is what makes them say what they check.
    """

    STATION = "466920"

    def rows(self, payload=None, value_only=False):
        parsed = [row for row in cwa.parse_observation(payload or observation_payload())
                  if row.station_id == self.STATION]
        return {r.element: (r.value if value_only else r) for r in parsed}

    def test_reads_station_and_town(self):
        rows = self.rows()
        self.assertEqual(rows["AirTemperature"].station_id, "466920")
        self.assertEqual(rows["AirTemperature"].town, "中正區")

    def test_sentinel_becomes_null_rather_than_a_number(self):
        """-99 means no reading. Stored as a number it would be averaged into nonsense."""
        rows = self.rows(value_only=True)
        self.assertIsNone(rows["WindSpeed"])

    def test_absent_weather_text_is_recorded_as_absent(self):
        """The `Weather` field's absence is an open measurement question; a row keeps it answerable."""
        rows = self.rows(observation_payload(weather=""), value_only=True)
        self.assertIn("Weather", rows)
        self.assertIsNone(rows["Weather"])

    def test_nested_value_is_kept_rather_than_dropped(self):
        rows = self.rows(value_only=True)
        self.assertEqual(json.loads(rows["Now"]), {"Precipitation": "2.0"})


class ContentDigest(unittest.TestCase):
    def test_envelope_noise_does_not_change_the_hash(self):
        """This is the whole of D42: an hourly fetch of unchanged content must be a no-op."""
        first = cwa.content_digest(cwa.FORECAST_DATASET, forecast_payload(noise="call-1"))
        second = cwa.content_digest(cwa.FORECAST_DATASET, forecast_payload(noise="call-2"))
        self.assertEqual(first, second)

    def test_a_changed_reading_changes_the_hash(self):
        first = cwa.content_digest(cwa.FORECAST_DATASET, forecast_payload(temperature="32"))
        second = cwa.content_digest(cwa.FORECAST_DATASET, forecast_payload(temperature="33"))
        self.assertNotEqual(first, second)

    def test_observation_hash_behaves_the_same_way(self):
        same = cwa.content_digest(cwa.OBSERVATION_DATASET, observation_payload())
        again = cwa.content_digest(cwa.OBSERVATION_DATASET, observation_payload())
        changed = cwa.content_digest(cwa.OBSERVATION_DATASET, observation_payload(temperature="31.0"))
        self.assertEqual(same, again)
        self.assertNotEqual(same, changed)

    def test_hash_is_sha256_shaped(self):
        digest = cwa.content_digest(cwa.OBSERVATION_DATASET, observation_payload())
        self.assertEqual(len(digest), 64)


class TlsPosture(unittest.TestCase):
    """The fix for CWA's chain must not become a fix that trusts anybody."""

    def test_certificates_are_still_verified(self):
        context = cwa.tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_only_the_strict_flag_is_relaxed(self):
        context = cwa.tls_context()
        self.assertFalse(context.verify_flags & ssl.VERIFY_X509_STRICT)


class KeyNeverLeaks(unittest.TestCase):
    def test_a_failed_fetch_does_not_repeat_the_url(self):
        """The URL carries the key as a query parameter, so it may never reach a message."""
        key = "CWA-" + "0123ABCD-4567-89EF-0123-456789ABCDEF"

        def explode(url):
            raise OSError("connection refused to " + url)

        with self.assertRaises(cwa.CwaUnavailable) as caught:
            cwa._fetch_json(cwa.FORECAST_DATASET, key, opener=explode)
        message = str(caught.exception)
        self.assertNotIn(key, message)
        self.assertNotIn("Authorization", message)

    def test_a_rejected_key_is_reported_without_the_key(self):
        with self.assertRaises(cwa.CwaUnavailable) as caught:
            cwa._fetch_json(cwa.FORECAST_DATASET, "some-key", opener=lambda url: b'{"success":"false"}')
        self.assertNotIn("some-key", str(caught.exception))


class FetchAssembly(unittest.TestCase):
    def test_publication_carries_hash_size_and_detection_time(self):
        raw = json.dumps(observation_payload()).encode("utf-8")
        fixed = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)
        publication = cwa.fetch_publication(
            cwa.OBSERVATION_DATASET, "k", now=lambda: fixed, opener=lambda url: raw
        )
        self.assertEqual(publication.detected_at, fixed)
        self.assertEqual(publication.payload_bytes, len(raw))
        self.assertEqual(len(publication.content_sha256), 64)
        self.assertTrue(publication.observation_rows)
        self.assertFalse(publication.forecast_rows)


if __name__ == "__main__":
    unittest.main(verbosity=2)
