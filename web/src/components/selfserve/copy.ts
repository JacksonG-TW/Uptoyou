/**
 * The self-serve surface's own labels — `spec-self-serve-2026-09-13.md` §6.
 *
 * **What is here and what is not.** Every member-facing *refusal* (409 the circle is full, 410 the
 * ticket was replaced, 404 no such ticket, 429 the daily ceiling) is the server's sentence,
 * rendered from the response's `detail` — those are states of the circle and the ticket, and
 * backend settles their words. **Nothing in this file is a refusal.** These are the screen's own
 * labels and the one notice line, which have no request behind them and so can only live in the
 * source.
 *
 * **`server_copy.py` is the wrong home for them, and that is a correction to my own first
 * instinct** (backend, 2026-09-13, having checked rather than reasoned): that file is a **scanner,
 * not a string table** — it walks `*.py` and lists what the *server* sends. A constant parked there
 * would be a string nothing sends, registered as server copy it is not, and the register is only
 * worth having while every row in it is real.
 *
 * **The half I was actually worried about is already covered.** `tools/subset_fonts.py` derives the
 * display and body charsets by walking `app/web/src`, and `font_subset_check --against-copy` runs
 * in the pre-commit hook, so a sentence written here **is** in the derived set and **is** checked.
 * The blank-gap story that made that rule (或 and 趟) was about *server* strings reaching a screen
 * without passing through `app/web/` at all — which is not the shape of anything in this file.
 *
 * **So the rule for editing this file: run `python3 tools/font_subset_check.py --against-copy`
 * before you are pleased with a wording.** A copy shortfall stops the commit rather than warning,
 * so a gap cannot ship — but the check is cheap and the rebuild (`tools/subset_fonts.py --build`,
 * needing `fonttools` + `brotli`) is not. Backend drafted two better-sounding notices before this
 * one and **both were short a character** — 它 in the first, 掉 in the second, neither in the
 * subset. On this machine they render perfectly, because a CJK fallback face draws them; on a clean
 * device they are blank gaps. Confirmed here independently: both characters are absent from
 * `charset-sub.txt`, and every character of `KEY_NOTICE` is present.
 */

/**
 * §2b's one line, beside the key — **backend's words, verified drawable character by character
 * against `noto-sub-variable.woff2` itself.**
 *
 * It states **what is lost, never what to do**: the copy control says what to do by being there,
 * and D20 is that the surface may state and may not advise.
 *
 * **One constant because it appears twice** — the creator's screen (§2b) and the joiner's (§4.2),
 * which §4 requires to be identical treatment. A sentence written out twice is a tally that
 * drifts, and this repository has been bitten by that often enough to keep a test for it.
 */
export const KEY_NOTICE = '這把鑰匙只出現這一次，我們沒有留著。離開這一頁就不見了。'

/** §2a — the one line on the naming screen. States the absence that matters to a stranger deciding
 *  whether to start: there is nothing to sign up for. */
export const NO_ACCOUNT = '不用帳號，也不用 email。'
