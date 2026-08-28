"""The brand source — 臺北市食材登錄平台: fetch, identify, and only then parse.

Ruled 2026-08-14 (D77). The FDA file's only name is the registered one, so a chain shows as
its legal entity — 安心食品服務股份有限公司, not 摩斯漢堡. This platform publishes the pair
the FDA lacks: 公司名稱 beside 品牌名稱. One CSV, ~29k product-level rows, from which this
module keeps the **distinct (company, brand) pairs** — 266 companies on the probe that ruled
it in, 188 of them joining the FDA name column exactly.

**The same shape as item 11, minus the zip.** The download is a bare CSV: no archive entry,
no stamp, so identity is the content hash alone (D35) and there is no disagreement check —
there is no second signal to disagree. The expensive half still sits behind the cheap half:
the parse runs only after the database has said the hash is new.

**Normalisation is `fda.normalise`, imported rather than copied.** The company column exists
to equal `reference_place.name` in an exact-string join; two normalisers would drift and the
join would rot silently, which is H24's shape.

**No credential** (D33's count grows by one source needing none). The endpoint is
data.taipei's public resource download.
"""

from __future__ import annotations

import csv
import hashlib
import io
import ssl
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from . import signature
from .fda import normalise

# data.taipei resource 29869b6f… under dataset 147004 (食材登錄-臺北市食材登錄平台餐飲業者).
URL = (
    "https://data.taipei/api/frontstage/tpeod/dataset/resource.download"
    "?rid=29869b6f-1cd3-4ce8-8c78-eb85aeea8583"
)

# Names the platform, not the slice kept: the hash covers every product row.
SOURCE = "taipei-foodtracer"
SCOPE = "公司名稱→品牌名稱 / 臺北市"

COMPANY_COLUMN = "公司名稱"
BRAND_COLUMN = "品牌名稱"
REQUIRED_COLUMNS = (COMPANY_COLUMN, BRAND_COLUMN)

# **A19: the same file, read wider.** The platform publishes one row per *ingredient* of one
# product, and until 2026-08-28 this module kept the (company, brand) pair and threw the rest away.
# D103's ingredient block was inert *for want of store-published data* that had been arriving daily
# and being discarded.
#
# **These two columns are NOT in `REQUIRED_COLUMNS`, deliberately.** The pair half is what D77 and
# every name on every screen depend on; the ingredient half is an addition. A file that stopped
# carrying 產品名稱 should cost the ingredient join and **not** the whole brand ladder — so their
# absence yields no ingredient rows and no failure, and `column_signature` (D102) records the shape
# either way so the change is visible in the ledger rather than only in a consequence.
PRODUCT_COLUMN = "產品名稱"
MATERIAL_COLUMN = "原料名稱"

REQUEST_TIMEOUT = 300


class FoodtracerUnavailable(RuntimeError):
    """The source did not answer usefully, or answered in a shape we do not know."""


@dataclass(frozen=True)
class Sheet:
    """One fetch, identified but not yet parsed. `raw` is excluded from repr and equality."""

    source: str
    content_sha256: str
    payload_bytes: int
    detected_at: datetime
    raw: bytes = field(default=b"", repr=False, compare=False)
    # D102 / M3: the shape of the file this fetch was, taken at identify time from one header
    # line. Excluded from equality for the same reason `raw` is — two fetches are the same
    # publication when their content hashes agree, and the signature is derived from the content,
    # so including it could only ever restate that or contradict it.
    column_signature: str = field(default="", compare=False)
    # Out of the repr as well as out of equality: `test_foodtracer_ingest` asserts the source's
    # own words never reach a log line through this object, and a header row is the source's
    # words — nine Chinese column names in every log line is also just noise.
    column_names: tuple = field(default=(), repr=False, compare=False)


@dataclass(frozen=True)
class BrandPair:
    """One company and one thing it calls a shop, normalised, raw kept beside it (H24)."""

    company_name: str
    company_name_raw: str
    brand_name: str
    brand_name_raw: str


@dataclass(frozen=True)
class ProductMaterial:
    """One raw material of one product of one brand, as the platform wrote it.

    **The allergen group is NOT here and must not be.** D28's read-time rule: what is stored is what
    the publisher published, and the group comes from `upto.seed.ingredient_terms` when somebody
    asks. Storing the group would freeze today's authored table into yesterday's rows, and the whole
    point of that table is that a term added tomorrow re-answers every row already held.
    """

    company_name: str
    brand_name: str
    product_name: str
    material_name: str
    material_name_raw: str


@dataclass
class PairResult:
    pairs: List[BrandPair] = field(default_factory=list)
    materials: List[ProductMaterial] = field(default_factory=list)
    scanned: int = 0
    companies: int = 0

    def line(self) -> str:
        return "{} rows scanned, {} distinct pairs across {} companies".format(
            self.scanned, len(self.pairs), self.companies
        )


def read_sheet(raw: bytes, detected_at: datetime, source: str = SOURCE) -> Sheet:
    """Identify a fetch without parsing it. The hash is of the served bytes, whole."""
    if not raw:
        raise FoodtracerUnavailable("{}: the download was empty".format(source))
    shape, names = signature.csv_header(raw)
    return Sheet(
        source=source,
        content_sha256=hashlib.sha256(raw).hexdigest(),
        payload_bytes=len(raw),
        detected_at=detected_at,
        raw=raw,
        column_signature=shape,
        column_names=tuple(names),
    )


def tls_context() -> ssl.SSLContext:
    """CWA's relaxation, measured to be needed here too — and only the same one.

    The first containerised run (2026-08-14) failed with `CERTIFICATE_VERIFY_FAILED: Missing
    Subject Key Identifier`: data.taipei's chain has the same defect CWA's has, a CA
    certificate without the extension Python 3.13's `VERIFY_X509_STRICT` requires. Hostname
    checking and trust-store verification stay on; see `cwa.tls_context` for the full
    argument. Item 11 keeps the strict default because its endpoint passes it — this is
    per-endpoint, measured, never a habit.
    """
    context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return context


def _download(target: str) -> bytes:
    request = urllib.request.Request(target, headers={"User-Agent": "upto-ingest/1.0"})
    with urllib.request.urlopen(
        request, timeout=REQUEST_TIMEOUT, context=tls_context()
    ) as response:
        return response.read()


def fetch_sheet(
    now: Optional[Callable[[], datetime]] = None,
    opener: Optional[Callable[[str], bytes]] = None,
    source: str = SOURCE,
    url: str = URL,
) -> Sheet:
    """Fetch the CSV and identify it. Does not parse, and does not touch a database.

    `url` and `source` are parameters because `gradelist` fetches from the same host with
    the same TLS relaxation — the *mechanism* is one thing even though the datasets are two,
    which is the opposite split from `fda_store`/`store` and for the opposite reason.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    download = opener or _download
    try:
        raw = download(url)
    except Exception as failure:  # noqa: BLE001 — any transport failure is one failure here
        raise FoodtracerUnavailable(
            "{}: fetch failed — {}: {}".format(source, type(failure).__name__, failure)
        ) from None
    return read_sheet(raw, clock(), source=source)


def _require_columns(fieldnames) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in (fieldnames or [])]
    if missing:
        raise FoodtracerUnavailable(
            "{}: the CSV is missing {} — found {}".format(SOURCE, missing, list(fieldnames or []))
        )


def parse_pairs(raw: bytes) -> PairResult:
    """Read the CSV down to its distinct pairs. **The expensive call, and the only one.**

    The file is product-level — one row per ingredient of one product of one brand — so a
    pair repeats tens of times. Dedup happens here, keyed on the **normalised** pair: two
    spellings that normalise together are one pair, and keeping both would fail 0013's
    primary key rather than store a subtlety.

    A row with a company and no brand is the platform's own data entry, not a defect —
    counted in `scanned`, kept out of the pairs. There is no unresolved report here because
    there is nothing partial to store: a pair either exists or it does not.
    """
    stream = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
    reader = csv.DictReader(stream)
    _require_columns(reader.fieldnames)
    result = PairResult()
    seen = {}
    # **Deduplicated on the whole four-tuple.** The file repeats a material across a product's
    # variants, and 0035's key would refuse the second copy — better to not offer it than to rely
    # on a conflict clause to hide a shape we could have seen here.
    materials = {}
    for row in reader:
        result.scanned += 1
        company_raw = (row.get(COMPANY_COLUMN) or "").strip()
        brand_raw = (row.get(BRAND_COLUMN) or "").strip()
        company = normalise(company_raw)
        brand = normalise(brand_raw)
        if not company or not brand:
            continue
        # A19: the ingredient half, gathered beside the pair from the same row. A row with no
        # product or no material is skipped in silence — the platform leaves both blank for a
        # company that has registered nothing yet, and that is data entry rather than a defect.
        product_raw = (row.get(PRODUCT_COLUMN) or "").strip()
        material_raw = (row.get(MATERIAL_COLUMN) or "").strip()
        product = normalise(product_raw)
        material = normalise(material_raw)
        if product and material:
            key = (company, brand, product, material)
            if key not in materials:
                materials[key] = ProductMaterial(
                    company_name=company,
                    brand_name=brand,
                    product_name=product,
                    material_name=material,
                    material_name_raw=material_raw,
                )
        if (company, brand) not in seen:
            seen[(company, brand)] = BrandPair(
                company_name=company,
                company_name_raw=company_raw,
                brand_name=brand,
                brand_name_raw=brand_raw,
            )
    result.pairs = list(seen.values())
    result.materials = list(materials.values())
    result.companies = len({pair.company_name for pair in result.pairs})
    if not result.pairs:
        raise FoodtracerUnavailable(
            "{}: the CSV parsed to no pairs — {} rows were read".format(SOURCE, result.scanned)
        )
    return result
