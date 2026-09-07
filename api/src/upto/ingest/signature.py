"""D102 / M3 — a publication's column signature: what shape the source's file was.

*Written 2026-08-18, owner-ruled (D102). Revision 0021 adds the two columns this module fills.*

**The question M3 asks.** A source can change the shape of its file without changing what it is
about — rename a column, add one, reorder them — and this pipeline would carry on. Some of those
changes are invisible (a new column nobody reads), some silently empty a field, and nothing
records enough to tell which happened when. So each publication stores the ordered list of its
source's own field names, plus a hash of that list so a comparison is one equality rather than a
diff.

**Why the signature is taken at claim time and not at parse time.** D34's claim-before-parse
short-circuit is what makes a no-change day cheap — M9 measured it at 3.58 s against 12.95 s on
the tax registry — and a signature that needed the parse would spend that saving. Reading one
header line does not: the header is the first row of the CSV, or the key set of one record in a
JSON payload that has already been decoded to compute the content hash.

**Two derivations, one column, and the reason it is not two columns.** The four CSV sources have a
header row; the two CWA feeds are JSON and have none, so their signature is the sorted key set of a
record. A reader should not have to know which kind their source is to compare two signatures, and
a second column would make them. The derivation is recorded per source in the functions below.

**The order is the signature for CSV and cannot be for JSON.** A CSV's column order is part of its
shape — a source that swaps two columns has changed something a positional reader would break on —
so the names are hashed in file order. A JSON object's keys have no order to preserve, so they are
sorted before hashing; otherwise the same payload would sign differently depending on how the
decoder happened to walk it.

**Nothing computes anything from these columns yet, and that is by design.** They begin recording
now and are compared later, because the comparison needs two publications of the same source and
five of the seven have one. Revision 0021 backfills nothing (`NULL` where the publication predates
it), and the rows heal as each source republishes — the same rule H33 used, third time it decides
something.
"""

from __future__ import annotations

import hashlib
import json
from typing import Iterable, Mapping, Optional, Sequence

# The separator between names inside the hashed string. A unit separator rather than a comma,
# because a comma can appear inside a column name and would then make two different headers hash
# alike — `("a,b", "c")` and `("a", "b,c")` are not the same shape.
JOIN = "\x1f"


def digest(names: Sequence[str]) -> str:
    """The hash of an ordered name list. Empty in, empty out — never a hash of nothing."""
    if not names:
        return ""
    return hashlib.sha256(JOIN.join(names).encode("utf-8")).hexdigest()


def from_csv_header(names: Iterable[str]) -> tuple[str, list[str]]:
    """A CSV source's signature: the header cells, **in file order**.

    Taken as the parser sees them — after the existing decode, so a BOM has already gone — and not
    normalised further. Folding case or stripping punctuation here would hide exactly the rename
    this column exists to notice.
    """
    ordered = [name for name in names if name is not None]
    return digest(ordered), ordered


def from_json_keys(record: Optional[Mapping]) -> tuple[str, list[str]]:
    """A JSON source's signature: one record's key set, **sorted**.

    Sorted because a JSON object's keys carry no order, so hashing them in decode order would make
    the same payload sign differently on a different decoder. `None` or an empty record signs as
    empty rather than raising: a shape nobody could read is not a shape to assert.
    """
    if not record:
        return "", []
    ordered = sorted(str(key) for key in record.keys())
    return digest(ordered), ordered


def csv_header_from_stream(stream) -> tuple[str, list[str]]:
    """One header row from an already-open text stream, tolerating a file that will not decode.

    **A signature may never change which fetches are identifiable.** `fda.read_archive` identified
    a fetch without decoding its contents at all, so a zip whose entry is not UTF-8 used to reach
    the *parse* before failing — and one of `test_fda_ingest`'s cases depends on exactly that.
    Reading a header introduced a decode where there had been none, and the first version of this
    raised `UnicodeDecodeError` out of `read_archive`, moving a failure earlier in the pipeline for
    the sake of a column nothing reads yet. So the shape is best-effort: an undecodable or empty
    file signs as empty, and the run fails where it always failed.
    """
    import csv  # noqa: PLC0415

    try:
        header = next(csv.reader(stream), [])
    except (StopIteration, UnicodeDecodeError, csv.Error):
        return "", []
    return from_csv_header(header)


def csv_header(raw: bytes, encoding: str = "utf-8-sig") -> tuple[str, list[str]]:
    """A CSV source's signature, read from raw bytes without parsing the file.

    **One row is read, not the file.** `csv.reader` over a text stream stops at the first row when
    only one is asked for, so this costs a line rather than the megabytes behind it — which is what
    keeps D34's claim-before-parse short-circuit intact. `utf-8-sig` by default because every CSV
    in this pipeline is served with a BOM and the parsers already decode it that way; a signature
    taken with a different decode would differ from the header the parser sees, which is the one
    thing it must not do.
    """
    import io  # noqa: PLC0415

    if not raw:
        return "", []
    return csv_header_from_stream(
        io.TextIOWrapper(io.BytesIO(raw), encoding=encoding, newline="")
    )


def as_json(names: Sequence[str]) -> Optional[str]:
    """The `column_names` column's value. `None` for an empty list, so "no signature taken" and
    "a file with no columns" are different rows rather than the same empty array."""
    if not names:
        return None
    return json.dumps(list(names), ensure_ascii=False)
