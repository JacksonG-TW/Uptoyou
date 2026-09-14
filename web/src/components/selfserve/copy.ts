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

/**
 * §2c — the join link's life, on the creator's screen. **Backend's words, font-checked before they
 * reached me** (2026-09-13; they drafted three and checked all three against
 * `noto-sub-variable.woff2`'s own cmap — verified independently here, 23 characters, none absent).
 *
 * **It is here because the creator is the only person who can prevent the failure.** The owner
 * ruled the ticket lives one hour (「最多 1 小時就過期」); without this line the common case is a
 * link posted at lunch and tapped at three, and the first anyone learns of it is a friend saying
 * the link is broken.
 *
 * **Both halves are doing work.** 「做好」 — the hour runs from when the link was **made**, not from
 * when it was posted or opened, and a reader who assumes 「an hour from when I sent it」 gets the
 * wrong answer on exactly that failure. 「再有一小時」 — a fresh full hour, not the remainder, which
 * is the other thing people guess wrong. Cause and remedy in one sentence, and the control directly
 * below it does what the second half says.
 */
export const LINK_LIFE = '連結做好一小時就過期，換一條新的就再有一小時。'

/** §2a — the one line on the naming screen. States the absence that matters to a stranger deciding
 *  whether to start: there is nothing to sign up for. */
export const NO_ACCOUNT = '不用帳號，也不用 email。'

/**
 * `/circle` for a seat that is **not** the creator's — the line that stands where the re-issue
 * control would (evaluator-ruled 2026-09-13, `gate-selfserve-2026-09-13.md` Addendum 4, on the
 * owner's ruling that re-issue is the creator's seat only, `91d146b`).
 *
 * **It replaces a button that failed every time for this reader.** Measured on 8080 before it: a
 * member saw 換一條新的連結 enabled, pressed it, and got a 403 that landed under the seat list,
 * 250 px from the button — the rule learned by breaking it, and the remedy never stated. This line
 * gives both before anything is pressed, in the product's own word for the creator, 開圈子的人.
 *
 * Every character checked against `charset-sub.txt` before it was written here; none absent.
 */
export const MEMBER_INVITE = '要邀人進來，跟開圈子的人要連結。'

/**
 * The creator's `/circle` — **is the link they sent still alive** (owner 「顯示」 2026-09-13; the
 * evaluator's words and format, `gate-selfserve-2026-09-13.md` Addendum 5).
 *
 * **The time is the browser's clock**, `expires_at` formatted with no `timeZone` option, so the
 * reader's own zone applies — display, not a D83 exception. `h23` because 上午/下午 would be a
 * second thing to read on a line whose whole job is one time. A link lives at most an hour, so
 * HH:MM with no date is never ambiguous.
 *
 * **The expired line says why a friend's tap failed and does not say what to do** — the button
 * directly under it does that by being there (D20).
 *
 * Every character checked against `charset-sub.txt` before it was written; none absent.
 */
const HHMM = new Intl.DateTimeFormat('zh-TW', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
export const linkLive = (at: Date) => `現在的連結可以用到${HHMM.format(at)}。`
export const LINK_EXPIRED = '上一條連結過期了，朋友點了會進不來。'
