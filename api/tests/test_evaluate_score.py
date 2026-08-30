#!/usr/bin/env python3
"""D64's scoring and the round runner's resume rule, tested with no model, network or database.

    python3 app/api/tests/test_evaluate_score.py

Three things are worth testing here and nothing else is:

1. **The arithmetic**, on a fabricated round small enough to count by hand — per-layer before
   pooled (D82's order), a refusal counted wrong rather than dropped, and every answer landing
   in the confusion cell it belongs to. A scorer that quietly discards the rows it cannot
   place would report a flattering number, which is the H23 shape this project keeps meeting.
2. **Gold is read fresh.** The round file carries the label it was asked under; the score must
   come from the current `testset_v1.json`. Amend a label and the same stored answer must flip.
3. **The resume rule**, as a pure function: a partial round continues, an answered row is never
   asked twice, and an answer about a name the set no longer carries is dropped rather than
   inherited.

Plus determinism of the rendering, because the report is committed: same inputs, same bytes,
and the row order of the input must not matter.

Import discipline: nothing here or under it may pull sqlalchemy at import time — the host
Python that runs this has none. `upto.evaluate.score` and `upto.evaluate.run_round` import
only the standard library and `upto.classify`, and that is part of what this file asserts.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.evaluate import run_round, score  # noqa: E402


def gold(i, name, layer, label):
    return {"registry_no": f"A-{i:09d}-00001-0", "name": name, "layer": layer, "label": label}


# Eight names, deliberately uneven across the layers so a per-layer table can be read by eye.
TESTSET = [
    gold(1, "阿明麵店", "sign", "麵食"),
    gold(2, "Q Burger松山南京五店", "sign", "早餐"),
    gold(3, "薔薇廳", "brand", "其他"),
    gold(4, "嘎兜商行", "registered", "法人"),
    gold(5, "旨王開發有限公司", "registered", "法人"),
    gold(6, "一階堂", "registered", "日式"),
    gold(7, "老捌麻辣食堂", "registered", "火鍋"),
    gold(8, "春水堂人文茶館", "brand", "咖啡飲料"),
]


def answered(i, answer, outcome="category"):
    row = dict(TESTSET[i])
    return {
        "i": i,
        "name": row["name"],
        "layer": row["layer"],
        "gold": row["label"],
        "answer": answer,
        "outcome": outcome,
    }


# The fabricated round: 6 right, 1 wrong-but-valid, 1 refused.
ROUND_ROWS = [
    answered(0, "麵食"),                        # sign     — right
    answered(1, "早餐"),                        # sign     — right
    answered(2, "咖啡飲料"),                    # brand    — wrong (gold 其他)
    answered(3, "法人", "no_signal"),           # register — right, the sentinel
    answered(4, "法人", "no_signal"),           # register — right
    answered(5, None, "refused"),               # register — refused, counts wrong
    answered(6, "火鍋"),                        # register — right
    answered(7, "咖啡飲料"),                    # brand    — right
]

ROUND = {
    "candidate": "qwen",
    "model": "qwen2.5:3b-instruct-q4_K_M",
    "prompt_version": "v3-2026-08-14",
    "testset": "testset_v1.json",
    "started_at": "2026-08-14T09:00:00+00:00",
    "finished_at": "2026-08-14T09:24:00+00:00",
    "rows": ROUND_ROWS,
}


def scored_counts(round_rows=None, gold_rows=None):
    scored, stale, unanswered = score.align(round_rows or ROUND_ROWS, gold_rows or TESTSET)
    return scored, stale, unanswered, score.tally(scored)


class TestArithmetic(unittest.TestCase):
    def test_per_layer_is_counted_separately(self):
        _, _, _, counts = scored_counts()
        # sign 2/2 · brand 1/2 · registered 3/4
        self.assertEqual(counts["per_layer"]["sign"], [2, 2])
        self.assertEqual(counts["per_layer"]["brand"], [1, 2])
        self.assertEqual(counts["per_layer"]["registered"], [3, 4])

    def test_pooled_is_the_sum_and_not_the_average_of_the_layers(self):
        # 6/8 = 75.0%; averaging the three layer rates would say 79.2% — a different claim,
        # and the reason D82 asks for per-layer first.
        _, _, _, counts = scored_counts()
        self.assertEqual(counts["pooled"], [6, 8])
        self.assertEqual(score.percent(*counts["pooled"]), "75.0%")

    def test_a_refusal_counts_wrong_and_is_never_dropped(self):
        _, _, _, counts = scored_counts()
        self.assertEqual(counts["invalid"], 1)
        # It stays in its layer's denominator: registered saw 4 names, not 3.
        self.assertEqual(counts["per_layer"]["registered"][1], 4)
        # And in its gold label's denominator, where it scores nothing.
        self.assertEqual(counts["per_label"]["日式"], [0, 1])

    def test_per_label_counts_the_gold_side(self):
        _, _, _, counts = scored_counts()
        self.assertEqual(counts["per_label"]["法人"], [2, 2])
        self.assertEqual(counts["per_label"]["其他"], [0, 1])
        self.assertEqual(counts["per_label"]["咖啡飲料"], [1, 1])
        self.assertEqual(counts["per_label"]["燒烤"], [0, 0])  # unseen, and shown as such
        self.assertEqual(score.percent(*counts["per_label"]["燒烤"]), "—")

    def test_every_scored_row_lands_in_exactly_one_confusion_cell(self):
        scored, _, _, counts = scored_counts()
        total = sum(sum(row.values()) for row in counts["confusion"].values())
        self.assertEqual(total, len(scored))


class TestConfusionPlacement(unittest.TestCase):
    def test_a_wrong_answer_lands_off_the_diagonal_in_the_right_cell(self):
        _, _, _, counts = scored_counts()
        # 薔薇廳: gold 其他, answered 咖啡飲料.
        self.assertEqual(counts["confusion"]["其他"]["咖啡飲料"], 1)
        self.assertEqual(counts["confusion"]["咖啡飲料"]["其他"], 0, "the matrix is transposed")

    def test_a_refusal_lands_in_the_invalid_column_of_its_gold_row(self):
        _, _, _, counts = scored_counts()
        self.assertEqual(counts["confusion"]["日式"][score.INVALID], 1)

    def test_invalid_is_a_column_and_never_a_gold_row(self):
        """Nothing in the frozen set is unreadable, so 無效 cannot be a gold label.

        **The size is derived, not written out, since D38 gained 便利商店 on 2026-08-30** — this
        assertion said 11×12 and went red on the eleventh value, which is the test doing its job
        and the number being the wrong thing to pin. What must hold is the *shape*: one row per
        label, one column per label plus 無效, and 無效 never a row. `label_space` can narrow both
        for an older set; `tally`'s defaults are today's, which is what this exercises.
        """
        _, _, _, counts = scored_counts()
        self.assertNotIn(score.INVALID, counts["confusion"])
        self.assertEqual(len(counts["confusion"]), len(score.LABELS))
        self.assertEqual(len(score.PREDICTED), len(score.LABELS) + 1)
        self.assertEqual(score.PREDICTED[-1], score.INVALID)

    def test_the_label_space_follows_the_set_and_not_todays_category_list(self):
        """A22 — a v5 round scored against v1 must not sprout a 便利商店 row.

        This is the assertion behind `label_space`: the tables describe the set that was scored.
        Before it, adding the eleventh value silently re-rendered every committed report with an
        empty extra row and column — same numbers, different shape, describing a category that
        did not exist when the round ran.
        """
        gold = [{"label": "麵食"}, {"label": "其他"}]
        scored = [{"predicted": "麵食"}, {"predicted": "其他"}]
        labels, predicted = score.label_space(gold, scored)
        self.assertEqual(labels, ("麵食", "其他"))
        self.assertEqual(predicted, ("麵食", "其他", score.INVALID))
        self.assertNotIn("便利商店", predicted)

    def test_a_label_the_set_cannot_measure_prints_insufficient_rows(self):
        """A22/v7 — 素食 is one row of 200, so its percentage would be 0% or 100%.

        **The number must not appear at all**, because a reader comparing two rounds on it would be
        comparing one coin flip against another and would not know it. M2 does the same thing for a
        source with one publication: *insufficient history*, never an interval derived from one.
        The pooled and per-layer figures are unaffected — every row still counts there.
        """
        counts = {"per_label": {"素食": [1, 1], "小吃": [20, 27]}, "per_layer": {}, "pooled": [0, 0],
                  "invalid": 0, "confusion": {}}
        rows = []
        for label in ("素食", "小吃"):
            got, seen = counts["per_label"][label]
            rows.append([label, str(seen), str(got),
                         "insufficient rows" if 0 < seen < score.MIN_SCOREABLE_ROWS
                         else score.percent(got, seen)])
        self.assertEqual(rows[0][3], "insufficient rows")
        self.assertEqual(rows[1][3], "74.1%")

    def test_the_threshold_is_named_and_not_a_literal(self):
        """It is a judgement, so it has to be findable and movable in one place."""
        self.assertEqual(score.MIN_SCOREABLE_ROWS, 5)

    def test_an_answer_outside_the_sets_labels_is_still_shown(self):
        """The other half: a v6 model answering 便利商店 against a v1 set gets a COLUMN, not a
        silent drop. A matrix that hides an answer is worse than one with an odd column in it."""
        gold = [{"label": "麵食"}]
        scored = [{"predicted": "便利商店"}]
        labels, predicted = score.label_space(gold, scored)
        self.assertEqual(labels, ("麵食",))
        self.assertEqual(predicted, ("麵食", "便利商店", score.INVALID))

    def test_an_answer_outside_the_list_is_invalid_even_if_the_outcome_says_otherwise(self):
        # Defence in depth: a hand-edited round file cannot smuggle 拉麵 into the matrix.
        rows = [dict(answered(0, "拉麵"))]
        _, _, _, counts = scored_counts(rows, TESTSET[:1])
        self.assertEqual(counts["confusion"]["麵食"][score.INVALID], 1)
        self.assertEqual(counts["pooled"], [0, 1])


class TestGoldIsReadFresh(unittest.TestCase):
    """The set is frozen against re-drawing, not against the owner's corrections."""

    def test_an_amended_label_changes_the_score_of_a_stored_answer(self):
        amended = [dict(row) for row in TESTSET]
        amended[2]["label"] = "咖啡飲料"  # 薔薇廳 re-ruled; the stored answer said 咖啡飲料
        _, _, _, counts = scored_counts(gold_rows=amended)
        self.assertEqual(counts["pooled"], [7, 8], "the score ignored the amended label")
        self.assertEqual(counts["per_layer"]["brand"], [2, 2])

    def test_the_drift_is_reported_rather_than_swallowed(self):
        amended = [dict(row) for row in TESTSET]
        amended[2]["label"] = "咖啡飲料"
        _, _, _, counts = scored_counts(gold_rows=amended)
        self.assertEqual(counts["drifted"], 1)

    def test_a_renamed_row_is_stale_and_is_not_scored_either_way(self):
        amended = [dict(row) for row in TESTSET]
        amended[2]["name"] = "薔薇廳咖啡"  # a different string; the stored answer is not about it
        scored, stale, _, counts = scored_counts(gold_rows=amended)
        self.assertEqual(len(stale), 1)
        self.assertEqual(len(scored), 7)
        self.assertEqual(counts["pooled"], [6, 7])

    def test_an_unanswered_row_is_reported_and_not_counted_wrong(self):
        scored, _, unanswered, counts = scored_counts(ROUND_ROWS[:5])
        self.assertEqual(unanswered, [5, 6, 7])
        # Five asked, four right — the three never asked are absent from the denominator
        # rather than folded in as failures, which would price silence as error.
        self.assertEqual(counts["pooled"], [4, 5])


class TestResumePoint(unittest.TestCase):
    """The runner's one piece of judgement, factored out so it can be tested without a model."""

    def test_a_finished_round_asks_nothing(self):
        kept, start = run_round.resume_point(ROUND_ROWS, TESTSET)
        self.assertEqual(start, len(TESTSET))
        self.assertEqual(len(kept), len(TESTSET))

    def test_a_partial_round_continues_at_the_first_unanswered_row(self):
        kept, start = run_round.resume_point(ROUND_ROWS[:5], TESTSET)
        self.assertEqual(start, 5)
        self.assertEqual([row["i"] for row in kept], [0, 1, 2, 3, 4])

    def test_an_empty_file_starts_at_zero(self):
        self.assertEqual(run_round.resume_point([], TESTSET), ([], 0))

    def test_a_gap_stops_the_prefix_rather_than_being_asked_around(self):
        # Rows 0,1 then 3: index 2 is missing, so the round re-asks from 2 and the stored
        # answer for 3 is dropped. The alternative — keeping it — makes `i` mean two things.
        kept, start = run_round.resume_point([ROUND_ROWS[0], ROUND_ROWS[1], ROUND_ROWS[3]], TESTSET)
        self.assertEqual(start, 2)
        self.assertEqual(len(kept), 2)

    def test_an_answer_about_an_amended_name_is_not_inherited(self):
        amended = [dict(row) for row in TESTSET]
        amended[1]["name"] = "Q Burger松山南京五店(新)"
        kept, start = run_round.resume_point(ROUND_ROWS, amended)
        self.assertEqual(start, 1, "an answer about a different string was inherited")
        self.assertEqual(len(kept), 1)

    def test_a_completed_row_is_never_asked_again(self):
        # The runner's loop is `range(start, len(gold))`; with every row answered it asks a
        # model that would explode if touched.
        def explode(prompt):
            raise AssertionError("an already-answered row was sent to the model")

        _, start = run_round.resume_point(ROUND_ROWS, TESTSET)
        for index in range(start, len(TESTSET)):
            run_round.answer_row(index, TESTSET[index], explode)


class TestRendering(unittest.TestCase):
    def report(self, round_doc=None, gold_rows=None):
        round_doc = round_doc or ROUND
        gold_rows = gold_rows or TESTSET
        scored, stale, unanswered = score.align(round_doc["rows"], gold_rows)
        return score.render(
            round_doc, scored, stale, unanswered, score.tally(scored),
            "testset_v1.json", "0" * 64,
        )

    def test_the_render_is_a_function_of_its_inputs(self):
        self.assertEqual(self.report(), self.report(), "two renders of one round disagree")

    def test_the_row_order_of_the_round_file_does_not_matter(self):
        shuffled = dict(ROUND, rows=list(reversed(ROUND_ROWS)))
        self.assertEqual(self.report(), self.report(shuffled))

    def test_no_clock_is_read_while_rendering(self):
        text = self.report()
        self.assertIn("2026-08-14T09:00:00+00:00", text)  # the round's own stamps, from the file
        self.assertNotIn("2026-08-15", text)

    def test_the_digest_is_printed_so_two_reports_are_comparable_or_visibly_not(self):
        self.assertIn("0" * 64, self.report())

    def test_the_headline_numbers_are_in_the_report(self):
        text = self.report()
        self.assertIn("75.0%", text)   # pooled
        self.assertIn("50.0%", text)   # brand
        self.assertIn("無效", text)

    def test_the_layer_table_comes_before_the_pooled_one(self):
        text = self.report()
        self.assertLess(text.index("by name layer"), text.index("Pooled"))

    def test_table_cells_are_padded_by_display_width(self):
        # The alignment claim, checked rather than eyeballed: every row of a table occupies
        # the same number of terminal cells. CJK glyphs are two cells wide, so a str-length
        # pad would look ragged exactly where this report is densest.
        blocks, current = [], []
        for line in self.report().splitlines():
            if line.startswith("|"):
                current.append(line)
            elif current:
                blocks.append(current)
                current = []
        if current:
            blocks.append(current)
        self.assertGreaterEqual(len(blocks), 4, "the report lost a table")
        for block in blocks:
            seen = {score.width(line) for line in block}
            self.assertEqual(len(seen), 1, f"ragged table: {block[0]} → widths {sorted(seen)}")

    def test_width_counts_a_cjk_glyph_as_two_cells(self):
        self.assertEqual(score.width("麵食"), 4)
        self.assertEqual(score.width("abc"), 3)


class TestFileRound(unittest.TestCase):
    """The one path that touches the disk: read a round file, write a report beside it."""

    def test_report_for_reads_the_round_and_the_set_from_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            round_path = os.path.join(directory, "round_qwen_v3-2026-08-14.json")
            set_path = os.path.join(directory, "testset_v1.json")
            with open(round_path, "w", encoding="utf-8") as handle:
                json.dump(ROUND, handle, ensure_ascii=False)
            with open(set_path, "w", encoding="utf-8") as handle:
                json.dump({"rows": TESTSET}, handle, ensure_ascii=False)
            text = score.report_for(round_path, set_path)
            self.assertIn("75.0%", text)
            self.assertIn(score.sha256_of(set_path), text)

    def test_the_real_frozen_set_loads_and_holds_only_known_labels(self):
        rows, digest = score.load_testset()
        self.assertEqual(len(rows), 200)
        self.assertEqual(len(digest), 64)
        for row in rows:
            self.assertIn(row["label"], score.LABELS, row["name"])
            self.assertIn(row["layer"], score.LAYERS, row["name"])

    def test_the_round_path_is_named_for_candidate_and_prompt_version(self):
        path = run_round.round_path("gemini", "v9-2026-01-01")
        self.assertTrue(path.endswith("round_gemini_v9-2026-01-01.json"), path)
        self.assertEqual(os.path.basename(os.path.dirname(path)), "evaluation")

    def test_the_evaluation_directory_is_found_at_the_repository_root(self):
        with tempfile.TemporaryDirectory() as directory:
            deep = os.path.join(directory, "app", "api", "src", "upto", "evaluate")
            os.makedirs(deep)
            os.makedirs(os.path.join(directory, "doc"))
            self.assertEqual(
                run_round.evaluation_dir(deep), os.path.join(directory, "evaluation")
            )


class TestImportDiscipline(unittest.TestCase):
    def test_nothing_here_pulled_sqlalchemy(self):
        # The host Python running this file has no sqlalchemy; importing it at module level
        # anywhere under upto.evaluate.score would make this suite unrunnable on the host,
        # which is the one property that keeps it cheap enough to run every time.
        self.assertNotIn("sqlalchemy", sys.modules)


if __name__ == "__main__":
    unittest.main(verbosity=2)
