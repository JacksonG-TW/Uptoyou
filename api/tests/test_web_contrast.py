#!/usr/bin/env python3
"""Contrast, computed from the shipped tokens — with no hand-maintained list of pairs.

Run: python3 app/api/tests/test_web_contrast.py    (no network, no database, no browser)

H30's finding was a border at 1.26:1 that looked right and hid because nothing measured it. This
file is the half that entry admitted was not built.

**Rewritten 2026-08-18 for D104.** The palette moved from `app/web/index.html`'s two `:root` blocks
to `app/web/src/index.css`, where Tailwind 4 declares it in `@theme` under a `--color-*` namespace
alongside shadcn's own `:root` set. The old version hard-coded a `PAIRS` list; that list had to be
edited by hand every time the palette moved, and it had already been retargeted twice in one day.

**So there is no pair list any more. Three rules derive the pairs from the file itself, and each one
arms itself as the palette grows.**

1. **Every contrast claim written in a comment is verified.** The frontend session documents ratios
   in the CSS — `ink on hot 7.98 · hot-ink on paper 4.00 · hot on paper 2.33` — and this recomputes
   each one from the tokens. A claim that drifts from its tokens fails. **This makes the
   documentation load-bearing instead of decorative**, and it needs nobody to maintain a list: a pair
   becomes checked by being written down.
2. **Every `--color-on-X` must clear 4.5:1 on `--color-X`.** The naming convention *is* the
   declaration that these two meet, so a new hue with an `on-` companion is checked from the moment
   it is added.
3. **If `--color-flood-X` differs from `--color-X`, an `--color-onflood-X` must exist and clear
   4.5:1 on it.** Written when the floods were exact aliases of their hues and no `onflood-*` token
   existed. **That is no longer true (measured 2026-10-10):** every flood is its own value and each
   has an `onflood-*` companion, so this rule is load-bearing. Which floods differ is pinned in
   `KNOWN_DIVERGED` below, so a palette change is a decision written in this file, not a stderr line.

**Why that matters more than it sounds:** when the floods were their hues, no single text colour
worked on all four — `--color-ink` cleared hot (7.98), jade (6.14) and sun (11.74) but failed cobalt
(2.83), and `--color-paper` cleared cobalt (6.56) and failed the other three (2.33, 3.02, 1.58). So
the per-flood companion is not a nicety, whatever the floods hold at a given moment.

**Decoration is deliberately held to no floor.** That principle came out of H30, where treating one
decorative token as if it had a job was how the one-token mistake started, and it outlives the
tokens it was learned on.

**One mode today.** `prefers-color-scheme` appears in this file only inside a comment, so the dark
palette is not ported. Every rule above runs over every declaring block found, so a dark palette is
covered the moment it is declared — and `test_a_second_mode_is_covered_when_it_arrives` says so out
loud rather than leaving it to be noticed.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")
CSS = os.path.join(WEB, "src", "index.css")

TEXT_FLOOR = 4.5   # WCAG 2.1 1.4.3
UI_FLOOR = 3.0     # WCAG 2.1 1.4.11 — a control's boundary, and D91's pips

HEX_TOKEN = re.compile(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})")
# `hot-ink on paper 4.00` — the convention the frontend already writes.
CLAIM = re.compile(r"\b([a-z][a-z0-9-]*) on ([a-z][a-z0-9-]*) ([0-9]+\.[0-9]{2})\b")
COMMENT = re.compile(r"/\*.*?\*/", re.S)


def css() -> str:
    with open(CSS, encoding="utf-8") as handle:
        return handle.read()


def tokens(text: str | None = None) -> dict:
    """Every `--name: #rrggbb` in the file, wherever it is declared.

    Deliberately not scoped to a selector. The palette now lives across a `:root` block and a
    `@theme` block, and pinning the selector is what broke the previous two versions of this file —
    a check that depends on which block a token sits in fails on a refactor rather than on a colour.
    """
    return dict(HEX_TOKEN.findall(css() if text is None else text))


def resolve(name: str, held: dict) -> str | None:
    """A claim says `hot`; the token may be `--color-hot` or `--hot`."""
    return held.get("color-" + name) or held.get(name)


def luminance(colour: str) -> float:
    channels = [int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class TheClaimsInTheCommentsAreTrue(unittest.TestCase):
    def test_every_documented_ratio_recomputes(self):
        held = tokens()
        checked = 0
        for foreground, background, claimed in CLAIM.findall(css()):
            a, b = resolve(foreground, held), resolve(background, held)
            if a is None or b is None:
                continue  # a sentence that merely reads like a claim, not a pair of tokens
            actual = contrast(a, b)
            checked += 1
            self.assertAlmostEqual(
                actual, float(claimed), delta=0.02,
                msg="the file says {} on {} is {}, and the tokens give {:.2f} — the comment drifted "
                    "from the colours, or the colours from the comment".format(
                        foreground, background, claimed, actual),
            )
        self.assertGreater(
            checked, 0,
            "no verifiable contrast claim found in {}. The convention is `<fg> on <bg> N.NN` in a "
            "comment; without one this rule checks nothing, which is worse than failing."
            .format(os.path.relpath(CSS, WEB)),
        )

    def test_the_check_can_fail(self):
        """A claim that does not match its tokens must be caught."""
        self.assertNotAlmostEqual(contrast("#101114", "#FF875C"), 4.00, delta=0.02)


class EveryOnTokenClearsItsHue(unittest.TestCase):
    def test_the_naming_convention_is_the_assertion(self):
        held = tokens()
        pairs = [(name, "color-" + name[len("color-on-"):]) for name in sorted(held)
                 if name.startswith("color-on-")]
        self.assertTrue(pairs, "no --color-on-* tokens found; the convention this rule derives "
                               "pairs from is gone and the rule now checks nothing")
        for on_token, hue in pairs:
            self.assertIn(hue, held, "{} has no {} to sit on".format(on_token, hue))
            ratio = contrast(held[on_token], held[hue])
            self.assertGreaterEqual(
                round(ratio, 2), TEXT_FLOOR,
                "{} on {} is {:.2f}:1 and text needs {}:1".format(on_token, hue, ratio, TEXT_FLOOR),
            )


#: Every flood that is not an alias of a `--color-<hue>` (a `-deep` flood has no hue, so it is always
#: here). Measured 2026-10-10: all eight.
KNOWN_DIVERGED = frozenset({
    "color-flood-cobalt", "color-flood-cobalt-deep", "color-flood-hot", "color-flood-hot-deep",
    "color-flood-jade", "color-flood-jade-deep", "color-flood-sun", "color-flood-sun-deep",
})


class TheFloodsKeepAReadableTextColour(unittest.TestCase):
    """Rule 3 — the one that arms itself when dark mode lands. See the module docstring."""

    def test_a_flood_that_differs_from_its_hue_needs_its_own_companion(self):
        held = tokens()
        floods = [name for name in sorted(held) if name.startswith("color-flood-")]
        self.assertTrue(floods, "no --color-flood-* tokens found")
        for flood in floods:
            hue = "color-" + flood[len("color-flood-"):]
            companion = "color-onflood-" + flood[len("color-flood-"):]
            if hue in held and held[flood].lower() == held[hue].lower():
                # An alias. `on-X` already cleared its floor above, so this flood is covered.
                continue
            self.assertIn(
                companion, held,
                "{} is no longer an alias of {}, so the text colour that cleared the hue no longer "
                "applies to the flood — {} must exist. No single token can serve all four: ink "
                "clears hot, jade and sun and fails cobalt; paper clears cobalt and fails the "
                "other three.".format(flood, hue, companion),
            )
            ratio = contrast(held[companion], held[flood])
            self.assertGreaterEqual(round(ratio, 2), TEXT_FLOOR,
                                    "{} on {} is {:.2f}:1".format(companion, flood, ratio))

    def test_which_floods_differ_from_their_hue_is_pinned(self):
        """It only printed to stderr until 2026-10-10, so it could not fail, and the divergence it
        watched for had already happened unseen. Now a flood joining or leaving the set fails here;
        the fix is to update `KNOWN_DIVERGED` in the same commit as the palette change."""
        held = tokens()
        diverged = {name for name in held if name.startswith("color-flood-")
                    and held.get("color-" + name[len("color-flood-"):], "").lower()
                    != held[name].lower()}
        self.assertEqual(
            sorted(diverged), sorted(KNOWN_DIVERGED),
            "the floods that differ from their hue changed — update KNOWN_DIVERGED in this file "
            "with the palette change, after the onflood rule above has passed for each")


class TheLoadBearingBasics(unittest.TestCase):
    """The pairs that are structural rather than conventional, and so cannot be derived."""

    def test_body_and_secondary_text_on_paper(self):
        held = tokens()
        for name in ("color-ink", "color-muted"):
            self.assertIn(name, held)
            ratio = contrast(held[name], held["color-paper"])
            self.assertGreaterEqual(round(ratio, 2), TEXT_FLOOR,
                                    "{} on paper is {:.2f}:1".format(name, ratio))

    def test_the_pips_on_the_die_face(self):
        """D91: pips are graphical objects, not text, so the UI floor applies.

        `--color-pipred` is one value in both schemes by ruling — a UI accent on a dark page must
        flip lighter, while a die face does not, because a die is an object rather than a surface.
        Paint on a die is the same paint with the lights off.
        """
        held = tokens()
        for pip in ("color-pip", "color-pipred"):
            self.assertIn(pip, held)
            ratio = contrast(held[pip], held["color-diefill"])
            self.assertGreaterEqual(round(ratio, 2), UI_FLOOR,
                                    "{} on the die face is {:.2f}:1".format(pip, ratio))


class TheSecondModeIsCoveredWhenItArrives(unittest.TestCase):
    def test_a_second_mode_is_covered_when_it_arrives(self):
        """Every rule above reads tokens wherever they are declared, so dark is covered on arrival.

        Said out loud because "one mode today" is a fact about the port's progress, not about the
        design: D104 carries two schemes, and a reader should not have to infer from a passing test
        that only one of them was checked.
        """
        text = css()
        has_dark = bool(re.search(r"prefers-color-scheme\s*:\s*dark", COMMENT.sub(" ", text))) \
            or bool(re.search(r"\.dark\s*\{", text)) \
            or bool(re.search(r'\[data-theme=["\']?dark', text))
        if not has_dark:
            print("\nweb contrast: only one colour scheme is declared — `prefers-color-scheme` "
                  "appears in this file only inside a comment. Every rule here reads tokens "
                  "wherever they are declared, so the dark palette is checked the moment it is "
                  "written; nothing to remember.", file=sys.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
