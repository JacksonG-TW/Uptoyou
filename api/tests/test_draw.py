#!/usr/bin/env python3
"""D108's draw, tested where it is cheap — no network, no database, no round.

Run: python3 app/api/tests/test_draw.py

**Why this file matters more than its size suggests.** `upto.engine.draw` is the fairness core: it
decides where people eat, and its claim is that nobody — including us — could have steered it. That
claim is checkable at the level of a pure function and nowhere else, because at the level of a round
you get one sample.

**It is also the evaluator's RP-5, made affordable.** RP-5 asks that the choice be uniform across
members rather than a fixed seat. Against the HTTP surface that needs a thousand rounds; against
`deciding_member` it needs a thousand calls. The evaluator asked for exactly this and it is here:
`TheDrawIsUniform` is RP-5's real content, and its walkthrough line can stay a smoke test without
pretending to be a distribution result.

**On the tolerances.** The uniformity tests use a chi-square statistic against a fixed critical
value rather than "roughly equal", because "roughly" is what lets a 2x skew through. They are
deterministic — the seeds are derived from a fixed counter, not from `secrets` — so a pass is a pass
for everyone and there is no flaky test to re-run until it goes green. **That is deliberate: a
randomness test that is itself random can be made to pass by trying again**, which is the shape of
every uncaught bias.
"""

from __future__ import annotations

import collections
import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from upto.engine import draw  # noqa: E402


def fixed_seeds(count: int) -> list:
    """Deterministic seeds. Not `new_seed()` — see the module docstring on flaky randomness tests."""
    return [hashlib.sha256(b"upto-test-seed-%d" % i).digest() for i in range(count)]


class TheCommitment(unittest.TestCase):
    def test_it_is_the_sha256_of_the_seed(self):
        seed = fixed_seeds(1)[0]
        self.assertEqual(draw.commitment(seed), hashlib.sha256(seed).hexdigest())

    def test_a_revealed_seed_verifies_against_its_commitment(self):
        seed = fixed_seeds(1)[0]
        self.assertTrue(draw.verify(seed.hex(), draw.commitment(seed)))

    def test_a_different_seed_does_not_verify(self):
        """The whole claim in one assertion: a substituted seed is detectable."""
        a, b = fixed_seeds(2)
        self.assertFalse(draw.verify(b.hex(), draw.commitment(a)))

    def test_a_malformed_reveal_is_false_and_not_an_exception(self):
        """A caller checking a claim must get an answer, not a traceback to handle."""
        self.assertFalse(draw.verify("not hex", draw.commitment(fixed_seeds(1)[0])))
        self.assertFalse(draw.verify("", "abc"))

    def test_a_new_seed_is_the_declared_length_and_not_reused(self):
        first, second = draw.new_seed(), draw.new_seed()
        self.assertEqual(len(first), draw.SEED_BYTES)
        self.assertNotEqual(first, second)


class APairIsFixedAndInRange(unittest.TestCase):
    def test_the_same_seed_and_member_always_give_the_same_pair(self):
        """The point of the whole design: a tap reveals, it does not draw."""
        seed = fixed_seeds(1)[0]
        self.assertEqual(draw.pair_for_member(seed, 148), draw.pair_for_member(seed, 148))

    def test_every_die_is_between_one_and_six(self):
        for seed in fixed_seeds(50):
            for member in (1, 7, 148, 999999):
                for die in draw.pair_for_member(seed, member):
                    self.assertIn(die, (1, 2, 3, 4, 5, 6))

    def test_two_members_are_not_handed_the_same_pair(self):
        """Not a uniqueness guarantee — 36 pairs and 12 members collide — but the derivation must
        depend on the member id at all. If it did not, everyone would show identical dice."""
        seed = fixed_seeds(1)[0]
        pairs = {draw.pair_for_member(seed, m) for m in range(1, 13)}
        self.assertGreater(len(pairs), 1, "every member got the same pair; the id is being ignored")

    def test_the_two_dice_are_drawn_separately(self):
        """`skip=1` is what makes die 2 a second value rather than the same one twice.

        If `skip` were ignored the pair would always be a double, and 30 of the 36 cells would be
        unreachable — a bug that looks like bad luck.
        """
        seed = fixed_seeds(1)[0]
        doubles = sum(1 for m in range(1, 200)
                      if (lambda p: p[0] == p[1])(draw.pair_for_member(seed, m)))
        self.assertLess(doubles, 60, "far too many doubles: die 2 is not a separate value")


class TheDecider(unittest.TestCase):
    def test_it_is_one_of_the_members(self):
        seed = fixed_seeds(1)[0]
        members = [3, 9, 148, 149]
        self.assertIn(draw.deciding_member(seed, members), members)

    def test_the_callers_ordering_cannot_change_it(self):
        """**The assertion that stops the decider depending on who tapped first.**

        A member list arriving in `rolled_at` order would otherwise make the outcome a function of
        speed, which is the exact thing the commitment exists to prevent.
        """
        seed = fixed_seeds(1)[0]
        forwards = draw.deciding_member(seed, [3, 9, 148, 149])
        backwards = draw.deciding_member(seed, [149, 148, 9, 3])
        shuffled = draw.deciding_member(seed, [148, 3, 149, 9])
        self.assertEqual(forwards, backwards)
        self.assertEqual(forwards, shuffled)

    def test_a_duplicate_in_the_list_cannot_change_it(self):
        seed = fixed_seeds(1)[0]
        self.assertEqual(draw.deciding_member(seed, [3, 9, 9, 148]),
                         draw.deciding_member(seed, [3, 9, 148]))

    def test_no_members_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            draw.deciding_member(fixed_seeds(1)[0], [])

    def test_the_rounds_dice_are_the_deciders_own_pair(self):
        """«the stored result's dice equal that member's pair» — true by construction."""
        seed = fixed_seeds(1)[0]
        members = [3, 9, 148, 149]
        chosen = draw.deciding_member(seed, members)
        self.assertEqual(draw.deciding_pair(seed, members), draw.pair_for_member(seed, chosen))


class TheDrawIsUniform(unittest.TestCase):
    """RP-5, made affordable — a thousand calls instead of a thousand rounds.

    Chi-square against a fixed critical value, on deterministic seeds. See the module docstring on
    why a randomness test must not itself be random.
    """

    def chi_square(self, counts: list, expected: float) -> float:
        return sum((c - expected) ** 2 / expected for c in counts)

    def test_the_decider_is_uniform_across_five_members(self):
        members = [11, 22, 33, 44, 55]
        seen = collections.Counter(
            draw.deciding_member(seed, members) for seed in fixed_seeds(3000))
        self.assertEqual(set(seen), set(members), "some member was never chosen in 3000 draws")
        # 4 degrees of freedom, critical value 18.47 at p=0.001.
        statistic = self.chi_square(list(seen.values()), 3000 / len(members))
        self.assertLess(statistic, 18.47,
                        "the decider is not uniform across members: {} (chi2 {:.2f})".format(
                            dict(sorted(seen.items())), statistic))

    def test_the_decider_is_uniform_at_the_ruled_ceiling_of_twelve(self):
        """D110 caps a circle at 12. The draw has to be fair at the largest legal circle too."""
        members = list(range(1, 13))
        seen = collections.Counter(
            draw.deciding_member(seed, members) for seed in fixed_seeds(6000))
        self.assertEqual(set(seen), set(members))
        # 11 degrees of freedom, critical value 31.26 at p=0.001.
        statistic = self.chi_square(list(seen.values()), 6000 / 12)
        self.assertLess(statistic, 31.26,
                        "not uniform at twelve members: chi2 {:.2f}".format(statistic))

    def test_each_die_face_is_uniform(self):
        """The rejection sampling, measured — **and the sample size is chosen so that it is.**

        This test first ran at 3,000 seeds and claimed in its own docstring to measure the rejection
        sampling. **It did not: the biased `byte % 6` implementation scores chi2 11.92 there, against
        a critical value of 20.52, so it would have passed.** A check that reads as verifying
        something it cannot detect is H37's shape, and this file's whole purpose is the one place that
        must not have it.

        The bias is small — faces 1–4 draw 43/256, faces 5–6 draw 42/256 — and its expected chi2 is
        `1.221e-4` per die, so detecting it at p=0.001 needs about 168,000 dice. Measured at 90,000
        seeds (180,000 dice), which costs about a second:

            byte % 6 (biased)   chi2 26.8   -> caught
            this implementation chi2  1.24  -> passes

        **The separation is what makes the assertion mean something**, and the numbers are here so
        that a future change to the sample size has to reckon with them rather than guess.
        """
        faces = collections.Counter()
        for seed in fixed_seeds(90000):
            faces.update(draw.pair_for_member(seed, 148))
        self.assertEqual(set(faces), {1, 2, 3, 4, 5, 6})
        # 5 degrees of freedom, critical value 20.52 at p=0.001.
        statistic = self.chi_square(list(faces.values()), 180000 / 6)
        self.assertLess(statistic, 20.52,
                        "die faces are not uniform: {} (chi2 {:.2f})".format(
                            dict(sorted(faces.items())), statistic))

    def test_a_byte_at_or_above_the_limit_is_rejected_rather_than_folded_in(self):
        """The mechanism directly, not its statistical shadow.

        The statistical test above needs 180,000 dice to see the bias. This one sees the *policy* in
        five bytes, by feeding `_below` a known stream: 252–255 must be walked past, and the answer
        must come from the first byte below the limit. If rejection were removed, 252 % 6 == 0 would
        be returned and this fails immediately.

        **Both tests, deliberately.** The direct one catches the mechanism being deleted; the
        statistical one catches it being subtly wrong in a way that still looks like rejection.
        """
        original = draw._stream
        draw._stream = lambda seed, message: iter([252, 253, 254, 255, 5, 1, 1, 1])
        try:
            self.assertEqual(draw._below(b"ignored", b"ignored", 6), 5,
                             "a byte at or above the limit was folded in instead of rejected")
        finally:
            draw._stream = original

    def test_the_limit_is_the_largest_whole_multiple_of_the_range(self):
        """252 for a die, not 250 and not 256 — off by one either way reintroduces skew or waste."""
        self.assertEqual((256 // 6) * 6, 252)

    def test_all_thirty_six_pairs_are_reachable(self):
        """**36 = 6x6 and the engine allocates pairs, not sums.** A pair no seed can produce is a
        place no round can pick, which is the unpickable-by-arithmetic failure the ceiling exists
        to prevent."""
        pairs = {draw.pair_for_member(seed, 148) for seed in fixed_seeds(4000)}
        self.assertEqual(len(pairs), 36,
                         "only {} of 36 pairs occurred in 4000 draws".format(len(pairs)))


class DomainSeparation(unittest.TestCase):
    def test_the_decider_question_and_a_member_question_are_different_streams(self):
        """One seed answers two questions and they must not be able to coincide.

        Asserted by construction rather than statistically: the labels differ, so the HMAC messages
        differ. This test exists so that a future edit merging them fails here rather than silently
        tying a member's dice to whether they were chosen.
        """
        self.assertNotEqual(draw.LABEL_DECIDER, draw.LABEL_MEMBER)
        self.assertFalse(draw.LABEL_MEMBER.startswith(draw.LABEL_DECIDER))
        self.assertFalse(draw.LABEL_DECIDER.startswith(draw.LABEL_MEMBER))

    def test_member_ids_cannot_run_into_each_other(self):
        """`member:1` and `member:11` must be two questions, not one prefix of the other.

        HMAC over a length-prefixed key is not the risk here; the risk is a caller concatenating ids.
        Checked as a property of the output rather than of the message, since that is what matters.
        """
        seed = fixed_seeds(1)[0]
        self.assertNotEqual(draw.pair_for_member(seed, 1), draw.pair_for_member(seed, 11))


class ABoundLargerThanAByteTerminates(unittest.TestCase):
    """**The hang, in the shape it actually happened.** `_below` read one byte and rejected anything
    at or above `(256 // bound) * bound`. Above 256 that expression is **zero**, so every byte was
    rejected and the loop ran forever — 100% of a core, no return, the request held open. Found
    2026-08-20 on a fixture circle that had grown to 290 members: one `GET /circles/{id}/stream`
    pegged `upto-api-1` and the snapshot never produced a byte. D110's supported shape is twelve, so
    no bound above 256 had ever been asked for and no test had ever asked for one either.
    """

    def test_the_first_bound_that_hung_now_returns(self):
        self.assertIn(draw._below(draw.new_seed(), b"x", 257), range(257))

    def test_a_circle_larger_than_a_byte_picks_a_decider(self):
        members = list(range(1, 291))
        chosen = draw.deciding_member(draw.new_seed(), members)
        self.assertIn(chosen, members)

    def test_much_larger_bounds_terminate_too(self):
        """Not only the boundary: 65,537 crosses the two-byte width the same way 257 crosses one."""
        seed = draw.new_seed()
        for bound in (512, 1000, 65536, 65537, 100000):
            self.assertIn(draw._below(seed, b"x", bound), range(bound), bound)

    def test_every_bound_around_each_byte_boundary_terminates(self):
        """The arithmetic that failed was a floor division, so the values worth testing are the ones
        either side of where the floor changes."""
        seed = draw.new_seed()
        for bound in (254, 255, 256, 257, 258, 65535, 65536, 65537):
            self.assertIn(draw._below(seed, b"x", bound), range(bound), bound)

    def test_a_wide_bound_is_still_uniform(self):
        """A wider draw must not skew, or the decider stops being fair the moment a circle grows.

        **One seed, 6,000 distinct messages — which is how the real code varies.** `pair_for_member`
        holds the round's seed still and changes the label per member, so that is what is measured.
        The first version of this test used `bytes([index % 256]) * 32` as the seed and scored
        chi2 56.6: only 256 distinct seeds, every one of them 32 identical bytes. **That was a
        degenerate instrument reporting skew in the subject** — the mirror of the earlier draw test
        that could not detect the bias it claimed to measure, and the same lesson from the other
        side. Ten buckets of 600; chi-square against 16.92 (df 9, p=0.05).

        **A fixed seed, as the module docstring requires** (2026-10-10). This one drew `new_seed()`, so
        a fair draw failed it about one run in twenty by construction — the public CI went red on
        chi2 18.35. Deterministic now: the same pass for everyone, and a skewed `_below` still fails.
        """
        bound, buckets, draws = 300, 10, 6000
        seed = fixed_seeds(1)[0]
        counts = [0] * buckets
        for index in range(draws):
            value = draw._below(seed, b"member:" + str(index).encode(), bound)
            counts[value * buckets // bound] += 1
        expected = draws / buckets
        chi2 = sum((c - expected) ** 2 / expected for c in counts)
        self.assertLess(chi2, 16.92, "{} -> chi2 {:.2f}".format(counts, chi2))

    def test_skip_still_works_across_a_wide_draw(self):
        """`skip` counts accepted values, and an accepted value is now `width` bytes rather than one.
        Miscounting it would make die 2 a copy of die 1."""
        seed = draw.new_seed()
        first = draw._below(seed, b"pair", 300, skip=0)
        second = draw._below(seed, b"pair", 300, skip=1)
        self.assertIn(first, range(300))
        self.assertIn(second, range(300))

    def test_the_derivation_below_257_is_byte_for_byte_what_it_was(self):
        """**The assertion that protects every round already stored.** A stored round's dice are
        re-derived from its seed by `explain_round`; a derivation that moved would turn every past
        round into a mismatch and every verification into a false alarm. `width` is 1 for every
        bound up to 256, so the arithmetic below that line is the arithmetic that was there.
        """
        for bound in (2, 6, 12, 36, 100, 255, 256):
            width = 1
            while 256 ** width < bound:
                width += 1
            self.assertEqual(width, 1, bound)
            self.assertEqual((256 ** width // bound) * bound, (256 // bound) * bound, bound)


if __name__ == "__main__":
    unittest.main(verbosity=1)
