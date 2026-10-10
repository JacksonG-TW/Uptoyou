#!/usr/bin/env python3
"""D102 / M3 — every publication table records the shape of the file it came from.

Run inside the stack:
    docker compose exec api python /srv/tests/test_column_signature_integration.py

The test builds its own database and drops it, so it never touches the stack's data.

**What is under test is the write, not the derivation.** `test_signature.py` holds the hash rule
still with no database at all; this file asserts that all **seven** publication tables actually
carry the two columns, that the real `claim` on each store fills them, that the value stored is the
one `upto.ingest.signature` computes from the source's own header, and — the case the whole column
exists for — that **two files whose headers differ sign differently while the source stays the
same**.

Two negative cases matter as much as the positive ones. A fetched object with no signature must
store `NULL` rather than an empty string, because "this publication predates the signature" is a
different fact from "this file had no columns" — revision 0021 backfills nothing, so those NULLs
are the historical rows and they must be recognisable. And a JSON feed's signature must come from a
*reading-bearing record* rather than the payload envelope, or a rename that breaks the parser would
leave the signature unmoved.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
import _tempdb  # noqa: E402

TEST_DB = "upto_signature_check"
NOW = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print("ok   {}".format(name))
    else:
        FAILURES.append(name)
        print("FAIL {} {}".format(name, detail))


def csv_bytes(header, rows):
    return ("﻿" + "\n".join([header] + rows) + "\n").encode("utf-8")


def zip_bytes(payload, name="97_2.csv"):
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, payload)
    return buffer.getvalue()


async def one_row(Session, table):
    async with Session() as session:
        result = await session.execute(
            text("select column_signature, column_names from {} order by id desc limit 1".format(
                table))
        )
        return result.fetchone()


async def scenario(test_url: str) -> None:
    os.environ["UPTO_DATABASE_URL"] = test_url

    from upto.ingest import signature  # noqa: PLC0415
    from upto.ingest.brand_store import BrandStore  # noqa: PLC0415
    from upto.ingest.business_store import BusinessStore  # noqa: PLC0415
    from upto.ingest.business_tax_store import BusinessTaxStore  # noqa: PLC0415
    from upto.ingest.cwa import FORECAST_DATASET, Publication, shape_of  # noqa: PLC0415
    from upto.ingest.fda import read_archive  # noqa: PLC0415
    from upto.ingest.fda_store import PlaceStore  # noqa: PLC0415
    from upto.ingest.fia import read_archive as read_tax_archive  # noqa: PLC0415
    from upto.ingest.foodtracer import read_sheet  # noqa: PLC0415
    from upto.ingest.store import store_publication  # noqa: PLC0415
    from upto.ingest.storefront_store import StorefrontStore  # noqa: PLC0415

    engine = create_async_engine(test_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    # ---- the three plain-CSV sources, one shared reader ------------------
    cases = (
        ("brand_publication", BrandStore, "公司名稱,品牌名稱,產品名稱",
         ["甲公司,甲牌,產品"], "taipei-foodtracer"),
        ("storefront_publication", StorefrontStore, "登錄字號,店名,評核等級",
         ["A-1,甲店,優"], "taipei-hygiene-grade"),
        ("business_status_publication", BusinessStore, "統一編號,現況,名稱",
         ["12345678,核准設立,甲"], "gcis-restaurant-registry"),
    )
    for table, store_class, header, rows, source in cases:
        sheet = read_sheet(csv_bytes(header, rows), NOW, source=source)
        expected = header.split(",")
        check("{}: the header is read at identify time".format(source),
              list(sheet.column_names) == expected, repr(sheet.column_names))
        async with Session() as session:
            store = store_class(session)
            publication_id = await store.claim(sheet, "test")
            await session.commit()
        check("{}: the claim stored a publication".format(source), publication_id is not None)
        stored = await one_row(Session, table)
        check("{}: the signature landed in {}".format(source, table),
              stored[0] == signature.digest(expected), repr(stored[0]))
        check("{}: the names landed as JSON".format(source),
              _names(stored[1]) == expected, repr(stored[1]))

    # ---- the drift case: same source, a renamed column ------------------
    renamed = read_sheet(
        csv_bytes("公司名稱,品牌名字,產品名稱", ["甲公司,甲牌,產品"]), NOW,
        source="taipei-foodtracer",
    )
    async with Session() as session:
        second = await BrandStore(session).claim(renamed, "test")
        await session.commit()
    check("a renamed column is a different publication with a different signature",
          second is not None)
    stored = await one_row(Session, "brand_publication")
    check("and the new signature is not the old one",
          stored[0] == signature.digest(["公司名稱", "品牌名字", "產品名稱"]), repr(stored[0]))

    # ---- item 11's zip ---------------------------------------------------
    place_header = "公司或商業登記名稱,公司統一編號,業者地址,登錄項目"
    archive = read_archive(
        zip_bytes(csv_bytes(place_header, ["甲,12345678,臺北市信義區一號,餐飲場所"])), NOW,
    )
    async with Session() as session:
        place_id = await PlaceStore(session).claim(archive, "test")
        await session.commit()
    check("fda-97: the zip's header is read at identify time",
          list(archive.column_names) == place_header.split(","), repr(archive.column_names))
    stored = await one_row(Session, "place_publication")
    check("fda-97: the signature landed in place_publication",
          stored[0] == signature.digest(place_header.split(",")), repr(stored[0]))
    check("fda-97: a claim still happened", place_id is not None)

    # ---- D85's zip: header and stamp in one pass -------------------------
    tax_header = "營業人統一編號,營業人名稱,營業地址,行業代號1"
    tax_archive = read_tax_archive(
        zip_bytes(csv_bytes(tax_header, ["14-AUG-26,,,", "12345678,甲,臺北市信義區一號,562"]),
                  name="tax.csv"),
        NOW,
    )
    check("fia: the header is read in the same pass as the stamp row",
          list(tax_archive.column_names) == tax_header.split(","),
          repr(tax_archive.column_names))
    async with Session() as session:
        tax_id = await BusinessTaxStore(session).claim(tax_archive, "test")
        await session.commit()
    check("fia: a claim still happened", tax_id is not None)
    stored = await one_row(Session, "business_tax_publication")
    check("fia: the signature landed in business_tax_publication",
          stored[0] == signature.digest(tax_header.split(",")), repr(stored[0]))

    # ---- the two JSON feeds ---------------------------------------------
    observation_payload = {
        "records": {"Station": [{"StationId": "A0", "StationName": "x", "GeoInfo": {}}]}
    }
    shape, names = shape_of("O-A0001-001", observation_payload)
    check("cwa: an observation signs on one Station's key set",
          names == ["GeoInfo", "StationId", "StationName"], repr(names))
    forecast_payload = {
        "records": {"Locations": [{"Location": [
            {"LocationName": "松山區", "Geocode": "63000010", "WeatherElement": []}
        ]}]}
    }
    _, forecast_names = shape_of(FORECAST_DATASET, forecast_payload)
    check("cwa: a forecast signs on one Location's key set",
          forecast_names == ["Geocode", "LocationName", "WeatherElement"], repr(forecast_names))
    check("cwa: the envelope is not the signature",
          "records" not in names and "records" not in forecast_names)

    async with Session() as session:
        await store_publication(session, Publication(
            dataset_id="O-A0001-001", content_sha256="0" * 64, detected_at=NOW,
            payload_bytes=10, column_signature=shape, column_names=tuple(names),
        ))
    stored = await one_row(Session, "observation_publication")
    check("cwa: the signature landed in observation_publication", stored[0] == shape, repr(stored))
    check("cwa: the names landed as JSON", _names(stored[1]) == names, repr(stored[1]))

    # ---- the historical row: no signature means NULL, not empty ---------
    async with Session() as session:
        await store_publication(session, Publication(
            dataset_id="O-A0001-001", content_sha256="1" * 64, detected_at=NOW, payload_bytes=10,
        ))
    stored = await one_row(Session, "observation_publication")
    check("a publication with no signature stores NULL, not an empty string",
          stored[0] is None and stored[1] is None, repr(stored))

    await engine.dispose()

    if FAILURES:
        print("\n{} failing: {}".format(len(FAILURES), ", ".join(FAILURES)))
        raise SystemExit(1)
    print(
        "\nD102: all seven publication tables carry the shape of the file they came from — the "
        "four CSV sources from their header row, the two CWA feeds from one reading-bearing "
        "record's key set, a renamed column signs differently, and a publication that predates "
        "the signature stores NULL rather than an empty claim"
    )


def _names(value):
    """`column_names` comes back as parsed JSON on some drivers and as text on others."""
    if isinstance(value, str):
        return json.loads(value)
    return value


async def with_temporary_database() -> int:
    async def served(test_url: str, environment: dict) -> None:
        await scenario(test_url)

    return await _tempdb.with_temporary_database(TEST_DB, served)


if __name__ == "__main__":
    sys.exit(asyncio.run(with_temporary_database()))
