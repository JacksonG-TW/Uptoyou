#!/usr/bin/env python3
"""The brand ingest (D77) — parse, identify, sequence. No network, no database.

Run: python3 app/api/tests/test_foodtracer_ingest.py

Three facts carry the ticket and each gets its own class. The pairs are **deduplicated on the
normalised strings**, because 0013's primary key will refuse what the parse fails to fold.
The company column is normalised **with the same function as `reference_place.name`**,
because an exact-string join against that column is the entire point of storing it. And the
sequencing holds item 11's guarantee — an unchanged day never parses — proven the only way it
can be: with a parser that raises.
"""

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.ingest import foodtracer  # noqa: E402
from upto.ingest import runlog  # noqa: E402
from upto.ingest.foodtracer import (  # noqa: E402
    FoodtracerUnavailable,
    parse_pairs,
    read_sheet,
)
from upto.ingest.run_brands import ingest_sheet, run_record  # noqa: E402

HEADER = "行政區域代碼,公司名稱,品牌名稱,產品名稱,原料名稱,原料品牌,每一份量,熱量大卡,相關資訊連結"

NOW = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)


def row(company, brand, product="某產品"):
    return "63000000,{},{},{},麵粉,某牌,100g,200,https://example.invalid".format(
        company, brand, product
    )


def csv_bytes(rows, header=HEADER, bom=True):
    body = "\n".join([header] + rows) + "\n"
    return ("﻿" + body if bom else body).encode("utf-8")


class Parsing(unittest.TestCase):
    def test_a_repeated_pair_is_stored_once(self):
        # The file is product-level: 一風堂 appears once per product per ingredient.
        raw = csv_bytes(
            [
                row("台灣一風堂股份有限公司", "一風堂", "白丸元味"),
                row("台灣一風堂股份有限公司", "一風堂", "赤丸新味"),
                row("台灣一風堂股份有限公司", "一風堂", "白丸元味"),
            ]
        )
        result = parse_pairs(raw)
        self.assertEqual(result.scanned, 3)
        self.assertEqual(len(result.pairs), 1)
        self.assertEqual(result.companies, 1)

    def test_one_company_may_carry_several_brands(self):
        # 15 of 266 companies do (measured 2026-08-14). The table stores every pair; which
        # pair a reader trusts is the read path's rule, not the parser's.
        raw = csv_bytes(
            [
                row("頂呱呱國際股份有限公司", "頂呱呱"),
                row("頂呱呱國際股份有限公司", "東京油組"),
            ]
        )
        result = parse_pairs(raw)
        self.assertEqual(len(result.pairs), 2)
        self.assertEqual(result.companies, 1)

    def test_the_company_is_normalised_like_the_fda_name_and_the_raw_survives(self):
        # Full-width digits and 台→臺 fold exactly as `fda.normalise` folds them — the join
        # is exact-string, so the two columns must be normalised by the one function (H24).
        raw = csv_bytes([row("台北１２３股份有限公司", "某牌")])
        pair = parse_pairs(raw).pairs[0]
        self.assertEqual(pair.company_name, "臺北123股份有限公司")
        self.assertEqual(pair.company_name_raw, "台北１２３股份有限公司")
        self.assertEqual(
            pair.company_name, foodtracer.normalise(pair.company_name_raw),
            "the parser and fda.normalise disagree — the join will silently rot",
        )

    def test_a_row_with_no_brand_is_counted_and_kept_out(self):
        raw = csv_bytes([row("某公司", ""), row("有牌公司", "有牌")])
        result = parse_pairs(raw)
        self.assertEqual(result.scanned, 2)
        self.assertEqual(len(result.pairs), 1)

    def test_two_spellings_that_normalise_together_are_one_pair(self):
        # Kept as two, they would collide on 0013's primary key at write time instead.
        raw = csv_bytes([row("台灣好店股份有限公司", "好店"), row("臺灣好店股份有限公司", "好店")])
        self.assertEqual(len(parse_pairs(raw).pairs), 1)

    def test_a_bom_prefixed_csv_parses_rather_than_renaming_its_first_column(self):
        raw = csv_bytes([row("某公司", "某牌")], bom=True)
        self.assertEqual(len(parse_pairs(raw).pairs), 1)

    def test_a_missing_column_is_a_failure_naming_what_is_missing(self):
        raw = csv_bytes([row("某公司", "某牌")], header=HEADER.replace("品牌名稱", "牌子"))
        with self.assertRaises(FoodtracerUnavailable) as failure:
            parse_pairs(raw)
        self.assertIn("品牌名稱", str(failure.exception))

    def test_a_file_with_no_pairs_is_a_failure_not_an_empty_success(self):
        with self.assertRaises(FoodtracerUnavailable):
            parse_pairs(csv_bytes([row("某公司", "")]))


class SheetIdentity(unittest.TestCase):
    def test_the_hash_is_sha256_shaped_and_stable(self):
        raw = csv_bytes([row("某公司", "某牌")])
        first = read_sheet(raw, NOW)
        second = read_sheet(raw, NOW)
        self.assertEqual(len(first.content_sha256), 64)
        self.assertEqual(first.content_sha256, second.content_sha256)

    def test_different_bytes_are_a_different_publication(self):
        one = read_sheet(csv_bytes([row("甲", "乙")]), NOW)
        two = read_sheet(csv_bytes([row("甲", "丙")]), NOW)
        self.assertNotEqual(one.content_sha256, two.content_sha256)

    def test_an_empty_body_is_a_failure_not_an_empty_success(self):
        with self.assertRaises(FoodtracerUnavailable):
            read_sheet(b"", NOW)

    def test_the_raw_bytes_stay_out_of_the_repr(self):
        sheet = read_sheet(csv_bytes([row("某公司", "某牌")]), NOW)
        self.assertNotIn("公司", repr(sheet))


class FakeStore:
    """Stands in for `BrandStore`. The sequencing is what is under test, not the SQL."""

    def __init__(self, claim_id=7, held_id=None):
        self._claim_id = claim_id
        self._held_id = held_id
        self.written = []
        # A19: the ingredient half, offered from the same parse in the same transaction. Kept
        # separately from `written` because the two halves are separately meaningful — a file that
        # carries pairs and no products writes one and not the other, and a fake that pooled them
        # could not tell that case from a working one.
        self.materials = []
        self.committed = False
        self.rolled_back = False
        self.counted = None

    async def write_materials(self, publication_id, materials):
        self.materials.append((publication_id, list(materials)))
        return len(materials)

    async def claim(self, sheet, scope):
        return self._claim_id

    async def held(self, source, content_sha256):
        # Not `brand_store.HeldPublication`: importing that module pulls sqlalchemy in, and
        # this file runs on the host, where fda's own tests keep that import deferred too.
        if self._held_id is None:
            return None
        from types import SimpleNamespace

        return SimpleNamespace(
            publication_id=self._held_id, content_sha256=content_sha256, detected_at=NOW
        )

    async def write(self, publication_id, pairs):
        self.written.extend(pairs)
        return len(pairs)

    async def accepted(self, publication_id):
        return len(self.written)

    async def record_count(self, publication_id, pair_rows):
        self.counted = pair_rows

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def refuse_to_parse(raw):
    raise AssertionError("an unchanged day parsed the CSV")


class Sequencing(unittest.TestCase):
    def test_unchanged_content_does_not_parse_and_is_a_silent_success(self):
        sheet = read_sheet(csv_bytes([row("某公司", "某牌")]), NOW)
        store = FakeStore(claim_id=None, held_id=3)
        verdict = asyncio.run(ingest_sheet(store, sheet, parse=refuse_to_parse))
        self.assertFalse(verdict.parsed)
        self.assertFalse(verdict.stored)
        self.assertEqual(verdict.publication_id, 3)
        self.assertTrue(store.rolled_back)
        self.assertIn("no change", verdict.line())

    def test_new_content_parses_and_writes(self):
        sheet = read_sheet(csv_bytes([row("某公司", "某牌")]), NOW)
        store = FakeStore(claim_id=7)
        verdict = asyncio.run(ingest_sheet(store, sheet))
        # **A19: the ingredient half went to the store from the same parse.** The fake accepted
        # this method only after `run_brands` started calling it — the first version of that call
        # turned two tests red with `'FakeStore' object has no attribute 'write_materials'`, which
        # is the fake doing its job: a stand-in that silently absorbed an unknown call would have
        # let the wiring ship untested.
        self.assertEqual(len(store.materials), 1, store.materials)
        offered_publication, offered = store.materials[0]
        self.assertEqual(offered_publication, 7)
        self.assertTrue(offered, "the parse produced no materials for a row that has both columns")
        self.assertTrue(verdict.stored)
        self.assertEqual(verdict.publication_id, 7)
        self.assertEqual(verdict.pairs_held, 1)
        self.assertEqual(store.counted, 1)
        self.assertTrue(store.committed)

    def test_force_parse_writes_against_the_publication_already_held(self):
        sheet = read_sheet(csv_bytes([row("某公司", "某牌")]), NOW)
        store = FakeStore(claim_id=None, held_id=3)
        verdict = asyncio.run(ingest_sheet(store, sheet, force_parse=True))
        self.assertTrue(verdict.parsed)
        self.assertFalse(verdict.stored)
        self.assertEqual(verdict.publication_id, 3)


class RunRow(unittest.TestCase):
    """The verdict-to-ledger mapping, held to `run_places`'s three rules."""

    def verdict(self, stored, held=5):
        from upto.ingest.run_brands import Verdict

        return Verdict(
            source=foodtracer.SOURCE,
            content_sha256="a" * 64,
            stored=stored,
            parsed=stored,
            publication_id=9,
            pairs_held=held,
        )

    def test_a_stored_run_files_its_publication_under_the_brand_column(self):
        record = run_record(self.verdict(stored=True), NOW, "cli")
        self.assertEqual(record.outcome, runlog.STORED)
        self.assertEqual(record.column(), "brand_publication_id")
        self.assertEqual(record.rows_written, 5)

    def test_a_no_op_attaches_no_publication(self):
        record = run_record(self.verdict(stored=False), NOW, "cli")
        self.assertEqual(record.outcome, runlog.NO_CHANGE)
        self.assertIsNone(record.publication_id)
        self.assertEqual(record.rows_written, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
