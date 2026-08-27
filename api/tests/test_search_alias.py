#!/usr/bin/env python3
"""D113's authored alias — the two iron laws and the four bounds, held by assertion.

Run: python3 app/api/tests/test_search_alias.py    (no network, no database)

D113 permits the first data in this product that no publisher stands behind, and it permits it under
conditions. **Conditions that only exist in prose are conditions that erode**, so each one here is a
test:

  iron law 1  match-only, never displayed  -> the rendered name is pinned to D92's ladder, and
                                              `search_alias` may appear in no `select`
  iron law 2  authored provenance per row  -> author, date and verifying note on every entry
  bound       its own table, joins nothing -> no foreign key in the migration
  bound       never feeds the classifier,  -> only the search path and the seed may name the table,
              the crib, or a derived name     asserted by walking every module
  bound       small, no completeness claim -> a ceiling, so growth has to come past this file

**The test that matters most is the fourth.** The others fail loudly if broken; that one is about a
table quietly acquiring readers, which is how a match-only lookup becomes a source of names.
"""

import ast
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src", "upto")
MIGRATION = os.path.join(HERE, "..", "migrations", "versions", "0028_search_alias.py")
BASIS_MIGRATION = os.path.join(HERE, "..", "migrations", "versions", "0029_alias_basis.py")

sys.path.insert(0, os.path.join(HERE, "..", "src"))

from upto.seed.aliases import ALIASES, AUTHOR, OWNER_RULED, PAIRING  # noqa: E402

# The only two modules allowed to name the table: the search that reads it, and the seed that
# writes it. **A module added here is a bound being widened and belongs in a ruling, not a diff.**
# `live.py` runs the search; `aliases.py` is the authored seed. **`roles.py` joined on 2026-08-27
# with A15/D115** and it is a different kind of naming: it lists every table in a GRANT map, so it
# names `search_alias` in order to say *which role may touch it*, not in order to read it. Excluding
# it does not weaken the bound — a grant map that could silently omit a table is a worse failure than
# the one this sweep guards, and `test_role_grants.py` refuses any table in `public` without a line
# there. The two tests pull in opposite directions on purpose, and this comment is the seam.
MAY_NAME_THE_TABLE = {"live.py", "aliases.py", "roles.py"}

# D113: "the table stays small (common foreign-branded chains; there is no completeness claim)".
# A ceiling rather than a target — it exists so that growth has to argue with this file.
CEILING = 25


def modules():
    for root, _dirs, files in os.walk(SRC):
        for name in sorted(files):
            if name.endswith(".py"):
                yield name, os.path.join(root, name)


class TheAliasIsNeverDisplayed(unittest.TestCase):
    """Iron law 1. The alias widens what a query hits; every name a member SEES comes from a
    publisher through D92's ladder."""

    def live(self):
        return open(os.path.join(SRC, "live.py"), encoding="utf-8").read()

    def test_the_rendered_name_is_still_the_ladder_and_only_the_ladder(self):
        """**The single edit that would break the ruling** is adding the alias to this coalesce, so
        the coalesce is pinned here character for character. If a rung is ever legitimately added,
        this test is where the change gets noticed."""
        self.assertIn(
            "coalesce(storefront.name, brand.brand_name, rp.name) as name", self.live())

    def sql_literals(self, module="live.py"):
        """Every string literal in the module, from the AST.

        **Counted in the code, not in the text, and the first version of this test got that wrong.**
        It used `source.count("search_alias")` and read 2 instead of 1 — one occurrence in the SQL and
        one in the *comment explaining the rule*, which is H44's shape exactly. Third time in two
        days: a gate that matched its own docstring, a hazard test that forbade a substring appearing
        in its own prose, and this. A guard over source reads the AST.
        """
        tree = ast.parse(open(os.path.join(SRC, module), encoding="utf-8").read())
        return [node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)]

    def test_the_table_is_read_in_a_where_and_never_selected_from_for_a_name(self):
        """It may appear only as the subquery that widens the match. Any other shape — a join, a
        column in the projection — is the law being broken."""
        naming = [text for text in self.sql_literals() if "search_alias" in text]
        self.assertEqual(len(naming), 1, "search_alias is named in {} string literals: {}".format(
            len(naming), naming))
        self.assertIn("select registered_name from search_alias", naming[0])

    def test_the_alias_column_is_never_projected(self):
        """`registered_name` is a publisher's string and may cross into a query; `alias` is ours and
        may not leave the `where`."""
        for text in self.sql_literals():
            self.assertNotIn("select alias", text)
            self.assertNotIn("alias as", text)


class EveryRowSaysWhoWroteItAndWhy(unittest.TestCase):
    """Iron law 2. An alias error is ours and traceable to nobody else."""

    def test_there_is_at_least_one_and_not_more_than_the_ceiling(self):
        self.assertGreaterEqual(len(ALIASES), 1)
        self.assertLessEqual(
            len(ALIASES), CEILING,
            "D113 bounds this table to common foreign-branded chains; growing past the ceiling is "
            "a ruling, not a diff")

    def test_every_row_carries_an_author_a_date_a_basis_and_a_note(self):
        for alias, registered, authored, basis, note in ALIASES:
            self.assertTrue(alias.strip(), alias)
            self.assertTrue(registered.strip(), alias)
            self.assertIsNotNone(authored, alias)
            self.assertIn(basis, (PAIRING, OWNER_RULED), alias)
            self.assertTrue(note.strip(), alias)

    def test_each_row_is_justified_the_way_its_basis_claims(self):
        """**Reads the basis column, and the first version of this read the prose — which passed
        falsely.** It asserted every note names `brand_registration`; the two owner-ruled rows
        satisfied that because their notes mention `brand_registration` *to say it does not support
        them*. A true assertion about the wrong subject, the sixth of that shape this week. The basis
        is structural now and this checks each path against its own standard.
        """
        for alias, _registered, _authored, basis, note in ALIASES:
            if basis == PAIRING:
                self.assertIn("brand_registration", note, alias)
            else:
                # D113's amendment: the note cites the ruling, which is the whole of the exception
                # path. A date makes it findable in the decision log; the word makes it unmistakable.
                self.assertIn("OWNER-RULED", note, alias)
                self.assertIn("2026-", note, alias)

    def test_no_note_rests_on_common_knowledge(self):
        """D113's fence, stated as a refusal rather than left implicit. An owner-ruled row is an
        *assertion somebody is accountable for*; "everyone knows" is an assertion nobody is."""
        for alias, _registered, _authored, _basis, note in ALIASES:
            lowered = note.lower()
            for banned in ("everyone knows", "common knowledge", "obviously", "well known"):
                self.assertNotIn(banned, lowered, alias)

    def test_an_owner_ruled_row_says_how_to_withdraw_it(self):
        """A pairing row is withdrawn by checking a source. An owner-ruled row can only be withdrawn
        by asking the owner, and a reader who does not know that will go looking for a source that
        does not exist."""
        for alias, _registered, _authored, basis, note in ALIASES:
            if basis == OWNER_RULED:
                self.assertIn("assertion", note.lower(), alias)

    def test_the_author_is_named_and_is_not_a_publisher(self):
        self.assertEqual(AUTHOR, "operator")

    def test_no_alias_duplicates_another(self):
        pairs = [(a, r) for a, r, _d, _b, _n in ALIASES]
        self.assertEqual(len(pairs), len(set(pairs)))


class NothingElseMayReadTheTable(unittest.TestCase):
    """The bound that matters most, because breaking it is silent: a match-only lookup quietly
    acquiring readers is how it becomes a source of names."""

    def test_only_the_search_and_the_seed_name_the_table(self):
        offenders = []
        for name, path in modules():
            if name in MAY_NAME_THE_TABLE:
                continue
            # Literals, not text — a module that merely *mentions* the table in a comment
            # explaining why it must not read it is not an offender. Same lesson as above.
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:  # pragma: no cover
                continue
            literals = [n.value for n in ast.walk(tree)
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            if any("search_alias" in literal for literal in literals):
                offenders.append(os.path.relpath(path, SRC))
        self.assertEqual(
            offenders, [],
            "D113 bounds the alias table to the search path; these modules name it: "
            + repr(offenders))

    def test_the_classifier_and_the_crib_do_not_import_the_seed(self):
        """Named separately from the sweep above because these are the two D113 calls out, and a
        test that says *why* survives a refactor better than one that only says *what*."""
        for name, path in modules():
            relative = os.path.relpath(path, SRC)
            if not (relative.startswith("classify") or relative.startswith("evaluate")):
                continue
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    self.assertNotIn("aliases", node.module, relative)
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for entry in node.names:
                        self.assertNotIn("aliases", entry.name, relative)

    def test_no_derived_name_reads_it(self):
        """`naming.py` composes what a member sees; `api_common.compose_names` assembles it. If
        either ever names this table, iron law 1 has been broken somewhere upstream of the SQL."""
        for module in ("naming.py", "api_common.py"):
            path = os.path.join(SRC, module)
            if os.path.exists(path):
                self.assertNotIn("search_alias", open(path, encoding="utf-8").read(), module)


class TheTableJoinsNothing(unittest.TestCase):
    def test_the_migration_declares_no_foreign_key(self):
        """D113's «joins nothing else». `registered_name` is text matched against a
        publication-scoped name; a foreign key would drag the alias into the publication lifecycle
        and would not be the last join added."""
        source = open(MIGRATION, encoding="utf-8").read()
        self.assertNotIn("ForeignKey", source)
        self.assertNotIn("foreign_key", source)

    def test_the_provenance_columns_are_not_nullable(self):
        source = open(MIGRATION, encoding="utf-8").read()
        for column in ("authored_by", "authored_at", "note"):
            index = source.index('"{}"'.format(column))
            self.assertIn("nullable=False", source[index:index + 200], column)

    def test_the_basis_column_is_constrained_to_the_two_paths(self):
        """0029. A basis that can be any string is a basis nobody has to justify."""
        source = open(BASIS_MIGRATION, encoding="utf-8").read()
        self.assertIn("basis in ('pairing', 'owner-ruled')", source)
        self.assertIn('alter_column("search_alias", "basis", nullable=False)', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
