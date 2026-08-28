"""Item 10 — the CWA weather ingest.

Two datasets, both fetched hourly on the same beat (D42):

  * `F-D0047-061` — township-level hourly forecast for Taipei (D19).
  * `O-A0001-001` — station observations (D19).

**A publication is identified by the hash of its content** (D35, extended to the forecast by
D42), because the forecast carries no publication timestamp and a six-hourly signal with
fifty minutes of jitter has no clock to align to. The consequence this module has to get
right is that **about twenty of twenty-four daily forecast runs publish nothing, and those
must be silent successes** — not errors, not warnings, and not twenty-four rows for four
facts.

**This module does not know where the API key lives.** It is handed one. D33 rules the key an
Airflow Connection, and until the DAG exists a caller may read it from anywhere it likes;
neither arrangement is visible here. That is also what keeps the key out of any signature
that gets logged.

**`detected_at` is a detection time, not a publication time.** The forecast does not tell us
when it was published, so nothing downstream — item 14's lineage label especially — may
present this as one.
"""

from __future__ import annotations

import hashlib
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable

from . import signature

BASE = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/"
FORECAST_DATASET = "F-D0047-061"
OBSERVATION_DATASET = "O-A0001-001"

# CWA reports local time with an explicit offset. Parsing keeps the offset rather than
# converting, because H17 is about never holding a timestamp whose zone is unknown — and
# `timestamptz` stores an instant, so the offset is preserved semantically either way.
TAIPEI = timezone(timedelta(hours=8))

REQUEST_TIMEOUT = 90

# **A18, owner-ruled 2026-08-28 (「匯入時只留臺北市，之前太異想天開，一次就做全台」): the observation
# ingest keeps 臺北市's stations and stores nothing else.** Measured on the live database that day:
# `O-A0001-001` publishes 876 stations / 7,884 rows an hour, of which 臺北市 is **19 stations / 171
# rows (2.2%)**, and the product never read the rest — D26 resolves a township to a Taipei station
# and D57 reads the latest publication per hour.
#
# **The filter belongs at store time, never at fetch or parse.** D42's change detection hashes the
# whole payload and D102 takes `column_signature` from the whole file, so both must keep seeing
# everything the source published; what narrows is only what is kept. A filter one step earlier
# would make the hash a hash of our policy instead of of their file, and the day the policy changes
# every publication would look new.
#
# The forecast dataset needs no filter and gets none: `F-D0047-061` **is** the Taipei township
# forecast, twelve townships in 臺北市's own `63000` code space, so the dataset id is the county.
STORED_COUNTY = "臺北市"


def in_stored_scope(county: str | None) -> bool:
    """Is this station's county the one A18 keeps?

    **Folded before comparing, and that is not decoration (H24).** The county arrives as free text
    in `GeoInfo.CountyName`; every value the live payload carries today is spelled 臺, but an exact
    match against one spelling is a filter that drops **every row** the day the source writes 台北市
    — and it would drop them silently, leaving a publication of zero rows and a ledger that says the
    fetch worked. `fda.normalise` already folds administrative 台 to 臺 and is the fold every stored
    name goes through, so the filter uses it rather than carrying a second list of spellings.
    """
    from .fda import normalise  # noqa: PLC0415  (import here to keep the module header lean)

    return normalise(county) == STORED_COUNTY


class CwaUnavailable(RuntimeError):
    """The source did not answer usefully. A run that hits this failed; it did not no-op."""


@dataclass(frozen=True)
class Reading:
    element: str
    value: str | None
    unit: str | None = None


@dataclass(frozen=True)
class ForecastRow:
    # D26 keys the forecast by geocode: the payload carries `Geocode` beside `LocationName`,
    # in the same 內政部 code space the seeded township_station uses. The name is kept because
    # it is what CWA calls the township and what a lineage answer quotes, not because it is
    # the key.
    township_code: str
    township: str
    element: str
    measure: str
    slot_start: datetime
    slot_end: datetime | None
    value: str


@dataclass(frozen=True)
class ObservationRow:
    station_id: str
    station_name: str
    county: str | None
    town: str | None
    # D26 matches a township to its station by *code*, never by name — a code cannot be
    # spelled 台 on one side and 臺 on the other, which is H24's shape.
    town_code: str | None
    observed_at: datetime
    element: str
    value: str | None


@dataclass
class Publication:
    """One fetch, reduced to what identifies it and what it said."""

    dataset_id: str
    content_sha256: str
    detected_at: datetime
    payload_bytes: int
    forecast_rows: list[ForecastRow] = field(default_factory=list)
    observation_rows: list[ObservationRow] = field(default_factory=list)
    # D102 / M3: the shape of the payload. These feeds are JSON and have no header row, so the
    # signature is the **sorted key set of one reading-bearing record** — the object a parser
    # actually reaches into. See `shape_of`.
    column_signature: str = ""
    column_names: tuple = field(default=(), repr=False)


def tls_context() -> ssl.SSLContext:
    """Full verification, with one RFC 5280 strictness check disabled — and only that one.

    Python 3.13 turned on `VERIFY_X509_STRICT` in the default context. CWA's open-data
    endpoint presents a chain whose CA certificate has no Subject Key Identifier extension,
    which strict mode rejects with `CERTIFICATE_VERIFY_FAILED: Missing Subject Key
    Identifier`. The host's Python 3.9 has no such check, which is why the measurement
    probes never hit this and the containerised ingest did on its first run.

    **What stays on: `check_hostname` and `CERT_REQUIRED`.** The certificate is still
    verified against the system trust store and still has to match the hostname. What is
    given up is an extension-presence rule about the issuer, on an endpoint we do not
    control and cannot ask to reissue. Turning verification off entirely would be the easy
    version of this fix and is the wrong one — it would make the ingest trust any server
    that answers on that name.
    """
    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _reason(failure: Exception) -> str:
    """Describe a failure without ever repeating the URL, which carries the key."""
    if isinstance(failure, urllib.error.HTTPError):
        return "HTTP {}".format(failure.code)
    inner = getattr(failure, "reason", None)
    return "{}: {}".format(type(failure).__name__, inner) if inner else type(failure).__name__


def _fetch_json(dataset_id: str, api_key: str, opener: Callable[[str], bytes] | None = None) -> tuple[dict, bytes]:
    params = urllib.parse.urlencode({"Authorization": api_key, "format": "JSON"})
    url = BASE + dataset_id + "?" + params
    if opener is None:

        def opener(target: str) -> bytes:
            request = urllib.request.Request(target, headers={"User-Agent": "upto-ingest/1.0"})
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT, context=tls_context()) as response:
                return response.read()

    try:
        raw = opener(url)
    except Exception as failure:  # noqa: BLE001 — the URL carries the key; never re-raise it
        raise CwaUnavailable("{} fetch failed — {}".format(dataset_id, _reason(failure))) from None
    if not raw:
        raise CwaUnavailable("{} returned an empty body".format(dataset_id))
    try:
        payload = json.loads(raw)
    except ValueError:
        raise CwaUnavailable("{} returned a body that is not JSON".format(dataset_id)) from None
    if not payload.get("success") in (True, "true"):
        raise CwaUnavailable("{} reported success={!r}".format(dataset_id, payload.get("success")))
    return payload, raw


def content_digest(dataset_id: str, payload: dict) -> str:
    """Hash what the publication *says*, not the envelope it arrived in.

    The response carries fields that differ on every call, so hashing the raw bytes would
    make every run look like a new publication and defeat the whole design. This hashes the
    normalised readings, which is the thing D35 means by a publication's identity.

    **Changing what goes into this function invalidates every hash already stored.** The next
    run then reads as a new publication and re-inserts content that is already held, which is
    exactly the duplicate D42 keys on the hash to avoid. It happened once during item 10's
    first build — adding `measure` to the tuple changed every forecast hash — and it was free
    only because nothing had accumulated yet. **Treat this function as schema:** a change to
    it needs a migration and a stated plan for the rows written under the old definition.
    """
    if dataset_id == FORECAST_DATASET:
        body = [
            (row.township, row.element, row.measure, row.slot_start.isoformat(), row.value)
            for row in sorted(
                parse_forecast(payload),
                key=lambda r: (r.township, r.element, r.measure, r.slot_start),
            )
        ]
    else:
        body = [
            (row.station_id, row.element, row.observed_at.isoformat(), row.value)
            for row in sorted(
                parse_observation(payload),
                key=lambda r: (r.station_id, r.element, r.observed_at),
            )
        ]
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_stamp(text: str | None) -> datetime | None:
    if not text:
        return None
    cleaned = text.strip().replace(" ", "T")
    try:
        stamp = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    # A stamp without an offset is the failure H17 is about. CWA sends local time; where it
    # omits the offset, attach Taipei's explicitly rather than letting it default to naive.
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=TAIPEI)


def parse_forecast(payload: dict) -> list[ForecastRow]:
    records = payload.get("records") or {}
    locations_wrapper = records.get("Locations") or []
    if not locations_wrapper:
        raise CwaUnavailable("forecast payload carries no Locations")
    rows: list[ForecastRow] = []
    for location in locations_wrapper[0].get("Location") or []:
        township = location.get("LocationName")
        geocode = location.get("Geocode")
        # `Latitude` and `Longitude` sit here too and are deliberately never read. The payload
        # states no datum for them — no CoordinateName, no EPSG — and an unlabelled coordinate
        # that nothing needs is what H23 is about. D26 declines to store them.
        for element in location.get("WeatherElement") or []:
            name = element.get("ElementName")
            for slot in element.get("Time") or []:
                start = _parse_stamp(slot.get("StartTime") or slot.get("DataTime"))
                if start is None or not township or not name or not geocode:
                    continue
                end = _parse_stamp(slot.get("EndTime"))
                for value, measure in _element_values(slot.get("ElementValue")):
                    rows.append(
                        ForecastRow(
                            township_code=str(geocode),
                            township=township,
                            element=name,
                            measure=measure or name,
                            slot_start=start,
                            slot_end=end,
                            value=value,
                        )
                    )
    if not rows:
        raise CwaUnavailable("forecast payload parsed to no readings")
    return rows


def _element_values(element_value) -> Iterable[tuple[str, str | None]]:
    """CWA nests one or more named measures under ElementValue, shaped inconsistently."""
    if element_value is None:
        return []
    if isinstance(element_value, dict):
        element_value = [element_value]
    out: list[tuple[str, str | None]] = []
    for entry in element_value:
        if not isinstance(entry, dict):
            out.append((str(entry), None))
            continue
        for measure, value in entry.items():
            out.append((str(value), measure))
    return out


def parse_observation(payload: dict) -> list[ObservationRow]:
    records = payload.get("records") or {}
    stations = records.get("Station") or []
    if not stations:
        raise CwaUnavailable("observation payload carries no Station")
    rows: list[ObservationRow] = []
    for station in stations:
        geo = station.get("GeoInfo") or {}
        observed_at = _parse_stamp((station.get("ObsTime") or {}).get("DateTime"))
        station_id = station.get("StationId")
        if observed_at is None or not station_id:
            continue
        for element, value in (station.get("WeatherElement") or {}).items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True)
            # CWA uses -99 and -990 for "no reading". Storing the sentinel would let it be
            # averaged; storing NULL keeps the absence visible, which the open question
            # about the `Weather` field's absence still needs.
            text = None if value in (None, "", "-99", "-990", "-99.0", "-990.0") else str(value)
            rows.append(
                ObservationRow(
                    station_id=str(station_id),
                    station_name=station.get("StationName") or "",
                    county=geo.get("CountyName"),
                    town=geo.get("TownName"),
                    town_code=geo.get("TownCode"),
                    observed_at=observed_at,
                    element=str(element),
                    value=text,
                )
            )
    if not rows:
        raise CwaUnavailable("observation payload parsed to no readings")
    return rows


def shape_of(dataset_id: str, payload: dict) -> tuple[str, list]:
    """M3's signature for a JSON feed: the key set of the first record a parser reaches into.

    **Which object counts as "the record" is the decision here.** A payload's top level is
    envelope — `success`, `result`, `records` — and its shape barely moves; what a parser depends
    on is the object it reads fields out of. For the observation feed that is one `Station`; for
    the forecast it is one `Location` under the first `Locations` wrapper. So a renamed or vanished
    `StationName` or `Geocode` moves the signature, and a change in the envelope does not.

    Nothing raises here. A payload shaped so unexpectedly that the record cannot be found signs as
    empty, and the parse — which is where an unreadable payload belongs — fails on its own terms a
    few lines later.
    """
    records = (payload or {}).get("records") or {}
    if dataset_id == FORECAST_DATASET:
        wrapper = records.get("Locations") or []
        locations = (wrapper[0].get("Location") or []) if wrapper else []
        record = locations[0] if locations else None
    else:
        stations = records.get("Station") or []
        record = stations[0] if stations else None
    return signature.from_json_keys(record if isinstance(record, dict) else None)


def fetch_publication(
    dataset_id: str,
    api_key: str,
    now: Callable[[], datetime] | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> Publication:
    """Fetch one dataset and reduce it to a Publication. Does not touch a database."""
    payload, raw = _fetch_json(dataset_id, api_key, opener=opener)
    clock = now or (lambda: datetime.now(timezone.utc))
    shape, names = shape_of(dataset_id, payload)
    publication = Publication(
        dataset_id=dataset_id,
        content_sha256=content_digest(dataset_id, payload),
        detected_at=clock(),
        payload_bytes=len(raw),
        column_signature=shape,
        column_names=tuple(names),
    )
    if dataset_id == FORECAST_DATASET:
        publication.forecast_rows = parse_forecast(payload)
    else:
        publication.observation_rows = parse_observation(payload)
    return publication
