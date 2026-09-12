"""The dataset export — one Parquet per reference publication, one row per place.

*Owner-ruled 2026-09-12 (「有好的資料集，才好訓練模型跟給資料科學家分析」; option (c) of
`idea & img/research/dataset-as-product.md`).* A data scientist gets a flat table: every place, the
name a person would recognise, the category with the model and prompt that produced it, and the
hashes of the files it was all composed against.

**The one rule that shapes this whole file: the name comes from the app's own read path.**
`api_common.place_display` is called, never re-implemented. The ladder — sign, then brand, then
registered name, then D92's bracket — lives in one place and is resolved at read time by D28's
ruling. A query written beside it would agree on the day it was written and start disagreeing the
first time the composition moved, and **a dataset that disagrees with the product is worse than no
dataset**, because it is believed. The cost is that this cannot run as plain SQL and needs a
session; that cost is the point.

**What a row is provenance for.** The name is composed against the *latest* publication of each
source, because that is what the read path uses (`order by detected_at desc limit 1`). So the
export records those publications' ids and content hashes rather than attributing a hash per row:
«this name was composed against these three files» is exactly true, and per-row attribution would
be a claim the read path does not make.

**What this does NOT export.** No member, no circle, no preference, no round, no weight. The
dataset is the *pipeline's* product. A circle-local place carries `origin = 'circle-local'` and its
own name — which a circle wrote — so those rows are excluded outright rather than filtered by
column: §3.0 says the product never publishes what a member typed.

**Row count.** One per reference place, and the job asserts it against `place`'s own count so a
partial write is a failure rather than a smaller file.

**This module imports with the standard library alone.** `sqlalchemy` and `pyarrow` are imported
inside the functions that need them, the same arrangement `upto/schema_guard.py` uses and for the
same reason: the column list and the dictionary are testable host-side, with no driver and no
100 MB wheel, and a test that can only run inside an image is a test that runs less often.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

#: Every column, in the order a reader meets them, with the source each comes from. The dictionary
#: shipped beside the data is generated from this tuple, so a column cannot exist without a
#: description — the failure this repository keeps meeting is a field nobody can explain.
COLUMNS: tuple[tuple[str, str], ...] = (
    ("registry_no", "`place.registry_no` — the government registry number, this row's key"),
    ("township_code", "`reference_place.township_code` in the publication named below"),
    ("township_name", "`reference_place.township_name` in the same publication"),
    ("display_name", "the app's own composed name (`api_common.place_display`), not a re-derivation"),
    ("name_source", "which rung produced it: `sign` · `brand` · `registered` — **null when the "
     "row has no name**, see the note below"),
    ("name_base", "the composed name without D92's bracket"),
    ("name_qualifier", "D92's bracket alone, or null when the name needed none"),
    ("category", "`place.category` — one of the thirteen, or null when undecided or a legal entity"),
    ("category_model", "`place.category_model` — the model that decided, by full identity"),
    ("category_prompt_version", "`place.category_prompt_version`"),
    ("category_input", "`place.category_input` — **the exact string the model was shown**"),
    ("category_generated_at", "`place.category_generated_at`, UTC"),
    ("place_publication_id", "the reference publication the name was composed against"),
    ("place_publication_sha256", "its `content_sha256` — the file's identity, not a timestamp"),
    ("storefront_publication_id", "the sign publication in force, or null if none exists yet"),
    ("storefront_publication_sha256", "its `content_sha256`"),
    ("brand_publication_id", "the brand publication in force, or null if none exists yet"),
    ("brand_publication_sha256", "its `content_sha256`"),
    ("exported_at", "when this file was written, UTC"),
)

#: Batched because `place_display` takes a list of ids and issues one query per call. 2,000 keeps
#: the `in :ids` list well inside any driver's parameter limit and the whole city inside twenty
#: round trips.
BATCH = 2000

_LATEST = (
    "select 'place' as source, id, content_sha256 from place_publication "
    "  order by detected_at desc, id desc limit 1"
)
_LATEST_STOREFRONT = (
    "select id, content_sha256 from storefront_publication order by detected_at desc, id desc limit 1"
)
_LATEST_BRAND = (
    "select id, content_sha256 from brand_publication order by detected_at desc, id desc limit 1"
)


async def publications_in_force(session) -> dict:
    """The three publications the read path would use right now, by id and hash.

    A source that has never published leaves its pair `None` — a null in the file, which is a fact
    about the pipeline's history rather than a gap in the row. Four of the seven sources had exactly
    one publication for weeks; a dataset that hid that would be hiding the thing a reader most needs
    to know about its own freshness.
    """
    from sqlalchemy import text  # noqa: PLC0415 — see the module docstring's importability note

    place = (await session.execute(text(_LATEST))).mappings().first()
    storefront = (await session.execute(text(_LATEST_STOREFRONT))).mappings().first()
    brand = (await session.execute(text(_LATEST_BRAND))).mappings().first()
    if place is None:
        raise RuntimeError(
            "no place publication exists — the reference ingest has never stored anything, so "
            "there is no publication to export a dataset under. Run the ingest first."
        )
    return {
        "place_publication_id": place["id"],
        "place_publication_sha256": place["content_sha256"],
        "storefront_publication_id": storefront["id"] if storefront else None,
        "storefront_publication_sha256": storefront["content_sha256"] if storefront else None,
        "brand_publication_id": brand["id"] if brand else None,
        "brand_publication_sha256": brand["content_sha256"] if brand else None,
    }


async def rows_for(session) -> list[dict]:
    """Every reference place as one flat row, with the name composed by the app itself.

    **`origin = 'reference'` and nothing else.** A circle-local place's name is a member's own
    words (§3.0), so it is excluded here rather than blanked — a column that is null for a reason
    nobody states is how a dataset acquires a footnote.
    """
    from sqlalchemy import text  # noqa: PLC0415

    from ..api_common import place_display  # noqa: PLC0415 — avoids an import cycle at module load

    provenance = await publications_in_force(session)
    exported_at = datetime.now(timezone.utc)

    base = (
        await session.execute(
            text(
                "select p.id, p.registry_no, p.category, p.category_model, "
                "       p.category_prompt_version, p.category_input, p.category_generated_at, "
                "       ref.township_code, ref.township_name "
                "  from place p "
                "  left join lateral ("
                "    select rp.township_code, rp.township_name from reference_place rp"
                "     where rp.registry_no = p.registry_no"
                "       and rp.publication_id = :pub"
                "     limit 1"
                "  ) ref on true "
                " where p.origin = 'reference' "
                " order by p.id"
            ),
            {"pub": provenance["place_publication_id"]},
        )
    ).mappings().all()

    out: list[dict] = []
    for start in range(0, len(base), BATCH):
        chunk = base[start:start + BATCH]
        composed = await place_display(session, [row["id"] for row in chunk])
        for row in chunk:
            name = composed.get(row["id"], {})
            out.append({
                "registry_no": row["registry_no"],
                "township_code": row["township_code"],
                "township_name": row["township_name"],
                "display_name": name.get("name"),
                "name_source": name.get("name_source"),
                "name_base": name.get("base"),
                "name_qualifier": name.get("qualifier"),
                "category": row["category"],
                "category_model": row["category_model"],
                "category_prompt_version": row["category_prompt_version"],
                "category_input": row["category_input"],
                "category_generated_at": row["category_generated_at"],
                "exported_at": exported_at,
                **provenance,
            })
    return out


async def expected_count(session) -> int:
    """`place`'s own count of reference rows, for the assertion the job makes against the file."""
    from sqlalchemy import text  # noqa: PLC0415

    return await session.scalar(
        text("select count(*) from place where origin = 'reference'")
    )


def write_parquet(rows: list[dict], path: str) -> int:
    """Write the rows and return how many. **pyarrow is imported here, not at module load.**

    The module has to stay importable where pyarrow is not installed — the api image does not have
    it and does not need it, and a test that reads `COLUMNS` should not need a 100 MB wheel.

    pyarrow 25.0.1, **Apache-2.0**, requires Python >= 3.10 (PyPI, read 2026-09-12). Snappy is its
    default compression — «In PyArrow we use Snappy compression by default, but Brotli, Gzip, ZSTD,
    LZ4, and uncompressed are also supported» (Arrow docs, read 2026-09-12) — and it is kept,
    because the reader most likely to open this file is pandas with defaults.
    """
    import pyarrow  # noqa: PLC0415
    import pyarrow.parquet  # noqa: PLC0415

    names = [name for name, _ in COLUMNS]
    table = pyarrow.table({name: [row.get(name) for row in rows] for name in names})
    pyarrow.parquet.write_table(table, path)
    return table.num_rows


def dictionary_markdown(publication_id: int, row_count: int) -> str:
    """The data dictionary that ships beside the file, generated from `COLUMNS`.

    **Generated rather than written**, so a column cannot be added without its description — the
    same rule as `server_copy.py` for member-facing strings, one directory over.
    """
    lines = [
        "# The dataset, column by column",
        "",
        "One row per place in the public reference list. Written from the product's own read path,",
        "so the name in this file is the name the app shows — not a re-derivation of it.",
        "",
        "*Reference publication `{}` · {} rows · written {}*".format(
            publication_id, row_count, datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ),
        "",
        "| column | what it is |",
        "|---|---|",
    ]
    lines += ["| `{}` | {} |".format(name, description) for name, description in COLUMNS]
    lines += [
        "",
        "## Two things worth knowing before you use it",
        "",
        "**`category_input` is the exact string the model was shown**, not the display name. The two",
        "differ whenever the ladder resolved a better name after the classification ran. It is here",
        "because it is what makes a verdict reproducible: you can ask the same model the same",
        "question.",
        "",
        "**A null `township_code` and `township_name` mean the place is not in the publication named",
        "in this row** — its registry number was listed once, the product made a row for it, and the",
        "current file no longer has it. The name survives (the read path falls back to the newest",
        "publication that still lists it) and only the district goes, which is why this null is the",
        "one a reader actually meets: **532 rows of 36,497 on 2026-09-12.**",
        "",
    "**A null `display_name` means the place is no longer in any publication this database holds.**",
        "Its registry number was listed once, the product made a row for it, and the source has since",
        "dropped it. `name_source` is null too, because no rung produced the name — the row is in the",
        "file so that a reader counting places is not quietly short, and it is named as unnamed rather",
        "than given a rung it does not have.",
        "",
    "**A null category is not a missing value.** It is either «not yet decided» or a recorded",
        "verdict that the row names a legal entity rather than a shop. `category_generated_at` tells",
        "them apart: null means never asked.",
        "",
        "**What is not here:** no member, no circle, no preference, no round, no weight. This is the",
        "pipeline's product, and circle-local places — whose names members wrote themselves — are",
        "excluded rather than blanked.",
    ]
    return "\n".join(lines) + "\n"


def object_names(prefix: str, publication_id: int) -> tuple[str, str]:
    """`(parquet, dictionary)` under the prefix, named by the publication rather than by the day.

    **The publication is the identity, not the date** — the same argument the dump's name makes
    with `alembic current`. Two exports of the same publication are the same dataset, so they
    overwrite rather than accumulate, and a reader comparing two files knows from the name whether
    the source moved between them.
    """
    stem = "{}/publication={}".format(prefix.strip("/"), publication_id)
    return "{}/places.parquet".format(stem), "{}/dictionary.md".format(stem)


def destination() -> tuple[str, str] | None:
    """`(bucket, prefix)`, or `None` when no bucket is configured.

    **Designed-off is a legal state (A10/A22's shape).** A fresh clone, `split_boot_check.sh` and CI
    all boot with no bucket; this returns `None` and the caller skips out loud rather than failing.
    """
    bucket = (os.environ.get("UPTO_BACKUP_S3_BUCKET") or "").strip()
    if not bucket:
        return None
    prefix = (os.environ.get("UPTO_DATASET_S3_PREFIX") or "dataset").strip().strip("/")
    return bucket, prefix
