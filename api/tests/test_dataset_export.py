#!/usr/bin/env python3
"""The dataset export's rules, host-side: no database, no pyarrow, no image.

*Candidate for the dataset export, owner-ruled 2026-09-12 (option (c) of
`idea & img/research/dataset-as-product.md`).*

**What is here is what does not need the world.** The column list, the generated dictionary, the
object names, and the bucket-empty skip. The half that needs a database and a real Parquet file is
`test_dataset_export_integration.py`, and neither file is sufficient without the other.

**`upto.dataset.export` imports with the standard library alone**, which is what makes this file
possible — `sqlalchemy` and `pyarrow` are imported inside the functions that need them, the same
arrangement `upto/schema_guard.py` uses. This test asserts that too, because the moment it stops
being true this file stops being able to run and the reason would look like an unrelated breakage.

    python3 app/api/tests/test_dataset_export.py
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from upto.dataset import export  # noqa: E402


class TheModuleCostsNothingToImport(unittest.TestCase):
    def test_it_imports_without_sqlalchemy_or_pyarrow(self):
        """**Asserted rather than relied on.** If a future edit moves either import to the top,
        this file and the dictionary's generation stop being runnable outside an image — and the
        failure would read as a missing dependency rather than as a decision that was reversed."""
        self.assertNotIn("sqlalchemy", sys.modules, "export pulled in sqlalchemy at import time")
        self.assertNotIn("pyarrow", sys.modules, "export pulled in pyarrow at import time")


class EveryColumnHasADescription(unittest.TestCase):
    """The dictionary is generated from `COLUMNS`, so a column cannot ship without one — the same
    rule `server_copy.py` holds for member-facing strings."""

    def test_names_are_unique_and_non_empty(self):
        names = [name for name, _ in export.COLUMNS]
        self.assertEqual(len(names), len(set(names)), "a column name appears twice")
        self.assertTrue(all(names), "a column has an empty name")

    def test_every_column_carries_a_description(self):
        for name, description in export.COLUMNS:
            self.assertTrue(description.strip(), "{} has no description".format(name))

    def test_the_columns_a_reader_is_promised_are_all_there(self):
        """The four groups the research page named, asserted by name so a rename is visible."""
        names = {name for name, _ in export.COLUMNS}
        for expected in ("registry_no", "township_code", "township_name",
                         "display_name", "name_source", "name_base", "name_qualifier",
                         "category", "category_model", "category_prompt_version",
                         "category_input", "category_generated_at",
                         "place_publication_id", "place_publication_sha256",
                         "exported_at"):
            self.assertIn(expected, names)

    def test_nothing_about_a_member_is_in_the_column_list(self):
        """§3.0: the dataset is the pipeline's product. A column named for a person would be the
        quietest possible way for one to arrive."""
        names = " ".join(name for name, _ in export.COLUMNS)
        for forbidden in ("member", "circle", "principal", "preference", "device", "nickname",
                          "seat", "round", "weight", "proposal", "trip"):
            self.assertNotIn(forbidden, names, "{} appears in a column name".format(forbidden))


class TheDictionaryIsGenerated(unittest.TestCase):
    def test_it_names_every_column(self):
        text = export.dictionary_markdown(30, 36497)
        for name, _ in export.COLUMNS:
            self.assertIn("`{}`".format(name), text)

    def test_it_states_the_publication_and_the_row_count(self):
        text = export.dictionary_markdown(30, 36497)
        self.assertIn("30", text)
        self.assertIn("36497", text)

    def test_it_explains_the_two_columns_a_reader_will_misread(self):
        """`category_input` is not the display name, and a null category is not a missing value.
        Both are stated because both are the kind of thing a reader assumes wrongly and silently."""
        text = export.dictionary_markdown(30, 1)
        self.assertIn("category_input", text)
        self.assertIn("null category is not a missing value", text)


class TheDestinationSkipsRatherThanGuesses(unittest.TestCase):
    """A22's designed-off shape: an empty bucket is the default state of a fresh clone and of CI,
    and it is not a failure."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("UPTO_BACKUP_S3_BUCKET", "UPTO_DATASET_S3_PREFIX")}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_no_bucket_is_none_rather_than_an_exception(self):
        os.environ.pop("UPTO_BACKUP_S3_BUCKET", None)
        self.assertIsNone(export.destination())

    def test_whitespace_is_not_a_bucket(self):
        """A variable set to a space is the shape a hand-edited `.env` produces, and it must read
        as absent rather than as a bucket named ' '."""
        os.environ["UPTO_BACKUP_S3_BUCKET"] = "   "
        self.assertIsNone(export.destination())

    def test_a_bucket_gives_a_default_prefix(self):
        os.environ["UPTO_BACKUP_S3_BUCKET"] = "a-bucket"
        os.environ.pop("UPTO_DATASET_S3_PREFIX", None)
        self.assertEqual(export.destination(), ("a-bucket", "dataset"))

    def test_the_prefix_is_normalised(self):
        os.environ["UPTO_BACKUP_S3_BUCKET"] = "a-bucket"
        os.environ["UPTO_DATASET_S3_PREFIX"] = "/sets/places/"
        self.assertEqual(export.destination(), ("a-bucket", "sets/places"))


class TheObjectIsNamedByThePublication(unittest.TestCase):
    def test_both_names_sit_under_one_publication_folder(self):
        parquet, dictionary = export.object_names("dataset", 30)
        self.assertEqual(parquet, "dataset/publication=30/places.parquet")
        self.assertEqual(dictionary, "dataset/publication=30/dictionary.md")

    def test_two_exports_of_one_publication_are_the_same_object(self):
        """**The publication is the identity, not the day.** Re-running an export must overwrite
        rather than accumulate, or a month of identical files is indistinguishable from a month of
        changes."""
        self.assertEqual(export.object_names("dataset", 30), export.object_names("dataset", 30))
        self.assertNotEqual(export.object_names("dataset", 30), export.object_names("dataset", 31))


if __name__ == "__main__":
    unittest.main(verbosity=2)
