#!/usr/bin/env python3
"""D88's retrieval prompt, tested with no model, no network and no database.

    python3 app/api/tests/test_classify_rag.py

What is worth asserting here is the *shape of the experiment*, not whether cribs help — that
question belongs to an evaluation round against the frozen set, and no unit test can answer it.

Four things, and each one is a way the experiment could quietly stop measuring retrieval:

1. **The examples reach the prompt**, nearest first, as 「名稱：類別」 lines, above the ladder
   and below the category list. A crib that never rendered would produce a round scoring v3
   under a v5 filename.
2. **The base is v3, not v4.** v4's three additions measurably lost (qwen 51.0→50.0, gemma
   51.5→49.5), so the retrieval prompt is stacked on the better base — asserted by the v4-only
   sentences being absent, because a copy-paste from the wrong version is exactly the mistake
   that reads as a win.
3. **Validation is the shipped one.** `classify_name_rag` refuses what `classify_name`
   refuses, and stamps `RAG_PROMPT_VERSION` on every outcome — D39's condition 2 must not be
   softened by the branch that has examples.
4. **`gemini --rag` is refused before anything else happens.** The crib is the owner's gold
   labels and gold does not leave this machine (D88), so the refusal is argv-level and costs
   no key read, no network and no database.
5. **`--embed` names a cell of the matrix and the file name follows it.** D88's amendment,
   2026-08-17: `bge` writes the *existing* `round_<name>_v5-rag-2026-08-15.json`, because the
   three rounds already scored under that name are the bge column and re-running them would
   buy nothing; every other embedder appends its key. An unknown key is refused at argv, for
   the same reason an unknown candidate is — a round is a measurement of one named model.

6. **`--k` names the third axis and the file name follows it too.** M10, 2026-08-17: k=5 writes
   the *existing* name (every round on disk was retrieved at five), any other k appends `_k<k>`
   after the embedder, `rag.k` is the real k, and out-of-range or non-integer k is refused at
   argv rather than clamped — a clamped k would put a number in the file that the command never
   asked for.

Import discipline, same rule as `test_evaluate_score.py`: nothing reached from here may pull
SQLAlchemy at import time. The host Python has none, and D88's store is imported by
`run_round` inside the `--rag` branch alone for exactly that reason.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.classify import (  # noqa: E402
    CATEGORIES,
    NO_SIGNAL,
    Classified,
    NoSignal,
    PROMPT_VERSION,
    RAG_PROMPT_VERSION,
    Refused,
    build_rag,
    classify_name_rag,
)
from upto.classify.embed import EMBED_MODELS  # noqa: E402
from upto.classify.prompt import INSTRUCTION, RAG_INSTRUCTION  # noqa: E402
from upto.evaluate import run_round  # noqa: E402

# Five neighbours in the shape `examples.nearest` returns them, nearest first: name, label,
# subtype. Every subtype is None because the frozen set carries none (0018) — the
# subtype-bearing branch is exercised separately below, against a synthetic crib.
EXAMPLES = [
    ("阿明麵店", "麵食", None),
    ("老捌麻辣食堂", "火鍋", None),
    ("春水堂人文茶館", "咖啡飲料", None),
    ("薔薇廳", "其他", None),
    ("旨王開發有限公司", NO_SIGNAL, None),
]


def answering(reply):
    return lambda prompt: reply


class TestTheRagPrompt(unittest.TestCase):
    def test_every_example_is_rendered_with_its_label(self):
        text = build_rag("一階堂", EXAMPLES)
        for name, label, _subtype in EXAMPLES:
            self.assertIn(f"{name}：{label}", text)

    def test_a_subtype_is_printed_beside_the_label(self):
        # 0018's case-book column: D38's ten do not change, and a finer tag rides along in
        # the crib alone. Synthetic, because the frozen set has no subtypes yet — this is the
        # branch that must already work when the first case book arrives.
        text = build_rag("某店", [("清心福全", "咖啡飲料", "手搖飲"), ("阿明麵店", "麵食", None)])
        self.assertIn("清心福全：咖啡飲料（手搖飲）", text)
        self.assertIn("阿明麵店：麵食", text)
        self.assertNotIn("阿明麵店：麵食（", text)

    def test_a_two_element_example_still_renders(self):
        # The frozen set's shape today; a caller that has no subtype column must not have to
        # invent one.
        self.assertIn("阿明麵店：麵食", build_rag("某店", [("阿明麵店", "麵食")]))

    def test_the_layer_is_never_printed(self):
        # Asymmetry with the subtype, and it is the ruling: a subtype is a fact about the
        # shop, a layer is how the score is read.
        text = build_rag("某店", EXAMPLES)
        for layer in ("sign", "brand", "registered", "招牌", "登記"):
            self.assertNotIn(layer, text[text.index("參考例") : text.index("判斷順序")])

    def test_the_examples_keep_the_order_they_were_retrieved_in(self):
        # Nearest first, and the prompt must not reorder them: the model reads top-down and
        # the retrieval order is the only ranking this design offers it.
        text = build_rag("一階堂", EXAMPLES)
        positions = [text.index(example[0]) for example in EXAMPLES]
        self.assertEqual(positions, sorted(positions))

    def test_the_examples_sit_between_the_category_list_and_the_ladder(self):
        text = build_rag("一階堂", EXAMPLES)
        self.assertLess(text.index("類別（只能是下列其中一個）"), text.index("參考例"))
        self.assertLess(text.index("參考例"), text.index("判斷順序"))

    def test_the_asked_name_is_the_last_thing_in_the_prompt(self):
        text = build_rag("一階堂", EXAMPLES)
        self.assertTrue(text.endswith("店名：一階堂\n類別："), repr(text[-40:]))

    def test_no_examples_still_builds(self):
        # A name whose every neighbour was excluded is a legitimate row, not a crash: the
        # prompt degrades to v3 rather than refusing to be built.
        text = build_rag("一階堂", [])
        self.assertIn("判斷順序", text)
        self.assertIn("店名：一階堂", text)

    def test_the_whole_category_list_is_offered(self):
        text = build_rag("某店", EXAMPLES)
        for value in CATEGORIES:
            self.assertIn(value, text)
        self.assertIn(NO_SIGNAL, text)

    def test_the_ladder_is_v3s_and_in_order(self):
        text = build_rag("某店", EXAMPLES)
        ladder = text[text.index("判斷順序") :]
        positions = [ladder.index(step) for step in ("自稱", "主食形式", "菜系", "其他")]
        self.assertEqual(positions, sorted(positions), "the ladder is out of order")

    def test_the_rag_base_diverges_from_the_plain_one_but_the_drinks_rule_is_shared(self):
        """**Amended 2026-08-30 (v7), and the amendment is the point.**

        This test used to assert that 「主要賣的是飲品」 was **absent** from `RAG_INSTRUCTION` —
        it was in the group of three v4 additions the RAG base deliberately skipped. Two of those
        three were skipped on purpose and still are. **The drinks rule was not: it was collateral,
        and this test pinned the loss in place.** Every RAG round and the entire city backfill ran
        without it while 1,972 drinks-shaped names sat in `其他`, and the assertion here is why
        nobody found it by reading the file — the file was *asserted* to look that way.

        So: the two prompts still genuinely diverge (asserted below, so this file cannot start
        aliasing one to the other), and the drinks rule is now in **both**.
        """
        for v4_only in ("忽略名稱裡的分店資訊", "宴會館"):
            self.assertIn(v4_only, INSTRUCTION, "v4's text moved; this test needs re-deriving")
            self.assertNotIn(v4_only, RAG_INSTRUCTION)
        for shared in ("主要賣的是飲品", "素食", "台菜", "便利商店"):
            self.assertIn(shared, INSTRUCTION, shared)
            self.assertIn(shared, RAG_INSTRUCTION, shared)

    def test_the_two_versions_are_different_strings(self):
        self.assertNotEqual(RAG_PROMPT_VERSION, PROMPT_VERSION)


class TestValidationIsUnchanged(unittest.TestCase):
    def test_a_clean_answer_is_taken_and_stamped_with_the_rag_version(self):
        result = classify_name_rag("一階堂", answering("日式"), EXAMPLES)
        self.assertIsInstance(result, Classified)
        self.assertEqual(result.category, "日式")
        self.assertEqual(result.prompt_version, RAG_PROMPT_VERSION)

    def test_the_sentinel_is_still_its_own_outcome(self):
        result = classify_name_rag("旨王開發有限公司", answering(NO_SIGNAL), EXAMPLES)
        self.assertIsInstance(result, NoSignal)
        self.assertEqual(result.prompt_version, RAG_PROMPT_VERSION)

    def test_a_near_miss_is_refused_not_mapped(self):
        result = classify_name_rag("一階堂", answering("拉麵"), EXAMPLES)
        self.assertIsInstance(result, Refused)
        self.assertEqual(result.raw, "拉麵")
        self.assertEqual(result.prompt_version, RAG_PROMPT_VERSION)

    def test_garbage_is_refused(self):
        for raw in ("這家店看起來像是賣麵的", "", "？"):
            with self.subTest(raw=raw):
                self.assertIsInstance(
                    classify_name_rag("某店", answering(raw), EXAMPLES), Refused
                )

    def test_noise_around_a_valid_answer_is_still_stripped(self):
        result = classify_name_rag("某店", answering("「早餐」。"), EXAMPLES)
        self.assertIsInstance(result, Classified)
        self.assertEqual(result.category, "早餐")

    def test_an_empty_name_never_reaches_the_model(self):
        def explode(prompt):
            raise AssertionError("the model was asked about an empty name")

        self.assertIsInstance(classify_name_rag("   ", explode, EXAMPLES), Refused)

    def test_the_examples_actually_reach_the_model(self):
        seen = []
        classify_name_rag("一階堂", lambda prompt: seen.append(prompt) or "日式", EXAMPLES)
        self.assertIn("阿明麵店：麵食", seen[0])


class TestTheRunnerRefusesGemini(unittest.TestCase):
    """D88: the crib is the owner's gold, and gold does not leave this machine."""

    def test_gemini_with_rag_exits_two(self):
        def explode(*_args, **_kwargs):
            raise AssertionError("the refusal happened after something expensive")

        original = run_round.build_candidate
        run_round.build_candidate = explode
        try:
            self.assertEqual(run_round.main(["gemini", "--rag"]), 2)
            self.assertEqual(run_round.main(["--rag", "gemini"]), 2)
            # The second axis does not open a door the first one closed: whichever embedder is
            # named, the crib is still the owner's gold and still does not leave this machine.
            for key in EMBED_MODELS:
                self.assertEqual(run_round.main(["gemini", "--rag", "--embed", key]), 2, key)
            self.assertEqual(run_round.main(["gemini", "--rag", "--embed=arctic"]), 2)
        finally:
            run_round.build_candidate = original

    def test_gemini_without_rag_is_still_reached(self):
        # The refusal must be about `--rag` and not about the candidate: a plain gemini round
        # is the hosted baseline and still runs.
        reached = []
        original = run_round.build_candidate
        run_round.build_candidate = lambda name: reached.append(name) or (_ for _ in ()).throw(
            run_round.UsageError("stopped here on purpose")
        )
        try:
            self.assertEqual(run_round.main(["gemini"]), 2)
        finally:
            run_round.build_candidate = original
        self.assertEqual(reached, ["gemini"])

    def test_an_unknown_flag_is_still_a_usage_error(self):
        self.assertEqual(run_round.main(["qwen", "--nope"]), 2)

    def test_the_rag_round_has_its_own_filename(self):
        plain = run_round.round_path("qwen")
        retrieved = run_round.round_path("qwen", RAG_PROMPT_VERSION)
        self.assertNotEqual(plain, retrieved)
        self.assertIn(RAG_PROMPT_VERSION, retrieved)

    def test_nothing_here_pulled_sqlalchemy(self):
        # D88's example store reaches SQLAlchemy and the host Python has none. `run_round`
        # imports it inside the `--rag` branch alone, so a plain round stays runnable here.
        self.assertNotIn("sqlalchemy", sys.modules)


class TestTheEmbedderAxis(unittest.TestCase):
    """D88's amendment: 3 embedders × 3 generators, chosen at argv and carried by the file name."""

    def test_the_default_embedder_keeps_the_existing_filename(self):
        # The load-bearing one. `round_qwen_v5-rag-2026-08-15.json` and its two siblings are
        # already scored and committed as the bge column; a suffix here would orphan them.
        self.assertEqual(
            run_round.round_path("qwen", RAG_PROMPT_VERSION),
            run_round.round_path("qwen", RAG_PROMPT_VERSION, "bge"),
        )
        self.assertTrue(
            run_round.round_path("qwen", RAG_PROMPT_VERSION, "bge").endswith(
                f"round_qwen_{RAG_PROMPT_VERSION}.json"
            ),
            run_round.round_path("qwen", RAG_PROMPT_VERSION, "bge"),
        )

    def test_every_other_embedder_appends_its_key(self):
        for key in EMBED_MODELS:
            if key == run_round.DEFAULT_EMBED_KEY:
                continue
            path = run_round.round_path("gemma", RAG_PROMPT_VERSION, key)
            self.assertTrue(
                path.endswith(f"round_gemma_{RAG_PROMPT_VERSION}_{key}.json"), path
            )

    def test_every_cell_of_the_matrix_is_its_own_file(self):
        """The whole point of the naming rule: no two cells may share a file, or the second run
        would resume the first and score a candidate that never existed.

        **Derived, not counted, since 2026-08-31.** It asserted `9` for three generators and three
        embedders; rung 2 took the embedders to five and the assertion went red on arithmetic
        rather than on a defect. What must hold is that the count equals generators × embedders —
        a literal here has to be edited every time the slate grows, and an edited literal is one
        nobody re-derives.
        """
        generators = sorted(run_round.LOCAL_MODELS)
        paths = {
            run_round.round_path(generator, RAG_PROMPT_VERSION, key)
            for generator in generators
            for key in EMBED_MODELS
        }
        self.assertEqual(len(paths), len(generators) * len(EMBED_MODELS), sorted(paths))

    def test_the_prompt_version_does_not_move_with_the_embedder(self):
        # The embedder is a retrieval variable, not a prompt one: the prompt text is
        # byte-identical whichever model retrieved the cribs, so bumping the version would
        # claim a change that did not happen.
        self.assertEqual(build_rag("一階堂", EXAMPLES), build_rag("一階堂", EXAMPLES))
        for path in (run_round.round_path("qwen", RAG_PROMPT_VERSION, key)
                     for key in EMBED_MODELS):
            self.assertIn(RAG_PROMPT_VERSION, path)

    def test_an_unknown_embedder_is_refused_at_argv(self):
        def explode(*_args, **_kwargs):
            raise AssertionError("an unknown embedder reached something expensive")

        original = run_round.build_candidate
        run_round.build_candidate = explode
        try:
            for bad in ("bge-m3", "nomic", "", "BGE"):
                with self.subTest(key=bad):
                    self.assertEqual(run_round.main(["qwen", "--rag", "--embed", bad]), 2)
            # A flag with nothing after it is usage, not a silent fall back to the default.
            self.assertEqual(run_round.main(["qwen", "--rag", "--embed"]), 2)
        finally:
            run_round.build_candidate = original

    def test_embed_without_rag_is_a_usage_error(self):
        # A plain round retrieves nothing, so there is no embedding model in it to choose;
        # accepting the flag would write a file claiming a variable the run never used.
        def explode(*_args, **_kwargs):
            raise AssertionError("--embed was accepted without --rag")

        original = run_round.build_candidate
        run_round.build_candidate = explode
        try:
            self.assertEqual(run_round.main(["qwen", "--embed", "arctic"]), 2)
        finally:
            run_round.build_candidate = original

    def test_the_keys_are_pinned_to_model_strings(self):
        # Same rule as LOCAL_MODELS: a key that resolved differently on two days would produce
        # two scores belonging to neither.
        self.assertEqual(
            EMBED_MODELS,
            {
                "bge": "bge-m3",
                "qwen3e": "qwen3-embedding:0.6b",
                # Rung 2, 2026-08-31: the 4B sibling and a multilingual e5, both screened with
                # the prefix their model cards ask for.
                "qwen3e4b": "qwen3-embedding:4b-q8_0",
                "arctic": "snowflake-arctic-embed2",
                "e5": "zylonai/multilingual-e5-large",
            },
        )
        self.assertIn(run_round.DEFAULT_EMBED_KEY, EMBED_MODELS)

    def test_the_embedder_axis_pulled_no_sqlalchemy_either(self):
        # `upto.classify.embed` is standard library only, which is what lets `run_round` name
        # it at module level while `examples` stays inside the `--rag` branch.
        self.assertNotIn("sqlalchemy", sys.modules)


class Stubbed:
    """A candidate that answers instantly and offline. `model` is pinned like a real one."""

    model = "stub-model:test"

    def check(self) -> None:
        pass

    def ask(self, prompt: str, unload_after: bool = False, cold: bool = False) -> str:
        return "日式"


class TestTheKAxis(unittest.TestCase):
    """M10's k-scan: `--k` chosen at argv, carried by the file name, recorded as the real k.

    Every test here stops before `rag_examples` reaches the example store, or stubs it — the
    store is the one thing in this path that pulls SQLAlchemy, and the host Python has none.
    """

    def _parsed(self, argv):
        """Run `main` far enough to see the k it parsed, and not one step further."""
        seen = {}

        def capture(digest, embed_model, k=run_round.RAG_K):
            seen["k"] = k
            seen["embed_model"] = embed_model
            raise run_round.UsageError("stopped here on purpose")

        originals = (run_round.build_candidate, run_round.rag_examples)
        run_round.build_candidate = lambda name: Stubbed()
        run_round.rag_examples = capture
        try:
            status = run_round.main(argv)
        finally:
            run_round.build_candidate, run_round.rag_examples = originals
        return status, seen

    def test_the_default_k_is_five(self):
        # Both halves matter: the constant is 5, and a `--rag` round with no `--k` retrieves
        # with it rather than with whatever the store's own default happens to be.
        self.assertEqual(run_round.RAG_K, 5)
        status, seen = self._parsed(["qwen", "--rag"])
        self.assertEqual(status, 2)  # the stub stopped it; the parse already happened
        self.assertEqual(seen["k"], 5)

    def test_k_eight_is_accepted_and_reaches_the_retrieval(self):
        for argv in (["qwen", "--rag", "--k", "8"], ["qwen", "--rag", "--k=8"]):
            with self.subTest(argv=argv):
                status, seen = self._parsed(argv)
                self.assertEqual(status, 2)
                self.assertEqual(seen["k"], 8)

    def test_the_ends_of_the_range_are_accepted(self):
        for value, expected in (("1", 1), ("20", 20)):
            with self.subTest(k=value):
                _status, seen = self._parsed(["gemma", "--rag", "--k", value])
                self.assertEqual(seen["k"], expected)

    def test_k_outside_the_range_or_not_a_number_is_refused_at_argv(self):
        # Refused rather than clamped, and refused before retrieval: a clamped k would write a
        # `rag.k` the command never asked for.
        for bad in ("0", "21", "200", "-1", "3.5", "five", "", " "):
            with self.subTest(k=bad):
                status, seen = self._parsed(["qwen", "--rag", "--k", bad])
                self.assertEqual(status, 2)
                self.assertEqual(seen, {}, "a bad k reached the retrieval")

    def test_k_with_nothing_after_it_is_usage(self):
        status, seen = self._parsed(["qwen", "--rag", "--k"])
        self.assertEqual(status, 2)
        self.assertEqual(seen, {})

    def test_k_without_rag_is_a_usage_error(self):
        # `--embed`'s rule, unchanged: a plain round retrieves nothing, so there is no number
        # of examples in it to set.
        def explode(*_args, **_kwargs):
            raise AssertionError("--k was accepted without --rag")

        original = run_round.build_candidate
        run_round.build_candidate = explode
        try:
            self.assertEqual(run_round.main(["qwen", "--k", "8"]), 2)
            self.assertEqual(run_round.main(["qwen", "--k=8"]), 2)
        finally:
            run_round.build_candidate = original

    def test_k_five_keeps_the_existing_filename_for_every_embedder(self):
        # The compatibility half. The scored rounds on disk were all retrieved at five, so k=5
        # must keep writing exactly the name they already carry.
        for key in EMBED_MODELS:
            with self.subTest(key=key):
                self.assertEqual(
                    run_round.round_path("gemma", RAG_PROMPT_VERSION, key),
                    run_round.round_path("gemma", RAG_PROMPT_VERSION, key, 5),
                )
        self.assertTrue(
            run_round.round_path("gemma", RAG_PROMPT_VERSION, "bge", 5).endswith(
                f"round_gemma_{RAG_PROMPT_VERSION}.json"
            )
        )
        self.assertTrue(
            run_round.round_path("gemma", RAG_PROMPT_VERSION, "arctic", 5).endswith(
                f"round_gemma_{RAG_PROMPT_VERSION}_arctic.json"
            )
        )

    def test_any_other_k_is_suffixed_after_the_embedder(self):
        self.assertTrue(
            run_round.round_path("gemma", RAG_PROMPT_VERSION, "bge", 8).endswith(
                f"round_gemma_{RAG_PROMPT_VERSION}_k8.json"
            ),
            run_round.round_path("gemma", RAG_PROMPT_VERSION, "bge", 8),
        )
        self.assertTrue(
            run_round.round_path("gemma", RAG_PROMPT_VERSION, "arctic", 1).endswith(
                f"round_gemma_{RAG_PROMPT_VERSION}_arctic_k1.json"
            ),
            run_round.round_path("gemma", RAG_PROMPT_VERSION, "arctic", 1),
        )

    def test_every_cell_of_the_scan_is_its_own_file(self):
        # The naming rule's whole job: two cells sharing a file would make the second run
        # resume the first and score a candidate that never existed.
        paths = {
            run_round.round_path(generator, RAG_PROMPT_VERSION, key, k)
            for generator in ("qwen", "gemma", "llama")
            for key in EMBED_MODELS
            for k in (1, 3, 5, 8)
        }
        self.assertEqual(len(paths), 3 * len(EMBED_MODELS) * 4, sorted(paths))

    def test_gemini_is_still_refused_whatever_the_k(self):
        # The third axis does not open the door the first two are shut against: the crib is the
        # owner's gold and gold does not leave this machine (D88).
        def explode(*_args, **_kwargs):
            raise AssertionError("the refusal happened after something expensive")

        original = run_round.build_candidate
        run_round.build_candidate = explode
        try:
            for k in ("1", "3", "8"):
                with self.subTest(k=k):
                    self.assertEqual(
                        run_round.main(["gemini", "--rag", "--embed", "arctic", "--k", k]), 2
                    )
            self.assertEqual(run_round.main(["gemini", "--rag", "--k", "8"]), 2)
        finally:
            run_round.build_candidate = original

    # --- the round document, written for real into a temporary directory ------------------

    def _run_offline_round(self, argv, directory):
        """A whole round with a stubbed candidate and a stubbed crib: no model, no store."""
        originals = (run_round.build_candidate, run_round.rag_examples)
        previous = os.environ.get("UPTO_EVALUATION_DIR")
        os.environ["UPTO_EVALUATION_DIR"] = directory
        run_round.build_candidate = lambda name: Stubbed()
        run_round.rag_examples = lambda digest, embed_model, k=5: (
            lambda name: list(EXAMPLES)[:k]
        )
        try:
            return run_round.main(argv)
        finally:
            run_round.build_candidate, run_round.rag_examples = originals
            if previous is None:
                del os.environ["UPTO_EVALUATION_DIR"]
            else:
                os.environ["UPTO_EVALUATION_DIR"] = previous

    def test_the_document_records_the_real_k_and_the_name_carries_it(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                self._run_offline_round(["gemma", "--rag", "--embed", "arctic", "--k", "3"],
                                        directory),
                0,
            )
            written = sorted(os.listdir(directory))
            self.assertEqual(
                written, [f"round_gemma_{RAG_PROMPT_VERSION}_arctic_k3.json"], written
            )
            with open(os.path.join(directory, written[0]), encoding="utf-8") as handle:
                document = json.load(handle)
            self.assertEqual(
                document["rag"],
                {"embed_model": EMBED_MODELS["arctic"], "embed_key": "arctic", "k": 3},
            )
            self.assertEqual(document["prompt_version"], RAG_PROMPT_VERSION)

    def test_a_stored_round_refuses_to_be_continued_at_a_different_k(self):
        # The fourth pin, and the same rule as the embedder's: one round is one measurement.
        # k=5 is invisible in the file name by the compatibility rule, so the refusal has to
        # come from the metadata — here a file that says 5 while the command asks for 8.
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, f"round_qwen_{RAG_PROMPT_VERSION}_k8.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "candidate": "qwen",
                        "model": Stubbed.model,
                        "prompt_version": RAG_PROMPT_VERSION,
                        "rag": {"embed_model": EMBED_MODELS["bge"], "embed_key": "bge", "k": 5},
                        "rows": [],
                    },
                    handle,
                )
            self.assertEqual(self._run_offline_round(["qwen", "--rag", "--k", "8"], directory), 2)
            # Refused, not overwritten: the stored round is still the one that was there.
            with open(path, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["rag"]["k"], 5)

    def test_the_k_axis_pulled_no_sqlalchemy_either(self):
        self.assertNotIn("sqlalchemy", sys.modules)


class TheEmbedderPrefix(unittest.TestCase):
    """Rung 2 — every embedder gets the prefix it was trained with, and the crib records which.

    **The failure this guards is invisible to every other check.** Adding a prefix makes the same
    model string return different vectors; before revision 0041 the crib's key was
    `(embed_model, name)`, so a prefixed load would upsert over the bare rows and leave half the
    store in each convention. Both vectors are well-formed and the right width — `embed.py`'s own
    docstring says the dimension check cannot see it — and neighbours would then be ordered by
    nothing. It would also have overwritten the very baseline rung 2 compares against.
    """

    def test_every_model_in_the_map_has_a_prefix_and_a_kind(self):
        """**`""` is a real answer and a missing key is not.** `bge-m3` is trained without a
        prefix; a key absent from the map would be ambiguous between "no prefix" and "nobody has
        checked", which are different facts."""
        from upto.classify import embed
        self.assertEqual(set(embed.EMBED_MODELS), set(embed.EMBED_PREFIX))
        self.assertEqual(set(embed.EMBED_MODELS), set(embed.PREFIX_KIND))
        self.assertEqual(embed.EMBED_PREFIX["bge"], "")
        self.assertEqual(embed.PREFIX_KIND["bge"], "none")

    def test_the_kind_is_resolved_from_the_model_string(self):
        """The store keys on the model string, so the label must come from the same thing."""
        from upto.classify import embed
        self.assertEqual(embed.prefix_kind("snowflake-arctic-embed2"), "query")
        self.assertEqual(embed.prefix_kind("bge-m3"), "none")
        self.assertEqual(embed.prefix_kind("qwen3-embedding:4b-q8_0"), "instruct")

    def test_an_unrecorded_model_is_unknown_and_never_none(self):
        """`none` claims the text was sent bare; `unknown` says nobody knows. A crib mixing those
        is exactly what 0041 exists to make impossible."""
        from upto.classify import embed
        self.assertEqual(embed.prefix_kind("nobody/pulled-this"), "unknown")
        self.assertNotEqual(embed.prefix_kind("nobody/pulled-this"), "none")

    def test_the_prefix_is_applied_inside_embed_and_not_by_a_caller(self):
        """One place, so no caller can forget it and no two can disagree."""
        from upto.classify import embed as embed_module
        captured = {}

        def fake_fetch(request, timeout, what, backoff=None):
            captured["body"] = json.loads(request.data.decode())
            return {"embeddings": [[0.0] * 1024]}

        original = embed_module.fetch
        embed_module.fetch = fake_fetch
        try:
            embed_module.embed(["某店"], model="snowflake-arctic-embed2")
            prefixed = captured["body"]["input"]
            embed_module.embed(["某店"], model="bge-m3")
            bare = captured["body"]["input"]
        finally:
            embed_module.fetch = original
        self.assertEqual(prefixed, ["query: 某店"])
        self.assertEqual(bare, ["某店"], "bge is trained bare and must stay bare")

    def test_the_screen_names_the_convention_in_its_filename(self):
        """Two runs of one embedder differing only by prefix are two measurements; a name that
        cannot tell them apart is how the incumbent's baseline gets overwritten."""
        import pathlib
        source = pathlib.Path(
            os.path.dirname(os.path.abspath(__file__)), "..", "src", "upto", "evaluate",
            "knn_vote.py").read_text(encoding="utf-8")
        self.assertIn("round_knn-vote_{}-{}-k{}", source)
        self.assertIn("prefix_kind", source)
        self.assertNotIn('EMBED_KEY = "arctic"', source)


class TheRoundRunnerUnloadsToo(unittest.TestCase):
    """H43 — the round runner carries the same unload as the classifier, and did not.

    **The gap is the finding.** `classify/run.py` got `UNLOAD_EVERY` on 2026-08-30; a round is the
    same workload — one distinct prompt per row against a resident model — and nobody carried it
    across. A v7 gemma round then took `llama-server` from 1,966 to 5,856 MB in 77 requests and
    left the box with 130 MB. These tests exist so the two cannot drift apart again silently.
    """

    def test_both_runners_use_the_same_map_object(self):
        """**The same object, not the same number** — a round and a backfill waiting different
        amounts on one model service is the divergence nobody notices until one of them dies.

        The map moved to `classify/model.py` on 2026-08-31 precisely so this could be an import:
        `classify/run.py` pulls in SQLAlchemy, and this runner is host-side importable.
        """
        from upto.classify import model as model_module
        self.assertIs(run_round.unload_every, model_module.unload_every)

    def test_the_map_says_it_belongs_to_the_model_AND_the_prompt_version(self):
        """The rule that stops the next prompt edit — or the next model — from being a silent
        memory change. Both halves have already moved once."""
        import pathlib
        source = pathlib.Path(
            os.path.dirname(os.path.abspath(__file__)), "..", "src", "upto", "classify", "model.py"
        ).read_text(encoding="utf-8")
        for phrase in ("prompt", "v7", "re-measure", "model"):
            self.assertIn(phrase, source.lower())

    def test_the_row_after_an_unload_is_cold_and_the_boundary_is_exact(self):
        """**The pairing, and the off-by-one that would make it useless.**

        An unload fires on rows N, 2N…; the row that pays for it is the **next** one — N+1,
        2N+1 — because that is the request the model is not loaded for. Getting this one index
        wrong widens the retry on a row that never needed it and leaves the row that does with
        2.5 s against a 14.8 s load, which is the failure this fixes.
        """
        every = run_round.unload_every("gemma2:2b")
        unloads = [i for i in range(3 * every) if (i + 1) % every == 0]
        colds = [i for i in range(3 * every) if i > 0 and i % every == 0]
        self.assertEqual(unloads, [every - 1, 2 * every - 1, 3 * every - 1])
        self.assertEqual(colds, [every, 2 * every])
        # Each cold row is exactly one after an unload, and row 0 is never cold: the model is
        # loaded by the run's own first request, not by an unload.
        self.assertEqual([c - 1 for c in colds], unloads[:len(colds)])
        self.assertNotIn(0, colds)

    def test_the_cold_schedule_covers_the_measured_reload(self):
        """27 s of waiting against a 14.8 s reload, and the numbers are the assertion.

        **Longer timeouts would not have helped** — H52 says a cold model REFUSES rather than
        hangs, so what is needed is more attempts spread wider. This asserts the total, because a
        schedule that adds attempts without adding time would look like a fix and not be one.
        """
        from upto.classify import transport
        self.assertGreaterEqual(sum(transport.COLD_BACKOFF_S), 20.0)
        self.assertGreater(sum(transport.COLD_BACKOFF_S), sum(transport.BACKOFF_S) * 5)
        self.assertIs(run_round.COLD_BACKOFF_S, transport.COLD_BACKOFF_S,
                      "the round runner must not carry its own copy of the schedule")

    def test_every_candidate_accepts_both_keywords(self):
        """**A gemini round died at row 50 once for the missing keyword; this covers all four.**

        The loop hands `unload_after` or `cold` without knowing which candidate it holds, so a
        signature that differs is a crash on a rationed quota, hours in.
        """
        import inspect
        for name in list(run_round.LOCAL_MODELS) + ["gemini"]:
            with self.subTest(candidate=name):
                if name == "gemini":
                    ask = run_round.Gemini.ask
                else:
                    ask = run_round.build_candidate(name).ask
                params = inspect.signature(ask).parameters
                self.assertIn("unload_after", params, name)
                self.assertIn("cold", params, name)

    def test_the_window_is_keyed_on_the_frozen_row_not_the_run(self):
        """**A resumed round must unload on the same rows the first attempt would have.** Counting
        from the start of *this* run would drift the window by wherever the resume began, so two
        halves of one round would have different unload points and neither would match a re-run."""
        source = __import__("inspect").getsource(run_round)
        self.assertIn("(index + 1) % every", source)


class TheCandidateMap(unittest.TestCase):
    """The slate, and the one entry in it that is not a contender.

    Added 2026-08-30 with `qwen7b`, the post-launch classifier ladder's first rung. The map is
    where a candidate's model string lives, so a test here is what stops the CLI, the round file
    and the ladder from disagreeing about which model answered.
    """

    def test_qwen7b_is_a_candidate_and_its_model_string_is_pinned(self):
        """**Pinned as a string, not as a pattern.** The round file records this exact value and
        it is the only durable record of what answered; a test matching `startswith("qwen2.5:7b")`
        would go on passing after somebody swapped the quantisation, which is a different model
        with the same name."""
        self.assertIn("qwen7b", run_round.LOCAL_MODELS)
        self.assertEqual(run_round.LOCAL_MODELS["qwen7b"], "qwen2.5:7b-instruct-q4_K_M")

    def test_it_is_a_local_candidate_and_so_needs_no_new_branch(self):
        """The three axes are orthogonal to the candidate, and this is why the brief could say
        "`--rag --embed arctic --k 5` must work unchanged": every one of them is decided after
        the name is looked up, so adding a key to the map adds a candidate to all of them."""
        self.assertNotEqual("qwen7b", "gemini")
        self.assertEqual(run_round.build_candidate("qwen7b").model,
                         "qwen2.5:7b-instruct-q4_K_M")

    def test_the_slate_is_four_contenders_since_the_gate_was_amended(self):
        """**Four since 2026-08-30, and the previous version of this test said three.**

        It asserted `qwen7b` was excluded — correct under D64's original ~2.5 GB line, which was
        written for a 4 GB EC2 class. The owner amended D64 the same day: the resident gate is the
        VRAM of the machine the DAG calls (the GPU box, 8 GB; 7B + arctic measured 6.9 GB), and
        the model is chosen on measured lift with the 3× cost column beside it. So the exclusion
        is gone and the count is the thing to pin — a fifth key has to come here and argue.
        """
        self.assertEqual(sorted(run_round.LOCAL_MODELS), ["gemma", "llama", "qwen", "qwen7b"])

    def test_an_unknown_candidate_is_still_refused_by_name(self):
        """Adding a key must not turn the refusal into a fallback — and the message must NAME the
        new candidate, because `qwen7b` and `qwen70b` are one keystroke apart and the list is the
        only thing that tells a typist which one exists."""
        with self.assertRaises(run_round.UsageError) as caught:
            run_round.build_candidate("qwen70b")
        self.assertIn("qwen7b", str(caught.exception))


class TheHoldOutIsScopedToTheFrozenSet(unittest.TestCase):
    """D88's 2026-09-03 amendment (owner 「縮」) — and it has to hold at BOTH call sites.

    **Why this is a source-reading test rather than a behaviour one.** The ruling is a predicate
    inside one SQL string, and the two callers that depend on it — the round runner and the
    classifier — reach it through the same function. A behaviour test would pass while one
    caller had been quietly given its own query, which is exactly the shape H43 met when the
    round runner did not carry the classifier's unload. So this reads the files.

    **What the ruling says, in one line:** the asked name is held out of its own retrieval
    **only among rows that came from the frozen set**. A brand row with the asked name stays,
    because it is a published fact from D77 (`brand_labels.py`) rather than a row of the exam —
    D113's kind. Measured before the ruling: 93.7% of the brand-joined places are asked as
    exactly the brand, so the old rule made a `麥當勞` crib row invisible to every one of them.
    """

    def _source(self, *parts):
        import pathlib
        return pathlib.Path(
            os.path.dirname(os.path.abspath(__file__)), "..", "src", "upto", *parts
        ).read_text(encoding="utf-8")

    def test_the_predicate_is_scoped_by_source_and_not_by_name_alone(self):
        """The bare `name <> :exclude` is what the amendment removed. If it comes back, every
        brand row goes dark again and nothing else in the suite would notice."""
        source = self._source("classify", "examples.py")
        self.assertNotIn("and name <> :exclude", source)
        self.assertIn("not (source = :testset_source and name = :exclude)", source)

    def test_both_call_sites_go_through_the_one_function(self):
        """**The gap this closes.** Either caller could grow its own `select … from
        example_embedding`, and the ruling would then hold in one of them. Both must reach the
        store through `nearest`, so there is one predicate to rule on."""
        for parts in (("evaluate", "run_round.py"), ("classify", "run.py")):
            source = self._source(*parts)
            with self.subTest(caller="/".join(parts)):
                self.assertIn("exclude_name=name", source)
                self.assertNotIn("from example_embedding", source)

    def test_the_classifier_records_why_brand_rows_are_exempt(self):
        """The exemption is a loosening of a defence; the file that does it says so, or the next
        reader takes it for an oversight and 'fixes' it."""
        source = self._source("classify", "run.py")
        for phrase in ("D88", "2026-09-03", "brand", "source = 'testset'"):
            self.assertIn(phrase, source)

    def test_the_two_sources_are_constants_not_repeated_strings(self):
        """The predicate, the two loads and this test all have to spell them the same way.

        **Read, not imported** — `examples.py` pulls SQLAlchemy and this runner is host-side, a
        constraint its own module docstring states. Importing it here would fail as
        `ModuleNotFoundError`, which reads as a broken test rather than as the wrong tempo.
        """
        source = self._source("classify", "examples.py")
        self.assertIn('TESTSET = "testset"', source)
        self.assertIn('BRAND = "brand"', source)

    def test_each_load_deletes_only_its_own_source(self):
        """0042's other half. A frozen-set reload that wiped the brand rows would empty the crib
        the amendment exists for, and the next round would score against nothing and say so only
        as a number."""
        source = self._source("classify", "examples.py")
        # Two deletes — the frozen-set load's and the brand load's — and BOTH name a source.
        self.assertEqual(
            source.count("delete from example_embedding where embed_model = :model"), 2)
        self.assertEqual(
            source.count("and prefix_kind = :prefix_kind and source = :source"), 2)


class TheBrandCribIsAFactTable(unittest.TestCase):
    """`brand_labels.py` — D113's shape, and the limits that must stay stated.

    Host-side: the module is a dict and a docstring, no database and no SQLAlchemy.
    """

    def test_every_label_is_one_of_the_ruled_values(self):
        """D39's condition 2 — a value outside the list is rejected, never coerced. `法人` is
        legal here and is not one of D38's thirteen: it is the decided absence (D79), and the
        nine supermarkets plus 美廉社 carry it because rule 0 says a 超市 is not a food shop."""
        from upto.classify.brand_labels import BRAND_LABELS
        from upto.classify.categories import CATEGORIES
        allowed = set(CATEGORIES) | {"法人"}
        for name, (label, _company) in BRAND_LABELS.items():
            with self.subTest(brand=name):
                self.assertIn(label, allowed)

    def test_every_row_carries_the_company_it_was_published_under(self):
        """The basis. 0042's CHECK refuses a brand row with an empty `source_ref`, and this is
        the same rule one layer up, where it can be read."""
        from upto.classify.brand_labels import BRAND_LABELS
        for name, (_label, company) in BRAND_LABELS.items():
            with self.subTest(brand=name):
                self.assertTrue(company.strip())

    def test_the_teachers_are_named_in_full(self):
        """H68 — org, tag and version, never a nickname. The record's older pair reads
        «Fable 5 + Gemini» and this draft was Opus 5, so that string here would be false."""
        from upto.classify.brand_labels import BRAND_LABELED_BY
        for part in ("claude-opus-5[1m]", "gemini-3.5-flash-lite", "owner"):
            self.assertIn(part, BRAND_LABELED_BY)

    def test_the_source_carries_no_hotpot_no_bbq_no_taicai(self):
        """**A limit of D77's list, asserted so a later reader does not expect the crib to help
        those three.** If a future publication adds one, this test fails and the limit comes out
        of the report — which is the right way round."""
        from upto.classify.brand_labels import BRAND_LABELS
        labels = {label for label, _ in BRAND_LABELS.values()}
        for absent in ("火鍋", "燒烤", "台菜"):
            self.assertNotIn(absent, labels)

    def test_the_digest_covers_the_labels_and_not_only_the_names(self):
        """A crib goes stale when what it TEACHES changes. A digest over names alone would call
        an amended label current, and a round would score against a crib its report misdescribes.
        """
        import hashlib
        from upto.classify import brand_labels
        before = brand_labels.BRAND_LABELS
        payload = "\n".join(
            "{}\t{}".format(n, before[n][0]) for n in sorted(before))
        names_only = "\n".join(sorted(before))
        self.assertNotEqual(
            hashlib.sha256(payload.encode()).hexdigest(),
            hashlib.sha256(names_only.encode()).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
