"""Write the brand publication and its pairs, or discover the content is already held.

The same mechanism as `fda_store` — the publication is claimed with `insert … on conflict do
nothing returning id`, so the *database* decides whether the content is new, and the claim is
what gates the parse. A separate module for the same reason that one is separate from item
10's: different statements, different key columns, and one writer serving two schemas would
be one file pretending they are one.

One transaction covers claim → write → count. A crash in the middle leaves no publication
row at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from . import signature
from .foodtracer import BrandPair, Sheet

CHUNK = 5000

CLAIM_PUBLICATION = """
insert into brand_publication
    (source, content_sha256, detected_at, payload_bytes, scope,
     column_signature, column_names)
values
    (:source, :content_sha256, :detected_at, :payload_bytes, :scope,
     :column_signature, :column_names)
on conflict (source, content_sha256) do nothing
returning id
"""

LATEST_PUBLICATION = """
select id, content_sha256, detected_at
from brand_publication
where source = :source
order by detected_at desc, id desc
limit 1
"""

HELD_PUBLICATION = """
select id, content_sha256, detected_at
from brand_publication
where source = :source and content_sha256 = :content_sha256
"""

INSERT_PAIR = """
insert into brand_registration
    (publication_id, company_name, company_name_raw, brand_name, brand_name_raw)
values
    (:publication_id, :company_name, :company_name_raw, :brand_name, :brand_name_raw)
on conflict (publication_id, company_name, brand_name) do nothing
"""


# **A19: the ingredient half of the same file, written beside the pairs in the same transaction.**
#
# `on conflict do nothing` for the same reason the pair insert has it — the parse already dedupes on
# this exact key, so a conflict here would mean the file changed shape under us, and refusing the
# row is the same answer as ignoring it. What must never happen is a partial publication: both
# writes are in one transaction and one `commit`, so a publication either holds its pairs and its
# materials or holds neither.
INSERT_MATERIAL = """
insert into product_material
    (publication_id, company_name, brand_name, product_name, material_name, material_name_raw)
values
    (:publication_id, :company_name, :brand_name, :product_name, :material_name,
     :material_name_raw)
on conflict (publication_id, company_name, brand_name, product_name, material_name) do nothing
"""


@dataclass(frozen=True)
class HeldPublication:
    publication_id: int
    content_sha256: str
    detected_at: datetime


class BrandStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest(self, source: str) -> Optional[HeldPublication]:
        result = await self._session.execute(text(LATEST_PUBLICATION), {"source": source})
        return _held(result.fetchone())

    async def held(self, source: str, content_sha256: str) -> Optional[HeldPublication]:
        result = await self._session.execute(
            text(HELD_PUBLICATION), {"source": source, "content_sha256": content_sha256}
        )
        return _held(result.fetchone())

    async def claim(self, sheet: Sheet, scope: str) -> Optional[int]:
        """Insert the publication, or learn that this content is already held (`None`)."""
        result = await self._session.execute(
            text(CLAIM_PUBLICATION),
            {
                "source": sheet.source,
                "content_sha256": sheet.content_sha256,
                "detected_at": sheet.detected_at,
                "payload_bytes": sheet.payload_bytes,
                "scope": scope,
                # D102 / M3: the file's own shape, taken at identify time. `NULL` on a
                # publication whose fetch predates the signature — nothing is backfilled.
                "column_signature": sheet.column_signature or None,
                "column_names": signature.as_json(sheet.column_names),
            },
        )
        return result.scalar()

    async def write(self, publication_id: int, pairs: Sequence[BrandPair]) -> int:
        """Write the pairs. Returns the number offered, not the number accepted."""
        offered = 0
        for start in range(0, len(pairs), CHUNK):
            batch = [
                {
                    "publication_id": publication_id,
                    "company_name": pair.company_name,
                    "company_name_raw": pair.company_name_raw,
                    "brand_name": pair.brand_name,
                    "brand_name_raw": pair.brand_name_raw,
                }
                for pair in pairs[start:start + CHUNK]
            ]
            if not batch:
                continue
            await self._session.execute(text(INSERT_PAIR), batch)
            offered += len(batch)
        return offered

    async def write_materials(self, publication_id: int, materials: Sequence) -> int:
        """Write the product materials. Returns the number offered, not the number accepted.

        **Separate from `write` on purpose.** The pairs are what every name on every screen depends
        on; the materials are an addition. A caller that has pairs and no materials — an older file,
        or one that stopped carrying 產品名稱 — writes the pairs and calls this with nothing, and
        the publication is still a good one.
        """
        offered = 0
        for start in range(0, len(materials), CHUNK):
            batch = [
                {
                    "publication_id": publication_id,
                    "company_name": item.company_name,
                    "brand_name": item.brand_name,
                    "product_name": item.product_name,
                    "material_name": item.material_name,
                    "material_name_raw": item.material_name_raw,
                }
                for item in materials[start:start + CHUNK]
            ]
            if not batch:
                continue
            await self._session.execute(text(INSERT_MATERIAL), batch)
            offered += len(batch)
        return offered

    async def accepted(self, publication_id: int) -> int:
        result = await self._session.execute(
            text("select count(*) from brand_registration where publication_id = :id"),
            {"id": publication_id},
        )
        return int(result.scalar() or 0)

    async def record_count(self, publication_id: int, pair_rows: int) -> None:
        await self._session.execute(
            text("update brand_publication set pair_rows = :n where id = :id"),
            {"n": pair_rows, "id": publication_id},
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        """End the transaction a no-op run opened. Nothing was written; nothing is wrong."""
        await self._session.rollback()


def _held(row) -> Optional[HeldPublication]:
    if row is None:
        return None
    return HeldPublication(
        publication_id=row.id,
        content_sha256=row.content_sha256,
        detected_at=row.detected_at,
    )
