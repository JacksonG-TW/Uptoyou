"""The tax-registry source — 財政部 全國營業(稅籍)登記資料集: fetch, identify, and only then parse.

Ruled 2026-08-14 (D85). This is the sixth reference source and the widest one: a 66 MB zip
holding a single ~320 MB CSV of **1,711,012 rows, nationwide, every registered business**
(measured 2026-08-14 on the served file). What it publishes that no earlier source has is the
營業人名稱 the tax office holds, beside the 行業代號 the business registered itself under —
a category the shop chose rather than one a model guessed (D63/D64).

**Only the rows our reference list already knows are stored** (ruled 2026-08-14). The join is
`reference_place.business_no` in the *latest* place publication — about 19.2k distinct 統編,
matching about 14.5k rows here. The other ~1.69M rows are never written, and that is a storage
ruling rather than an optimisation: this project's question is "what can this circle eat", and a
tax row for a 南投縣 hardware store answers nothing while costing a table two hundred times the
size of the one it decorates.

**Two version signals, exactly as item 11 has them** (D34, D35). The identity is the sha256 of
the *compressed* bytes; the file's own stamp is the second signal, and here it is not the zip
entry's mtime but **row 2 of the CSV** — a lone `14-AUG-26` in the first cell with every other
cell empty, which is the publisher's own statement of what day the extract was cut. The two are
compared on every run and a disagreement is exit 2, because a stamp can move while the data
stands still and the data can move while the stamp stands still.

**The expensive half sits behind the cheap half.** `read_archive` hashes the compressed bytes and
decompresses only far enough to read the two header lines — a few kilobytes; `parse_rows` is the
only thing here that touches the 320 MB, and the caller must not reach it until the database has
said the hash is new.

**No credential.** The file is an open download, like items 11, D77, D78 and D81. The TLS
posture is not the default one, and `tls_context` states what was measured to make it so.

Measured on the served file, 2026-08-14, and each of these is a shape this module relies on:

  * 1,711,012 data rows; **統編 is unique** — 0 duplicates — so the row is the unit and the
    number is the key, unlike D81's roster where the tuple had to be.
  * every 統編 is exactly 8 digits and numeric; none is short, so no leading zero has been
    eaten by a numeric export on the way out.
  * no row carries an empty 行業代號 while carrying a later one, so the four code/name pairs
    are stored **positionally** — the first pair is the business's own primary 行業, and
    compacting the empties would quietly promote a secondary one.
"""

from __future__ import annotations

import csv
import hashlib
import io
import ssl
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Iterable, List, Optional, Set, Tuple

from . import signature

URL = "https://eip.fia.gov.tw/data/BGMOPEN1.zip"

# Names the file, not the slice kept from it — the hash covers all 1.7M rows nationwide, so a
# source string naming the join would describe the rows and misdescribe the thing identified.
# What the rows cover is recorded separately, as SCOPE.
SOURCE = "fia-business-tax"
SCOPE = "營業(稅籍)登記 / 參照名單上的統編"

ADDRESS_COLUMN = "營業地址"
BUSINESS_NO_COLUMN = "統一編號"
NAME_COLUMN = "營業人名稱"
# The file names the primary pair 行業代號/名稱 and then numbers the other three. Read from the
# header rather than by position, and paired here so the store cannot drift out of step.
INDUSTRY_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("行業代號", "名稱"),
    ("行業代號1", "名稱1"),
    ("行業代號2", "名稱2"),
    ("行業代號3", "名稱3"),
)
REQUIRED_COLUMNS = (
    ADDRESS_COLUMN,
    BUSINESS_NO_COLUMN,
    NAME_COLUMN,
) + tuple(column for pair in INDUSTRY_COLUMNS for column in pair)

# 66 MB over a government link. Item 11's 17 MB is given 300 seconds; this is four times the
# bytes and the same order of patience.
REQUEST_TIMEOUT = 900

# The stamp row's month is an English abbreviation in capitals — `14-AUG-26`. Parsed from a
# table rather than with `%b`, because `%b` reads the process locale and a container whose
# locale is not C would fail to parse a date the file states plainly.
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
# The stamp carries two year digits. The dataset is published monthly and has no pre-2000
# history to confuse this with.
CENTURY = 2000


class FiaUnavailable(RuntimeError):
    """The source did not answer usefully, or answered in a shape we do not know.

    A run that hits this **failed**; it did not no-op. The two must stay distinguishable, or a
    source that stopped answering looks exactly like a source with nothing new to say.
    """


@dataclass(frozen=True)
class Industry:
    """One 行業代號 and its name, as the business registered it. Either may be absent."""

    code: Optional[str]
    name: Optional[str]


@dataclass(frozen=True)
class TaxRow:
    """One registered business, kept because our reference list already knows its 統編.

    `address` is the **registered** address — where the business is registered for tax, not
    where the shop stands. **13.7% of the matched rows sit outside 臺北市 entirely** — 3,130 of
    them, measured 2026-08-17 over the join itself (`probes/m5-cross-source.md`). This column must
    never be read as a storefront location; the address a diner would walk to is
    `reference_place.address`.

    **The figure here read 6.2% until 2026-09-11 and that was an understatement**, taken on
    2026-08-14 before the cross-source measurement existed. It is corrected rather than annotated
    because this number is the whole argument for the rule above it: a warning that halves the size
    of the problem it is warning about is one somebody talks themselves past.
    """

    business_no: str
    tax_name: str
    address: str
    # Exactly four, positional, in the file's own order. `industries[0]` is the primary.
    industries: Tuple[Industry, ...]


@dataclass(frozen=True)
class TaxArchive:
    """One fetch, identified but not yet parsed.

    `raw` is the compressed bytes, kept only so the caller can parse them *if* the hash turns
    out to be new. Excluded from the repr and from equality: a 66 MB blob in a log line is
    worse than no log line.
    """

    source: str
    content_sha256: str
    file_stamp: Optional[date]
    entry_name: str
    entry_bytes: int
    payload_bytes: int
    detected_at: datetime
    raw: bytes = field(default=b"", repr=False, compare=False)
    # D102 / M3: the CSV's header, read in the same pass that reads the stamp row below it.
    # Out of equality like `raw`: the content hash decides what is one publication.
    column_signature: str = field(default="", compare=False)
    column_names: tuple = field(default=(), repr=False, compare=False)

    def stamp_label(self) -> str:
        """What a verdict shows. A file whose stamp row is unreadable says so, never a date."""
        if self.file_stamp is None:
            return "no file stamp"
        return self.file_stamp.isoformat()


@dataclass
class TaxResult:
    rows: List[TaxRow] = field(default_factory=list)
    scanned: int = 0
    wanted: int = 0
    duplicates: int = 0

    def line(self) -> str:
        return "{} rows scanned, {} matched against {} reference numbers{}".format(
            self.scanned,
            len(self.rows),
            self.wanted,
            "" if not self.duplicates else ", {} repeated 統編 ignored".format(self.duplicates),
        )


def parse_stamp(cell: str) -> Optional[date]:
    """Read the file's own version stamp out of row 2's first cell — `14-AUG-26`.

    An unreadable stamp is `None` rather than a refusal, which is the same call item 11 makes
    for a zip epoch: a missing stamp is a missing label, and the run still has a content hash
    to identify the publication by. What it costs is the disagreement check for that run, and
    the verdict says `no file stamp` so the loss is visible rather than inferred.
    """
    parts = (cell or "").strip().split("-")
    if len(parts) != 3:
        return None
    day, month, year = parts
    if not day.isdigit() or not year.isdigit():
        return None
    number = MONTHS.get(month.strip().upper())
    if number is None:
        return None
    try:
        return date(CENTURY + int(year), number, int(day))
    except ValueError:
        # 31-FEB-26 and friends. A date the calendar refuses is not a date.
        return None


def tls_context() -> ssl.SSLContext:
    """CWA's relaxation, measured to be needed here too — and only the same one.

    Measured from inside the api container on 2026-08-14, both ways: with Python 3.13's default
    `VERIFY_X509_STRICT` the handshake fails `CERTIFICATE_VERIFY_FAILED: Missing Subject Key
    Identifier`, and with that one flag cleared it completes over TLS 1.3. This is the third
    government chain in this repository carrying a CA certificate without the extension — CWA
    and data.taipei are the other two — and item 11's endpoint remains the one that passes the
    strict default, which is why this stays per-endpoint and measured rather than a habit.

    **Hostname checking and trust-store verification stay on**; `check_hostname` is True and
    `verify_mode` is CERT_REQUIRED after the flag is cleared, both asserted in the unit tests.
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


def _single_entry(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    entries = archive.infolist()
    if len(entries) != 1:
        # The served archive has carried exactly one entry, `BGMOPEN1.csv`. A second one means
        # the packaging changed, and guessing which entry is the data is how a wrong table gets
        # written with nothing to notice it.
        raise FiaUnavailable(
            "{}: the archive carries {} entries, not one — {}".format(
                SOURCE, len(entries), [entry.filename for entry in entries]
            )
        )
    return entries[0]


def _open_csv(archive: zipfile.ZipFile, entry: zipfile.ZipInfo):
    """The CSV as text, streamed. `utf-8-sig`, because the file carries a leading BOM and `csv`
    does not raise on one — it renames the first column instead, so 營業地址 becomes a key
    nothing looks up and the failure reads as a typo (H24)."""
    return io.TextIOWrapper(archive.open(entry.filename), encoding="utf-8-sig", newline="")


def _read_head(raw: bytes, entry_name: str) -> tuple[Optional[date], str, list]:
    """Decompress the first few kilobytes only, and read rows 1 and 2 — header, then stamp.

    A zip entry is a stream, so taking two lines costs two lines. This is what keeps the stamp
    a *cheap* signal: it is read on every run, including the twenty-nine in thirty that will
    turn out to have nothing to store.

    **Renamed from `_read_stamp` and widened by D102**, because the header row was already being
    read here and thrown away — row 1 is the header and row 2 is the stamp, so M3's column
    signature was one line already paid for. Reading it in a second pass would have decompressed
    the same kilobytes twice to learn something this function had in its hand.
    """
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        with _open_csv(archive, archive.getinfo(entry_name)) as stream:
            reader = csv.reader(stream)
            try:
                header = next(reader)
            except StopIteration:
                return None, "", []
            shape, names = signature.from_csv_header(header)
            try:
                stamp_row = next(reader)
            except StopIteration:
                return None, shape, names
    if not stamp_row:
        return None, shape, names
    return parse_stamp(stamp_row[0]), shape, names


def read_archive(raw: bytes, detected_at: datetime, source: str = SOURCE) -> TaxArchive:
    """Identify a fetch without parsing it.

    The hash is of the compressed bytes, which is what D35 chose and what its cost bullet
    admits: a recompression of identical data would mint a false publication, and the stamp is
    right in exactly that case, which is the argument for storing both.
    """
    if not raw:
        raise FiaUnavailable("{}: the download was empty".format(source))
    digest = hashlib.sha256(raw).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entry = _single_entry(archive)
            name, size = entry.filename, entry.file_size
        stamp, shape, names = _read_head(raw, name)
    except zipfile.BadZipFile:
        raise FiaUnavailable("{}: the download is not a zip archive".format(source)) from None
    except UnicodeDecodeError as failure:
        raise FiaUnavailable(
            "{}: the archived file does not decode as UTF-8 — {}".format(source, failure)
        ) from None
    return TaxArchive(
        source=source,
        content_sha256=digest,
        file_stamp=stamp,
        entry_name=name,
        entry_bytes=size,
        payload_bytes=len(raw),
        detected_at=detected_at,
        raw=raw,
        column_signature=shape,
        column_names=tuple(names),
    )


def fetch_archive(
    now: Optional[Callable[[], datetime]] = None,
    opener: Optional[Callable[[str], bytes]] = None,
    source: str = SOURCE,
) -> TaxArchive:
    """Fetch the archive and identify it. Does not parse, and does not touch a database."""
    clock = now or (lambda: datetime.now(timezone.utc))
    download = opener or _download
    try:
        raw = download(URL)
    except Exception as failure:  # noqa: BLE001 — any transport failure is one failure here
        # No credential is in play, so unlike item 10 nothing has to be hidden. The message
        # names the source rather than the URL, which adds nothing a reader of this log lacks.
        raise FiaUnavailable(
            "{}: fetch failed — {}: {}".format(source, type(failure).__name__, failure)
        ) from None
    return read_archive(raw, clock(), source=source)


def _require_columns(fieldnames) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in (fieldnames or [])]
    if missing:
        raise FiaUnavailable(
            "{}: the CSV is missing {} — found {}".format(SOURCE, missing, list(fieldnames or []))
        )


def is_stamp_row(row) -> bool:
    """Row 2: a date in the address cell and nothing anywhere else.

    Recognised by its shape rather than by its position, and then only accepted as the first
    record — a real business row always carries a 統編, so a row with none and no name is the
    publisher's stamp line rather than data with holes in it.
    """
    if (row.get(BUSINESS_NO_COLUMN) or "").strip():
        return False
    if (row.get(NAME_COLUMN) or "").strip():
        return False
    return parse_stamp(row.get(ADDRESS_COLUMN) or "") is not None


def _industries(row) -> Tuple[Industry, ...]:
    """The four pairs, positional, empties kept as `None` rather than compacted away.

    Nothing is normalised: a 行業代號 is the government's own code and a name folded to match
    something would be a name this file did not publish.
    """
    pairs = []
    for code_column, name_column in INDUSTRY_COLUMNS:
        code = (row.get(code_column) or "").strip()
        name = (row.get(name_column) or "").strip()
        pairs.append(Industry(code=code or None, name=name or None))
    return tuple(pairs)


def parse_rows(raw: bytes, wanted: Iterable[str]) -> TaxResult:
    """Decompress and read the CSV, keeping only the wanted 統編. **The expensive call.**

    Streamed rather than loaded: `ZipFile.open` plus `TextIOWrapper` hands `csv` one row at a
    time, so 320 MB is read in constant memory instead of parsed whole before the first record
    exists. That is not a nicety at this size — the whole file does not fit in the API
    container's memory.

    **Nothing is normalised beyond `strip`.** The names here are already clean single-line
    strings, and the address is audit context rather than join material (see `TaxRow`); folding
    an address that nothing matches on would imply a matching that does not happen. The 統編 is
    the only column joined on, and it is eight digits either way.
    """
    keep: Set[str] = {number.strip() for number in wanted if number and number.strip()}
    if not keep:
        raise FiaUnavailable(
            "{}: the reference list offered no 統編 to match — item 11's ingest has to have "
            "stored a place publication before this source has anything to join to".format(SOURCE)
        )
    result = TaxResult(wanted=len(keep))
    seen: Set[str] = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entry = _single_entry(archive)
        with _open_csv(archive, entry) as stream:
            reader = csv.DictReader(stream)
            _require_columns(reader.fieldnames)
            for index, row in enumerate(reader):
                if index == 0 and is_stamp_row(row):
                    continue
                result.scanned += 1
                business_no = (row.get(BUSINESS_NO_COLUMN) or "").strip()
                if business_no not in keep:
                    continue
                if business_no in seen:
                    # Measured zero on 2026-08-14, and counted rather than raised so that the
                    # day it stops being zero the verdict says so instead of the write failing.
                    result.duplicates += 1
                    continue
                seen.add(business_no)
                result.rows.append(
                    TaxRow(
                        business_no=business_no,
                        tax_name=(row.get(NAME_COLUMN) or "").strip(),
                        address=(row.get(ADDRESS_COLUMN) or "").strip(),
                        industries=_industries(row),
                    )
                )
    if not result.rows:
        raise FiaUnavailable(
            "{}: none of the {} reference 統編 appear in the file — {} rows were read, which "
            "is a shape change rather than a quiet day".format(SOURCE, len(keep), result.scanned)
        )
    return result
