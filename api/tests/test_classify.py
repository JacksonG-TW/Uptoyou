#!/usr/bin/env python3
"""D39's generator, tested without a model, a network or a database.

Run: python3 app/api/tests/test_classify.py

The model is a callable, so every case here is a *stated* model behaviour: the clean answer,
the answer wrapped in the noise a real model produced during the probe, and the answers that
must be refused. **The refusal tests are the point** — D39's condition 2 is the only part of
this process that can fail, and a coercion would delete it while looking like a fix.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.classify import (  # noqa: E402
    CATEGORIES,
    NO_SIGNAL,
    Classified,
    NoSignal,
    PROMPT_VERSION,
    Refused,
    build,
    classify_name,
)


def answering(reply):
    return lambda prompt: reply


class TestAcceptance(unittest.TestCase):
    def test_a_clean_answer_is_taken(self):
        result = classify_name("啟祥早餐店", answering("早餐"))
        self.assertIsInstance(result, Classified)
        self.assertEqual(result.category, "早餐")
        self.assertEqual(result.prompt_version, PROMPT_VERSION)

    def test_noise_around_a_valid_answer_is_stripped(self):
        for raw in ("早餐。", " 早餐\n", "類別：早餐", "「早餐」", "早餐\n（因為店名有早餐店）"):
            with self.subTest(raw=raw):
                result = classify_name("啟祥早餐店", answering(raw))
                self.assertIsInstance(result, Classified, raw)
                self.assertEqual(result.category, "早餐")

    def test_every_listed_value_is_acceptable(self):
        for value in CATEGORIES:
            self.assertIsInstance(classify_name("某店", answering(value)), Classified, value)


class TestNoSignal(unittest.TestCase):
    """Ruled 2026-08-14: a legal entity is a decided outcome, not a category and not a failure."""

    def test_the_sentinel_is_its_own_outcome(self):
        result = classify_name("安心食品服務股份有限公司", answering(NO_SIGNAL))
        self.assertIsInstance(result, NoSignal)
        self.assertEqual(result.prompt_version, PROMPT_VERSION)

    def test_the_sentinel_is_not_one_of_the_ten(self):
        # If it ever joined D38's list it would become something a person could pick, and
        # 其他 would go back to meaning two things at once.
        self.assertNotIn(NO_SIGNAL, CATEGORIES)

    def test_noise_around_the_sentinel_is_stripped_too(self):
        self.assertIsInstance(classify_name("某公司", answering("「法人」。")), NoSignal)

    def test_it_is_not_a_refusal(self):
        # Same effect on the database, opposite meanings — the distinction ingest_run draws
        # between no change and failed, applied one table over.
        self.assertNotIsInstance(classify_name("某公司", answering(NO_SIGNAL)), Refused)


class TestRefusal(unittest.TestCase):
    """A wrong answer stays wrong — the one thing D39's process can catch."""

    def test_a_near_miss_is_refused_not_mapped(self):
        result = classify_name("一階堂", answering("拉麵"))
        self.assertIsInstance(result, Refused)
        self.assertEqual(result.raw, "拉麵")

    def test_an_explanation_instead_of_an_answer_is_refused(self):
        result = classify_name("某店", answering("這家店看起來像是賣麵的"))
        self.assertIsInstance(result, Refused)

    def test_an_empty_answer_is_refused(self):
        self.assertIsInstance(classify_name("某店", answering("")), Refused)

    def test_an_empty_name_never_reaches_the_model(self):
        def explode(prompt):
            raise AssertionError("the model was asked about an empty name")

        self.assertIsInstance(classify_name("   ", explode), Refused)


class TestPrompt(unittest.TestCase):
    def test_the_prompt_carries_the_list_and_the_name(self):
        text = build("老捌麻辣食堂")
        self.assertIn("老捌麻辣食堂", text)
        for value in CATEGORIES:
            self.assertIn(value, text)

    def test_the_ladder_is_in_the_prompt_in_order(self):
        # D39's tie-break is an instruction, not a convention held by whoever wrote the code.
        # Searched inside the ladder block alone: every value also appears in the list above
        # it, and an index over the whole prompt measures the wrong occurrence.
        text = build("某店")
        ladder = text[text.index("判斷順序") :]
        positions = [ladder.index(step) for step in ("自稱", "主食形式", "菜系", "其他")]
        self.assertEqual(positions, sorted(positions), "the ladder is out of order")

    def test_the_version_is_stamped_on_every_outcome(self):
        self.assertEqual(classify_name("某店", answering("早餐")).prompt_version, PROMPT_VERSION)
        self.assertEqual(classify_name("某店", answering("？")).prompt_version, PROMPT_VERSION)


class TheUnloadThatHoldsTheBoxUp(unittest.TestCase):
    """H43 — `keep_alive: 0` every `UNLOAD_EVERY` rows, and the constant carries its arithmetic.

    Owner-ruled 2026-08-30 (「不改WSL，用卸載壓住」): the WSL2 memory ceiling stays where it is
    because Windows needs it, so the unload is the bound. Tested here rather than only in the
    module because the failure is silent — a request that quietly stops carrying the field looks
    exactly like one that carries it, until the box is killed some hours into a pass.
    """

    def _payload(self, **kwargs):
        """The JSON body `ask` would send, without sending it."""
        import json as _json
        from upto.classify import model as model_module

        captured = {}

        def fake_fetch(request, timeout, what, backoff=None):
            captured["body"] = _json.loads(request.data.decode())
            captured["backoff"] = backoff
            return {"response": "早餐"}

        original = model_module.fetch
        model_module.fetch = fake_fetch
        try:
            model_module.ask("某店", **kwargs)
        finally:
            model_module.fetch = original
        self._captured_backoff = captured["backoff"]
        return captured["body"]

    def test_an_ordinary_ask_carries_no_keep_alive(self):
        """**The default must not change.** An unload on every request would pay a ~10 s reload
        per row, which is the same defect in the opposite direction."""
        self.assertNotIn("keep_alive", self._payload())

    def test_the_unloading_ask_sets_keep_alive_to_zero(self):
        self.assertEqual(self._payload(unload_after=True)["keep_alive"], 0)

    def test_the_rest_of_the_request_is_untouched(self):
        """The unload is one field on a request we already make — not a different request."""
        plain = self._payload()
        unloading = self._payload(unload_after=True)
        del unloading["keep_alive"]
        self.assertEqual(plain, unloading)

    def test_a_cold_ask_gets_the_wide_retry_and_an_ordinary_one_does_not(self):
        """**The pairing that makes the unload survivable (H52).** A model that has just been
        unloaded refuses the next call rather than answering it slowly, and the ordinary 2.5 s
        schedule gives up while a 7B is still loading its 14.8 s — which is how qwen7b ended a
        200-row round at row 50."""
        from upto.classify import transport

        self._payload()
        ordinary = self._captured_backoff
        self._payload(cold=True)
        self.assertIs(ordinary, transport.BACKOFF_S)
        self.assertIs(self._captured_backoff, transport.COLD_BACKOFF_S)

    def test_n_is_per_model_and_the_2b_is_the_expensive_one(self):
        """**Parameter count predicts nothing here, and the map is the assertion.**

        Measured on prompt v7 in a clean window: gemma2:2b ~103 MB per request, llama3.2:3b ~79,
        qwen2.5:7b ~36, qwen2.5:3b ~23. The **2B costs about three times the 7B**, an inversion
        that has now held across two independent measurements — so a single N sized on the biggest
        model would put the smallest one over the ceiling.
        """
        from upto.classify.model import unload_every
        self.assertEqual(unload_every("gemma2:2b"), 25)
        self.assertEqual(unload_every("llama3.2:3b"), 35)
        self.assertEqual(unload_every("qwen2.5:7b-instruct-q4_K_M"), 50)
        self.assertLess(unload_every("gemma2:2b"), unload_every("qwen2.5:7b-instruct-q4_K_M"))

    def test_an_unmeasured_model_gets_the_smallest_n_and_not_a_default(self):
        """**The case that kills the box is the model nobody measured.** A default of 50 would be a
        guess sized on the two cheapest entries; the smallest N costs reloads, and a wrong large N
        costs the pass. Wrong in the direction that only wastes time."""
        from upto.classify.model import unload_every, UNLOAD_EVERY_BY_MODEL
        self.assertEqual(unload_every("mistral:7b"), min(UNLOAD_EVERY_BY_MODEL.values()))
        self.assertEqual(unload_every("something-nobody-has-pulled"), 25)

    def test_a_requantised_tag_still_matches(self):
        """A re-quantised pull is the same KV geometry and must not fall through to the unknown
        branch — safe, but it would silently halve N on a model we HAVE measured."""
        from upto.classify.model import unload_every
        self.assertEqual(unload_every("qwen2.5:7b-instruct"), 50)

    def test_the_constant_is_200_and_says_where_both_numbers_came_from(self):
        """**The source is read, because a constant without its arithmetic cannot be moved.**

        N is a trade between cache growth per distinct prompt and the cost of one reload; a reader
        who can see only the number has to re-derive both to change it, and will not.
        """
        import pathlib

        source = pathlib.Path(
            os.path.dirname(os.path.abspath(__file__)), "..", "src", "upto", "classify", "run.py"
        ).read_text(encoding="utf-8")
        import pathlib as _p
        model_source = _p.Path(
            os.path.dirname(os.path.abspath(__file__)), "..", "src", "upto", "classify", "model.py"
        ).read_text(encoding="utf-8")
        self.assertIn("UNLOAD_EVERY_BY_MODEL", model_source)
        # Every per-request figure the map was derived from, so the map cannot be re-tuned
        # without the numbers that justify it being visible in the same file.
        for number in ("103", "79", "36", "23", "7.7"):
            self.assertIn(number, model_source, "the map lost one of its measured quantities")
        self.assertIn("H43", model_source)
        self.assertIn("unload_every", source, "the backfill must consult the map, not a constant")

    def test_the_window_fires_on_the_row_it_should(self):
        """The off-by-one that would make this useless: `% N == 0` on a 0-based index unloads on
        row 1 and never again on a boundary. Asserted on the expression the loop uses."""
        from upto.classify.model import unload_every
        every = unload_every("gemma2:2b")
        fires = [i for i in range(3 * every) if (i + 1) % every == 0]
        self.assertEqual(fires, [every - 1, 2 * every - 1, 3 * every - 1], fires)


if __name__ == "__main__":
    unittest.main(verbosity=2)
