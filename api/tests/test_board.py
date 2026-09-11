#!/usr/bin/env python3
"""Candidate 17 — the member's 6×6 board: the picture of the draw, with nothing countable on it.

*Owner-ruled 2026-09-11: coloured at the reveal only, row = die 1, column = die 2, the operator grid
unchanged.* The member's wire gains 36 cells, one place id each, and **no count and no share**
(D105 as amended: the picture, not the figure).

**Host-side, because the rule needs no database.** The board is a pure function of the folded
weights — `upto.engine.table.board` — and the wiring into the payload and the member whitelist is
`test_api_rounds_integration`'s and `test_operator_view_integration`'s. Neither file is sufficient
without the other.

**The three assertions the ruling names are here, plus the one it implies.** The cell for the rolled
pair equals the winner; a vetoed place appears in zero cells; the per-place cell counts equal
`allocate`'s — *this test may count, the wire may not.* The fourth is the orientation, and it is the
one that needs care: most cells look the same transposed, so it is asserted only where a transpose
would actually show, and the precondition for that is its own failing test rather than a comment.

    python3 app/api/tests/test_board.py
"""

from __future__ import annotations

import os
import sys
import unittest
from collections import Counter
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from upto.engine.table import OUTCOMES, allocate, board, build, place_for  # noqa: E402


def weights(**kw) -> dict[int, Decimal]:
    return {int(place): Decimal(value) for place, value in kw.items()}


THREE = weights(**{"10": "1", "20": "2", "30": "3"})
WITH_VETO = weights(**{"10": "1", "20": "2", "30": "0"})


class TheBoardIsTheDraw(unittest.TestCase):
    """Not «agrees with» — IS. Both come from the same 36-slot table."""

    def test_every_cell_names_the_place_the_draw_would_land_on(self):
        table = build(THREE)
        cells = board(THREE)
        for die1 in range(1, 7):
            for die2 in range(1, 7):
                self.assertEqual(cells[die1 - 1][die2 - 1], place_for(table, die1, die2),
                                 "cell ({}, {}) disagrees with the draw".format(die1, die2))

    def test_the_cell_for_the_rolled_pair_is_the_winner(self):
        """The ruling's own line. A member checking the board against the result checks this."""
        table = build(THREE)
        for die1, die2 in OUTCOMES:
            winner = place_for(table, die1, die2)
            self.assertEqual(board(THREE)[die1 - 1][die2 - 1], winner)

    def test_it_is_six_by_six_and_holds_thirty_six_cells(self):
        cells = board(THREE)
        self.assertEqual(len(cells), 6)
        self.assertEqual({len(row) for row in cells}, {6})
        self.assertEqual(sum(len(row) for row in cells), 36)


class NothingCountableRidesOnIt(unittest.TestCase):
    def test_a_vetoed_place_appears_in_no_cell(self):
        """D45's veto survives the apportionment, so it must survive the picture of it."""
        seen = {place for row in board(WITH_VETO) for place in row}
        self.assertNotIn(30, seen)
        self.assertEqual(seen, {10, 20})

    def test_the_cell_counts_equal_allocate(self):
        """**This test may count; the wire may not.** The board carries no number — the check that
        it still says what `allocation` says is here, not on a member's screen."""
        counted = Counter(place for row in board(THREE) for place in row)
        expected = {place: n for place, n in allocate(THREE).items() if n}
        self.assertEqual(dict(counted), expected)

    def test_every_cell_is_a_place_id_and_nothing_else(self):
        """A cell is an int. A dict or a pair would be a count arriving by another door."""
        for row in board(THREE):
            for cell in row:
                self.assertIsInstance(cell, int)
                self.assertNotIsInstance(cell, bool)


class RowIsDieOne(unittest.TestCase):
    """**Without this the ruling's «row = die 1» cannot fail.** A transposed board renders perfectly
    and puts the wrong place under the rolled pair — the error the nested shape exists to make hard
    to write by accident — so the orientation is asserted rather than assumed.

    **And the assertion is guarded, because it passes for free more often than not** (the
    evaluator's catch, 2026-09-11). `(d1, d2)` and `(d2, d1)` share a sum and sit close together in
    `OUTCOMES`, so they usually land inside one place's run: on this fixture only **6 of the 30**
    non-double cells hold different places under transposition, and on a one-place pool every cell
    is the same id and the board IS its own transpose — legally, because one shop is certain. So
    «the board is not its own transpose» is false as a general claim and is not asserted here. What
    is asserted is the orientation at coordinates that can actually tell the difference, and the
    precondition fails loudly rather than letting the check pass vacuously.
    """

    @staticmethod
    def _telling_pairs(cells):
        """`(die1, die2)` where the transposed cell holds a different place — the only coordinates
        at which orientation is observable. Doubles are excluded: there the transposed cell is the
        same cell, so the check is vacuous by construction."""
        return [(d1, d2) for d1 in range(1, 7) for d2 in range(1, 7)
                if d1 != d2 and cells[d1 - 1][d2 - 1] != cells[d2 - 1][d1 - 1]]

    def test_this_fixture_can_tell_row_major_from_column_major(self):
        """The precondition, as its own line so a fixture change reports the real reason."""
        telling = self._telling_pairs(board(THREE))
        self.assertTrue(telling,
                        "no coordinate on this board distinguishes row-major from column-major, so "
                        "the orientation test below would pass whatever the code did. Choose "
                        "weights whose table is asymmetric — do not delete the check.")

    def test_row_index_is_die_one_where_that_is_observable(self):
        """Pinned against `place_for`, whose argument order is `(die1, die2)` by its own signature,
        and only at coordinates the precondition above proved can fail."""
        table = build(THREE)
        cells = board(THREE)
        telling = self._telling_pairs(cells)
        self.assertTrue(telling, "precondition unmet — see the test above")
        for die1, die2 in telling:
            self.assertEqual(cells[die1 - 1][die2 - 1], place_for(table, die1, die2),
                             "board[{0}][{1}] should be the place for die1={2}, die2={3}"
                             .format(die1 - 1, die2 - 1, die1, die2))
            self.assertEqual(cells[die2 - 1][die1 - 1], place_for(table, die2, die1))

    def test_a_one_place_pool_is_symmetric_and_that_is_correct(self):
        """The case that would have gone red under «not its own transpose». One shop is certain, so
        all 36 cells hold it and the board equals its transpose. Kept as a test rather than as a
        comment, because the next person to tighten this file needs to meet it."""
        cells = board(weights(**{"10": "1"}))
        self.assertEqual({place for row in cells for place in row}, {10})
        transposed = tuple(tuple(cells[r][c] for r in range(6)) for c in range(6))
        self.assertEqual(cells, transposed)
        self.assertEqual(self._telling_pairs(cells), [])


class TheDiceOrderIsNotTheSlotOrder(unittest.TestCase):
    """Slots run by `(sum, die1, die2)`; a board runs by die. Conflating them is the other way to
    get a plausible wrong picture, so the difference is asserted rather than described."""

    def test_a_flat_reading_of_the_board_is_not_the_slot_table(self):
        flat = tuple(cell for row in board(THREE) for cell in row)
        self.assertNotEqual(flat, build(THREE))

    def test_but_both_hold_the_same_places_in_the_same_quantities(self):
        flat = Counter(cell for row in board(THREE) for cell in row)
        self.assertEqual(flat, Counter(build(THREE)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
