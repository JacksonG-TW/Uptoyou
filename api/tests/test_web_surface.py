#!/usr/bin/env python3
"""The surface's rules, checked where each one is actually decidable.

Run: python3 app/api/tests/test_web_surface.py    (no network, no database, no browser)

**Rewritten 2026-08-18 for D104.** The surface was one `index.html` with a vendored Vue global
build, and this file's machinery matched it: HTML comments delimited "screens", and every rule was
read off that one document. Vite + React 19 + Tailwind 4 has no such document, so the old
apparatus is gone rather than adapted.

**Each rule now lives where it can be decided, and the two are not interchangeable.**

- **Source (`app/web/src`) for anything about what the code says.** H7's rule and D20's advisory-copy
  rule are properties of what was written, and source is readable.
- **Built output (`app/web/dist`) for anything about what a browser fetches.** §6's dead-wifi rule
  and the `@font-face` declarations are properties of the artefact nginx serves, and only the build
  produces them.

**Two things I measured before writing an assertion, and both changed it.**

**`dangerouslySetInnerHTML` appears in `dist/assets/*.js` once, from React itself.** So a built-output
scan for H7 can never pass, and H7 is checked in source only. This is the mirror of the reason H7 is
*not* checked in built output for the other direction: a minifier mangles nothing about a prop name,
but React shipping the string means the signal is not ours.

**Three external URLs appear in the built output and none of them is a network dependency** — a
`https://react.dev` link inside a React error template, `https://tailwindcss.com` in Tailwind's MIT
licence comment, and `http://www.w3.org/2000/svg` as an SVG namespace. **So §6 cannot be checked by
scanning for URLs.** It is checked at the places a browser actually fetches from: `<script src>`,
`<link href>`, `<img src>`, and CSS `url(...)`. A gate that failed on a licence comment would be
waved through the first time it fired, which is the same lesson as the font gate demanding a `═`
that appeared only in a CSS comment.

**D20's second half is written to arm itself rather than to wait.** *Weather appears on the home
screen and nowhere else* needs screens, and the scaffold has none. Rather than leave a comment for
someone to remember, the check asserts the half that is decidable today — **weather vocabulary
appears in no module other than a home module** — which passes on a scaffold that mentions weather
nowhere and starts biting the moment a second module mentions it. The positive half (*the home does
show it*) prints as not-yet-assertable and names what it waits for.
"""

import ast
import os
import re
import sys
import unittest

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "web")
SRC = os.path.join(WEB, "src")
DIST = os.path.join(WEB, "dist")

# D20's first half: the surface may state, never advise.
ADVISORY = ["建議", "推薦", "最好", "不如", "應該去", "別去", "值得一試", "首選"]

# D20's second half. The vocabulary is the weather's, not a restaurant's — 「晴光市場」 is a place
# name and must not read as weather, which is why the list is phrases and measures rather than
# single characters.
WEATHER_WORDS = ["降雨機率", "體感溫度", "weather_code", "weather_text", "氣溫", "濕度", "舒適度"]

# A module is "the home" by name. Kept deliberately loose — `Home.tsx`, `home/index.tsx`,
# `screens/home/Weather.tsx` all count — because the rule is about which screen, not which file.
HOME_HINT = re.compile(r"(^|[/\\])home([/\\.]|$)", re.I)

# **And the modules that are the home without being named it. Added 2026-08-19.**
#
# The pattern above was written against a layout that no longer exists, and it went stale the way
# every naming convention does: D104's port put the home screen's root in `App.tsx` and its lookup
# tables in `lib/weather.ts`, so the two files that legitimately hold weather read as "not the home"
# and D20's second half started failing on correct code. Reported by the frontend session, which
# checked it against HEAD first and did not touch this file.
#
# **Widening the pattern was the obvious fix and it is the wrong one.** Any regex loose enough to
# admit `App.tsx` and `lib/` admits every module in the tree, which turns this assertion into "any
# file may mention weather" — deleting the rule with extra steps. So the exemption is a list
# instead. Adding to it is a visible act in a diff someone reviews; a new screen that mentions
# weather still fails, which is the entire point of the rule.
#
# **Each entry says why it is the home rather than merely being allowed**, because a bare list of
# paths decays into a list of whatever was failing that week.
HOME_MODULES = {
    # The home screen's root. It IS the home — the only screen the React port has so far — and the
    # day a router arrives this line is what has to be re-argued rather than quietly kept.
    "src/App.tsx": "the home screen's root component",
    # The measure→label tables. Not a place weather is *shown*: D20's rule is about which screen
    # displays it, and a lookup table displays nothing. It is listed rather than exempted by folder
    # so that a second `lib/` module holding weather has to be argued for too.
    "src/lib/weather.ts": "the home screen's weather vocabulary, displayed by nothing itself",
}


def is_home(relative_path: str) -> bool:
    """Whether a module is the home screen's, by name or by the explicit list."""
    return bool(HOME_HINT.search(relative_path)) or \
        relative_path.replace(os.sep, "/") in HOME_MODULES

LINE_COMMENT = re.compile(r"//[^\n]*")
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)

FETCHED_ATTR = re.compile(r"""<(?:script|link|img|source|video|audio|iframe)\b[^>]*?
                              \b(?:src|href)\s*=\s*["']([^"']+)["']""", re.I | re.X)
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}", re.I)


def source_files(extensions=(".tsx", ".ts", ".jsx", ".js")) -> list[str]:
    """Every hand-written module under `src`. `node_modules` and `dist` are not source."""
    found = []
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
        for name in files:
            if name.endswith(extensions):
                found.append(os.path.join(root, name))
    return sorted(found)


def read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def code_of(path: str) -> str:
    """A module with its comments removed.

    Comments are stripped for the same reason the font derivation strips them: a rule that fires on
    a comment *describing* the rule is a rule that gets disabled. String literals are deliberately
    **kept** — copy lives in them, so D20's vocabulary must still see them.
    """
    text = read(path)
    return LINE_COMMENT.sub(" ", BLOCK_COMMENT.sub(" ", text))


def dist_files(extension: str) -> list[str]:
    found = []
    for root, _dirs, files in os.walk(DIST):
        for name in files:
            if name.endswith(extension):
                found.append(os.path.join(root, name))
    return sorted(found)


def built() -> bool:
    return os.path.isdir(DIST) and bool(dist_files(".html"))


class TheBuildIsPresentOrTheReasonIsStated(unittest.TestCase):
    def test_dist_exists_or_the_rules_needing_it_say_so(self):
        """`dist/` is gitignored, so a fresh clone has none until `npm run build` has run.

        This is stated as its own check rather than skipped inside the others, because "the rules
        about the served artefact did not run" must be one visible line and not four quiet ones.
        """
        if built():
            return
        print("\nweb surface: app/web/dist is absent — the rules about the SERVED artefact did not "
              "run (§6's fetch points, the @font-face declarations). Build it with "
              "`docker compose build proxy`, or `npm run build` in app/web, and re-run. The source "
              "rules below ran regardless.", file=sys.stderr)


class NoDangerousInnerHtml(unittest.TestCase):
    """H7, in source, because the built output cannot answer it."""

    def test_it_is_never_used(self):
        offenders = []
        for path in source_files():
            if "dangerouslySetInnerHTML" in code_of(path):
                offenders.append(os.path.relpath(path, WEB))
        self.assertEqual(
            offenders, [],
            "H7: dangerouslySetInnerHTML appears in {} — the surface renders text as text. Every "
            "string on it comes from a government file or another person's typing.".format(
                ", ".join(offenders)),
        )

    def test_the_check_reads_source_and_not_the_bundle(self):
        """Pinned, because the obvious 'improvement' is to scan `dist` too, and it cannot work.

        React's own runtime contains the string, so a built-output scan fails on an innocent build.
        Measured 2026-08-18: one occurrence in `dist/assets/*.js` on a surface that does not use it.
        """
        if not built():
            self.skipTest("dist absent")
        bundles = "".join(read(path) for path in dist_files(".js"))
        self.assertIn(
            "dangerouslySetInnerHTML", bundles,
            "React's runtime no longer carries this string, so a built-output scan for H7 may have "
            "become possible — re-measure before assuming either way",
        )

    def test_the_check_can_fail(self):
        self.assertIn("dangerouslySetInnerHTML",
                      LINE_COMMENT.sub(" ", 'a = {dangerouslySetInnerHTML: {__html: x}}'))

    def test_a_comment_mentioning_it_does_not_trip_the_check(self):
        """Both comment forms, because a rule that fires on its own documentation gets deleted."""
        for comment in ("// never use dangerouslySetInnerHTML here",
                        "/* dangerouslySetInnerHTML is banned by H7 */"):
            stripped = LINE_COMMENT.sub(" ", BLOCK_COMMENT.sub(" ", comment))
            self.assertNotIn("dangerouslySetInnerHTML", stripped, comment)


class TheSurfaceStatesAndDoesNotAdvise(unittest.TestCase):
    """D20's first half, over the copy in source."""

    def test_no_advisory_copy(self):
        offenders = []
        for path in source_files():
            code = code_of(path)
            for word in ADVISORY:
                if word in code:
                    offenders.append("{}: {}".format(os.path.relpath(path, WEB), word))
        self.assertEqual(offenders, [], "D20: the surface may state, never advise — " +
                         "; ".join(offenders))

    def test_the_vocabulary_is_not_empty(self):
        """A rule with an empty word list passes everything. H34's shape."""
        self.assertGreater(len(ADVISORY), 5)


class WeatherStaysOnTheHomeScreen(unittest.TestCase):
    """D20's second half, armed rather than deferred — see the module docstring."""

    def modules_mentioning_weather(self) -> dict:
        found = {}
        for path in source_files():
            code = code_of(path)
            hits = [word for word in WEATHER_WORDS if word in code]
            if hits:
                found[os.path.relpath(path, WEB)] = hits
        return found

    def test_no_module_outside_the_home_mentions_weather(self):
        elsewhere = {
            path: hits for path, hits in self.modules_mentioning_weather().items()
            if not is_home(path)
        }
        self.assertEqual(
            elsewhere, {},
            "D20: weather belongs to the home screen and nowhere else; found it in " +
            ", ".join("{} ({})".format(path, "/".join(hits)) for path, hits in elsewhere.items()),
        )

    def test_every_listed_home_module_still_exists(self):
        """**The list must not outlive the files in it.**

        This is the failure the list replaced, wearing a different hat: `HOME_HINT` went stale because
        nothing told it the layout had moved, and an exemption list rots exactly the same way — rename
        `lib/weather.ts` and the entry lingers, exempting a path that is not there while the real file
        is unexempted and failing. Worse, an entry for a deleted module reads as a *reason* to a future
        reader, so the stale list is more misleading than the stale regex was.

        So the list is checked against the disk. A rename must move the entry, and the diff that
        renames the file is the diff that has to.
        """
        missing = [path for path in sorted(HOME_MODULES)
                   if not os.path.exists(os.path.join(WEB, path))]
        self.assertEqual(
            missing, [],
            "HOME_MODULES exempts {} which no longer exist(s) under app/web/. An exemption for an "
            "absent file exempts nothing and reads as a reason — move the entry with the rename."
            .format(", ".join(missing)),
        )

    def test_the_exemption_list_is_not_a_blanket(self):
        """A list that grew to cover the whole surface would pass everything, which is H34's shape.

        Not a style rule — it is the failure mode of the fix. The reason a list was chosen over a
        wider pattern is that each addition is visible; a list nobody pushes back on becomes the
        pattern it replaced.
        """
        modules = source_files()
        self.assertLess(
            len(HOME_MODULES), max(2, len(modules) // 2),
            "HOME_MODULES exempts {} of {} modules. Past roughly half, D20's second half is no "
            "longer asserting anything — if the surface really is that weather-heavy, the rule needs "
            "re-arguing rather than the list needs extending.".format(len(HOME_MODULES), len(modules)),
        )

    def test_the_positive_half_says_what_it_waits_for(self):
        """*The home does show it* cannot be asserted before a home screen exists.

        Printed rather than skipped silently, and it needs no maintenance: the moment a home module
        mentions weather this assertion starts passing on its own, and the moment a non-home module
        does, the check above fails.
        """
        mentions = self.modules_mentioning_weather()
        if any(is_home(path) for path in mentions):
            return
        print("\nweb surface: no module mentions weather yet, so D20's positive half (the home "
              "screen DOES show it) is not yet assertable. It arms itself when a home module "
              "does — nothing to remember.", file=sys.stderr)


class NothingIsFetchedFromAnotherHost(unittest.TestCase):
    """§6's dead-wifi rule, at the points a browser actually fetches from."""

    def fetch_points(self) -> list[tuple[str, str]]:
        points = []
        for path in dist_files(".html"):
            for url in FETCHED_ATTR.findall(read(path)):
                points.append((os.path.relpath(path, WEB), url))
        for path in dist_files(".css"):
            for url in CSS_URL.findall(CSS_COMMENT.sub(" ", read(path))):
                points.append((os.path.relpath(path, WEB), url))
        return points

    def test_every_fetch_point_is_local(self):
        if not built():
            self.skipTest("dist absent")
        points = self.fetch_points()
        self.assertTrue(points, "no fetch points found at all — the scan is looking in the wrong "
                                "place, which would pass for the wrong reason")
        remote = [(where, url) for where, url in points
                  if re.match(r"[a-z]+:", url) and not url.startswith("data:")]
        self.assertEqual(
            remote, [],
            "§6: the surface must work on a dead wifi, so every asset ships with it; found " +
            ", ".join("{} → {}".format(where, url) for where, url in remote),
        )

    def test_a_bare_url_in_a_comment_or_a_message_is_not_a_violation(self):
        """The measured false alarm this check was written around.

        `dist` contains `https://react.dev` (a React error template), `https://tailwindcss.com`
        (a licence comment) and `http://www.w3.org/2000/svg` (an XML namespace). None is fetched.
        A scan for URLs would fail on all three, and a gate that cries wolf gets waved through.
        """
        if not built():
            self.skipTest("dist absent")
        everything = "".join(read(path) for path in dist_files(".js") + dist_files(".css"))
        self.assertRegex(everything, r"https?://",
                         "no external URL strings at all — if that is now true the note above is "
                         "stale, but the check below must still target fetch points")
        self.assertEqual(
            [], [url for _w, url in self.fetch_points() if url.startswith("http")],
            "a fetch point genuinely points at another host",
        )


class TheGlobalClassNamespace(unittest.TestCase):
    """**There are no CSS modules in this build, so every class name is global.**

    *Added 2026-08-19 at the frontend session's request, after it lost time to the failure below.*

    The reveal's die rendered as a black blob with correct pips floating on top. The CSS was right —
    the same markup in an isolated file rendered a clean cube. `home.css` already defined a global
    `.cell` for the collage (ink ground, hard offset shadow, per-child aspect ratios, an nth-child
    margin) and the die's nine cells inherited all of it. **The second screen to want a generic name
    silently gets the first screen's styling**, and the diff that causes it looks correct in both
    files.

    Their words on why this is a check rather than a habit: *"I would rather it be a check than a
    thing I remember."*

    **What is compared: the class names a stylesheet can match from the document root.** For each
    selector, only the **first** compound counts — `.reveal .cell` claims `reveal` and not `cell`,
    because `cell` there is scoped and cannot reach another screen's markup. That is exactly the fix
    the frontend applied, so the rule rewards it rather than merely describing the bug. A class
    redefined in the *same* file is normal (responsive overrides) and is not a collision; two
    different files claiming one root-reachable name is.
    """

    RULE = re.compile(r"([^{}]+)\{", re.S)
    CLASS = re.compile(r"\.(-?[A-Za-z_][\w-]*)")
    COMBINATOR = re.compile(r"\s*[>+~]\s*|\s+")

    def stylesheets(self) -> list:
        found = []
        for root, dirs, names in os.walk(SRC):
            dirs[:] = [d for d in dirs if d not in ("node_modules", "dist")]
            found += [os.path.join(root, n) for n in names if n.endswith(".css")]
        return sorted(found)

    def root_classes(self, text: str) -> set:
        """Class names this stylesheet can match without an ancestor of its own."""
        found = set()
        for selector_list in self.RULE.findall(CSS_COMMENT.sub(" ", text)):
            selectors = selector_list.strip()
            # An at-rule prelude (`@media (max-width: 899.98px)`) is not a selector; the rules nested
            # inside it are matched by this same loop, so nothing is skipped by ignoring it.
            if not selectors or selectors.startswith("@"):
                continue
            for selector in selectors.split(","):
                selector = selector.strip()
                if selector:
                    found |= set(self.CLASS.findall(self.COMBINATOR.split(selector)[0]))
        return found

    def claims(self) -> dict:
        held = {}
        for path in self.stylesheets():
            for name in self.root_classes(read(path)):
                held.setdefault(name, set()).add(os.path.relpath(path, WEB))
        return held

    def test_no_two_stylesheets_claim_the_same_root_class(self):
        collisions = {name: sorted(where) for name, where in self.claims().items()
                      if len(where) > 1}
        self.assertEqual(
            collisions, {},
            "the same root-reachable class is defined in more than one stylesheet, and there are no "
            "CSS modules here — whichever loads later wins, on every screen: {}\n"
            "  Scope one of them under its screen's own class (`.reveal .cell`, not `.cell`), which "
            "takes it out of the global namespace and out of this check.".format(collisions),
        )

    def test_the_check_catches_the_collision_it_was_written_for(self):
        """`.cell` in two stylesheets — the actual defect, since the real tree is clean today.

        H37's rule: this check's subject is *absent* on a healthy tree, so passing proves nothing
        about the check. Driven against fixture text instead, and the fixture is the real bug.
        """
        collage = ".cell { background: var(--color-ink); box-shadow: 6px 6px 0 #000; }"
        die = ".cell { background: #fff; border-radius: 6px; }"
        held = {}
        for label, text in (("home.css", collage), ("reveal.css", die)):
            for name in self.root_classes(text):
                held.setdefault(name, set()).add(label)
        self.assertEqual({n: sorted(w) for n, w in held.items() if len(w) > 1},
                         {"cell": ["home.css", "reveal.css"]})

    def test_scoping_takes_a_class_out_of_the_namespace(self):
        """And the fix must actually clear the check, or the rule punishes the remedy."""
        collage = ".cell { background: #000; }"
        die = ".reveal .cell { background: #fff; } .reveal .cell:nth-child(2) { margin: 0; }"
        self.assertEqual(self.root_classes(collage), {"cell"})
        self.assertEqual(self.root_classes(die), {"reveal"})

    def test_an_ancestor_only_selector_does_not_claim_its_descendant(self):
        """`.cell img` claims `cell` — it can still reach another screen's cells."""
        self.assertEqual(self.root_classes(".cell img { inset: 0; }"), {"cell"})

    def test_it_says_how_exposed_each_stylesheet_is(self):
        """Unscoped count per file, printed rather than asserted.

        A screen stylesheet with twenty bare class names has not collided *yet*; requiring every
        screen to scope under one root is a stronger rule and a design decision that belongs to the
        session that owns `app/web/`, not to this file. So the exposure is reported and the collision
        is enforced.
        """
        for path in self.stylesheets():
            count = len(self.root_classes(read(path)))
            if count > 1:
                print("\nweb surface: {} claims {} class names in the global namespace"
                      .format(os.path.relpath(path, WEB), count), file=sys.stderr)


class TheVendoredFaces(unittest.TestCase):
    """Every `@font-face` the build emits, and the two things each must get right."""

    def faces(self) -> list[dict]:
        found = []
        for path in dist_files(".css"):
            for block in FONT_FACE.findall(CSS_COMMENT.sub(" ", read(path))):
                entry = {}
                for declaration in block.split(";"):
                    if ":" in declaration:
                        key, _, value = declaration.partition(":")
                        entry[key.strip().lower()] = value.strip()
                found.append(entry)
        return found

    def test_at_least_one_face_ships(self):
        if not built():
            self.skipTest("dist absent")
        self.assertTrue(self.faces(), "the build emitted no @font-face at all")

    def test_every_face_declares_a_weight_range_not_a_single_weight(self):
        """**The source faces are variable and their default instances are not Regular.**

        Noto Sans TC is `wght 100–900` defaulting to **Thin**, and an `@font-face` without the range
        renders the whole surface hairline — that has happened here. Noto Serif TC is `wght 200–900`
        defaulting to **ExtraLight**, so the ranges differ per face and a shared constant would be
        wrong for one of them. What is asserted is therefore the shape — two numbers — rather than a
        value.
        """
        if not built():
            self.skipTest("dist absent")
        for face in self.faces():
            family = face.get("font-family", "?")
            weight = face.get("font-weight", "")
            self.assertRegex(
                weight, r"^\d+\s+\d+$",
                "{}: font-weight is {!r}; a variable face needs its range declared, or the "
                "browser renders the face's default instance — Thin for the sans, ExtraLight for "
                "the serif".format(family, weight),
            )

    def test_the_sans_declares_the_range_its_source_face_actually_has(self):
        if not built():
            self.skipTest("dist absent")
        sans = [f for f in self.faces() if "sans" in f.get("font-family", "").lower()]
        self.assertTrue(sans, "no sans face found among {}".format(
            [f.get("font-family") for f in self.faces()]))
        for face in sans:
            self.assertEqual(face.get("font-weight"), "100 900",
                             "the sans source face is wght 100–900; declaring anything else claims "
                             "a weight it has not got")

    def test_the_serif_declares_the_range_its_source_face_actually_has(self):
        """`200 900`, and specifically **not** the sans's `100 900`.

        The two ranges differ and the manifest now spells each one out per face, because the tempting
        mistake is to copy the working declaration: `100 900` on the serif claims a weight the file
        has not got, and the masthead's `font-weight: 900` then resolves against a clamp rather than
        against the axis.
        """
        if not built():
            self.skipTest("dist absent")
        serif = [f for f in self.faces() if "serif" in f.get("font-family", "").lower()]
        if not serif:
            self.skipTest("no serif face ships yet")
        for face in serif:
            self.assertEqual(face.get("font-weight"), "200 900",
                             "the serif source face is wght 200–900, not the sans's 100–900; "
                             "declaring the sans's range claims a weight it has not got")

    def test_every_family_the_stylesheets_ask_for_first_is_actually_declared(self):
        """**The failure this exists for: a stack whose first family nothing declares.**

        `home.css` set `font-family: "UpTo Serif", "Noto Serif TC", serif` on the masthead while no
        `@font-face` named `UpTo Serif`, so the largest text on the product silently rendered in
        whatever serif the machine happened to have — and on a machine with none, in whatever the
        generic keyword resolved to. §6 forbids an external asset, so there is no webfont behind the
        fallback to be right instead; a screenshot on this machine looks fine and the same page on a
        phone does not.

        **The first family in a stack, and only the first.** Everything after it is a fallback by
        definition and is *supposed* to be absent — demanding those be declared would forbid writing
        a fallback at all. So the rule is exactly: what the page asks for first, the page must ship.
        """
        if not built():
            self.skipTest("dist absent")
        declared = {f.get("font-family", "").strip("\"'") for f in self.faces()}
        asked = {}
        for path in dist_files(".css"):
            text = CSS_COMMENT.sub(" ", read(path))
            for stack in re.findall(r"font-family\s*:\s*([^;}]+)", text):
                first = stack.split(",")[0].strip().strip("\"'")
                # A generic keyword or a bare custom property is not a family this repo can ship.
                if not first or first.startswith("var(") or first in (
                        "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui",
                        "inherit", "initial", "unset", "revert"):
                    continue
                asked.setdefault(first, os.path.relpath(path, WEB))
        missing = {name: where for name, where in asked.items() if name not in declared}
        self.assertEqual(
            missing, {},
            "asked for first and never declared: {} — declared faces are {}.\n"
            "  A family nothing declares falls back in silence. Build it with "
            "tools/subset_fonts.py --build, place it in public/fonts/, and rebuild the proxy (H28)."
            .format(missing, sorted(declared) or "none"),
        )

    def test_every_face_points_at_a_file_that_actually_shipped(self):
        """A face whose `src` 404s degrades silently to a fallback — no error, wrong glyphs."""
        if not built():
            self.skipTest("dist absent")
        for face in self.faces():
            for url in CSS_URL.findall(face.get("src", "")):
                self.assertTrue(url.startswith("/"), "{} is not an absolute served path".format(url))
                on_disk = os.path.join(DIST, url.lstrip("/"))
                self.assertTrue(os.path.exists(on_disk),
                                "{} is declared and did not ship — the browser would fall back "
                                "silently".format(url))


class TheScreenNeverOffersWhatTheApiRefuses(unittest.TestCase):
    """The screen's closed list must be a **subset** of the API's, never the other way round.

    **The list this guards changed on 2026-08-30, and the guard did not.** It was `INGREDIENTS`
    until the owner withdrew that kind from the surface (「將選擇權還給使用者，我們專心做好分類」);
    `lib/preferences.ts` no longer defines it, so this class now watches `CATEGORIES` — the list
    that still exists, and the one that just gained D38's eleventh value 便利商店. **The rule is
    the same rule**: the screen may never offer what the endpoint would refuse.

    **Why a subset and not equality, and it earned that on both lists.** The ingredient version
    was ⊆ because the owner took 亞硫酸鹽類 off the screen while the endpoint kept accepting it.
    The category version needs it for the opposite reason: on 2026-08-30 the API gained 便利商店
    hours before the screen did, so equality would have gone red in the gap and the honest-looking
    fix would have been to delete the test. The two lists are equal today; the relationship is
    what is asserted.

    **What is guarded is the direction, and nothing guarded it before this class existed.** The two
    lists are independent copies — `upto/preferences.py` and `app/web/src/lib/preferences.ts` — and
    a value the screen offers that the API refuses is a **refusal the member sees** after tapping a
    button the product drew for them. That failure is silent until somebody taps it.

    **Both sides are read as text, and neither is imported.** The TypeScript has no runtime here;
    and `upto.preferences` pulls in FastAPI, which this host does not have and which this check has
    no use for. The Python side is parsed with `ast`, so it reads the literal the module defines
    rather than a regex's guess. Both parses fail loudly if their file stops looking like a list of
    quoted strings, which is better than quietly matching nothing and passing.
    """

    def api_list(self, name: str) -> list:
        source = read(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                   "src", "upto", "preferences.py"))
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets
            ):
                values = [e.value for e in node.value.elts
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                self.assertTrue(values, "{}: parsed nothing from the API side".format(name))
                return values
        self.fail("{} is not assigned in upto/preferences.py".format(name))

    def literals(self, name: str) -> list:
        source = read(os.path.join(SRC, "lib", "preferences.ts"))
        start = source.index("export const {} = [".format(name))
        end = source.index("]", start)
        found = re.findall(r"'([^']+)'", source[start:end])
        self.assertTrue(found, "{}: parsed nothing — has the file's shape changed?".format(name))
        return found

    def test_every_category_the_screen_offers_is_one_the_api_accepts(self):
        accepted = self.api_list("CATEGORIES")
        offered = self.literals("CATEGORIES")
        unknown = [value for value in offered if value not in accepted]
        self.assertEqual(unknown, [],
                         "the screen offers what the endpoint would refuse: {}".format(unknown))

    def test_and_the_api_may_know_more_than_the_screen_shows(self):
        """The direction that may legitimately be unequal — asserted so nobody re-tightens it."""
        self.assertLessEqual(len(self.literals("CATEGORIES")),
                             len(self.api_list("CATEGORIES")))

    def test_the_eleventh_value_reached_both_sides(self):
        """**The specific thing this commit is about**, named rather than left to the ⊆ check.

        `便利商店` is D38's eleventh value (revision 0039). A chip the API refuses and a category
        the API accepts but no chip offers are both silent failures, in opposite directions, and
        the subset test above catches only one of them.
        """
        self.assertIn("便利商店", self.api_list("CATEGORIES"))
        self.assertIn("便利商店", self.literals("CATEGORIES"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
