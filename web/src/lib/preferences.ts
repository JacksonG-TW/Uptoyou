/**
 * A1 / item 4's two endpoints, as the API actually answers them (`upto/preferences.py`).
 *
 * **The client never resolves "in force".** The `GET` returns the latest row per key already
 * resolved server-side, and D25 and D5 both refuse the alternative: a browser applying
 * latest-wins would put the convention in the one place that cannot be tested from the database.
 * So there is no reducer here and no history — what arrives is what is true.
 *
 * **Nothing is edited and nothing is deleted.** Every write appends: a different band, an `allow`
 * that un-avoids, a re-post of the same value carrying `persist: true`. There is no DELETE in this
 * file because there is none in the product (§3 D).
 */

import { auth, type Device } from './device'
import { must, send } from './http'

/* **The budget's two bands went with the 偏好 screen** (`spec-return-choice.md`, 2026-08-30):
   nothing sets a budget any more and the API refuses the kind. The wire's words were
   `tight`/`easy` and appeared on no screen; the labels were 省一點／鬆一點. */

/** **D38's thirteen since 2026-08-30** — `便利商店`, then `台菜` and `素食` the same evening, in the
 *  order the API's closed list carries them. **`其他` stays last**: the order is
 *  the row a screen renders and the fallback belongs at the end, so the new value goes before it
 *  rather than after — mirrored from `upto/preferences.py`, not chosen here.
 *
 *  **The API had to accept it first.** The value is enforced by a CHECK (revision 0039 widened it);
 *  a chip shipped ahead of the migration renders, taps, and is refused by the database, which is
 *  the worst of the three failures because it looks like it works. Mirrored, not fetched: the list is
 *  closed and versioned by a migration, and a screen that discovered its own controls at runtime
 *  would render an empty settings page on a failed request. The integration test asserts the two
 *  agree; a value outside the list is refused by the database whatever this file believes. */
export const CATEGORIES = [
  '麵食', '飯食', '小吃', '火鍋', '燒烤', '日式', '西式', '早餐', '咖啡飲料',
  '便利商店', '台菜', '素食', '其他',
] as const

/* **The eleven food-label groups and their sourced 「常見於 …」 lines are gone** with the same
   ruling — the ingredient kind was withdrawn wholesale, so there is no control left to list them
   for. Every example was quoted from 食藥署's own material and the three sources are named in the
   commit that added them (c90b06e); nothing here was authored, so nothing is lost that a document
   does not hold. */

/** **One kind since 2026-08-30** (`spec-return-choice.md` §1). `budget` and `avoid_ingredient`
 *  are refused with a 422 naming the kind — refused, not ignored, so a client still sending one
 *  learns it rather than failing quietly. */
export type Kind = 'avoid_category'
export type Stance = 'avoid' | 'allow'

/**
 * One stance the member holds. **`touched` and `share` are per-stance and always present** — every
 * kind carries them, so the screen special-cases none: ingredients report `0` and `0.0` today
 * because nothing carries ingredient data (D103), and the day that changes the number moves on its
 * own with no code here to remember.
 *
 * **Never sum these for a total.** They happen to add up to `breadth.touched` today because D38's
 * categories are disjoint — verified by backend, 14,658 = 14,658 — but `breadth` is the authority
 * and this list is the breakdown. If a kind ever overlaps, adding them would overstate the truth at
 * exactly the moment it mattered.
 */
export type Avoidance = {
  value: string
  persist: boolean
  valid_from: string
  touched: number
  /**
   * **`touched` is a FLOOR on the ingredient rows, and the payload says so rather than the reader
   * guessing** (A19, backend 2026-08-29). Two authored terms of one group — 蝦 and 蝦仁 — name
   * overlapping sets of places, so the count is the largest single term's rather than a union that
   * would double-count. The true number is at least this many.
   *
   * Optional: the category rows carry no flag, because D38's ten are disjoint and their counts are
   * totals. **Absent means a total, never "unknown"** — so the copy hedges only where the wire
   * says to hedge.
   */
  touched_is_a_floor?: boolean
  share: number
}

export type Coverage = {
  reference_rows: number
  share: number
  with_category?: number
  with_ingredient?: number
}

export type Preferences = {
  /* **`month` went with the budget** (`spec-return-choice.md` §1, 2026-08-30). It was the server's
     own expiry boundary and existed so the screen could never derive one — the two-clock defect
     that rule closed is recorded in D25. With no budget there is no month boundary to state. */

  breadth: {
    /** **`touched` — the third name this field has had, and each rename was a correction.**
     *  `removed` until 2026-08-19, `zeroed` until 2026-08-27, `touched` now (backend `fdf1a06`,
     *  D22 re-derived).
     *
     *  A place is never *removed*: it stays proposable, can still be proposed and still appears in
     *  the pool. And since A13 a category no longer *zeroes* anything either — it discounts by
     *  `1 − 1/N`, so a 火鍋 place can still be drawn. What the number counts is the share of the
     *  proposable set that any of the member's stances **reaches at all**, whatever it does on
     *  arrival: an ingredient's ×0 and a category's discount each count one place.
     *
     *  **The name is load-bearing and the history is why.** A field called `zeroed` reads as
     *  *cannot be drawn* to every screen and every spec that meets it — which is how 「拿掉」 got
     *  into a spec once already. */
    touched: number
    proposable: number
    share: number
    /** Stated by the API, never composed here. A share whose denominator the screen invents is
     *  the warning the evaluator refuses at the gate. */
    denominator: string
    /** **`0.5` since D22's amendment; `null` still means *no line exists*.** While it is null
     *  nothing may render as crossed. */
    threshold: number | null
    /** **Stated by the server with `>`, never computed here.** A member exactly on half is not
     *  warned. Same reason as A6's `counts`: a surface that computes a boundary can compute it
     *  wrong, and this one decides whether a person is told they have narrowed themselves. */
    crossed?: boolean
  }
  category_coverage: Coverage
  avoid_categories: Avoidance[]
  /**
   * **Which of the eleven no place carries yet, so a true zero can say why.**
   *
   * A category with coverage but no places would otherwise print 「0 家會比較少中（0.0%）」, and a
   * count of zero reads as a RESULT — *we looked and nothing needed excluding* — when what is true
   * is that the classifier has not run the city with the new value yet. That is A2-G8-zero, and it
   * is the same defect this surface shipped for a few hours on the allergen rows in August; the
   * answer then was silence because there was no sentence, and the answer now is the payload's own
   * sentence because backend wrote one.
   *
   * `why` is rendered **verbatim** and never composed here. Optional, because it empties itself the
   * day the re-pass lands and an older api does not carry it at all.
   */
  values_awaiting_classification?: { values: string[]; why: string }
  /* **`ingredient_coverage`, `budget` and `avoid_ingredients[]` left the payload** with the kinds
     they described (`spec-return-choice.md` §1). Stored rows stay in the database — D24's pins
     reference them and the nightly erasure runs unchanged — they are simply never returned. */
}

export async function fetchPreferences(d: Device): Promise<Preferences> {
  const r = must(await send('GET', `/api/circles/${encodeURIComponent(d.circle)}/preferences`, {
    headers: auth(d),
    // `no-store` is not politeness. G3 drives a NEW browser context and asserts the value came
    // from the GET; a cached read would pass that gate while proving nothing about the server.
    cache: 'no-store',
  }), '讀取失敗')
  return r.json<Preferences>()
}

/**
 * Append one preference row. **204 and an empty body — there is nothing to parse and nothing to
 * echo**, and the caller re-reads rather than patching local state: the server owns "in force".
 *
 * `persist` is passed explicitly on every call. The endpoint defaults it to `false` (D17), and a
 * caller that relies on the default is one refactor away from sending `undefined` where it meant
 * `false` — same value, no record of a choice having been made.
 *
 * **A 401 is the table's `forget_seat`**: `must` drops the key and raises `SeatGone`, so the
 * API's English «the token does not resolve…» never reaches the screen.
 */
export async function postPreference(
  d: Device,
  body: { kind: Kind; value: string; persist: boolean; stance?: Stance },
): Promise<void> {
  must(await send('POST', `/api/circles/${encodeURIComponent(d.circle)}/preferences`, {
    headers: auth(d),
    json: body,
  }), '寫入失敗')
}

/** A whole-number percentage for a share the API already rounded. Rendered from the payload on
 *  every screen that states one — never written into the markup, because today's figure becomes
 *  false the moment a backfill runs and says nothing when it does. */
export function pct(share: number): string {
  return `${(share * 100).toFixed(1)}%`
}
