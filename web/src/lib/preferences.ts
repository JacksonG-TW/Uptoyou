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

/** The two bands. Not a number — a typed budget would need a currency, a period and a model. */
export const BANDS = ['tight', 'easy'] as const
export type Band = (typeof BANDS)[number]

/** The label a person reads. `tight`/`easy` are the wire's words and appear on no screen. */
export const BAND_LABEL: Record<Band, string> = { tight: '省一點', easy: '鬆一點' }

/** D38's ten, in the order the API's closed list carries them. Mirrored, not fetched: the list is
 *  closed and versioned by a migration, and a screen that discovered its own controls at runtime
 *  would render an empty settings page on a failed request. The integration test asserts the two
 *  agree; a value outside the list is refused by the database whatever this file believes. */
export const CATEGORIES = [
  '麵食', '飯食', '小吃', '火鍋', '燒烤', '日式', '西式', '早餐', '咖啡飲料', '其他',
] as const

/** 衛福部's eleven food-label groups, mirrored from revision 0023's CHECK for the same reason.
 *
 *  **The word for why a person avoids one of these appears nowhere in this file, on this screen,
 *  or in any string it renders.** What is recorded is a dietary choice. The moment the copy names
 *  a medical reason, the row stops being a preference and becomes health information about an
 *  identified person, which this product does not hold. That is a PDPA boundary and it is kept by
 *  the wording — there is no flag to set. */
export const INGREDIENTS = [
  '甲殼類', '芒果', '花生', '牛奶／羊奶', '蛋', '堅果類',
  '芝麻', '含麩質之穀物', '大豆', '魚類', '亞硫酸鹽類',
] as const

export type Kind = 'budget' | 'avoid_category' | 'avoid_ingredient'
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
  share: number
}

export type Coverage = {
  reference_rows: number
  share: number
  with_category?: number
  with_ingredient?: number
}

export type Preferences = {
  /** **`YYYY-MM`, and the only month this screen is allowed to know** (A2-G13c, `4caed3d`).
   *
   *  It is the month the server's own expiry boundary falls in — derived from the same
   *  `date_trunc('month', now())` that computed every `expires_on` — so `month` and
   *  `budget.expires_on.slice(0, 7)` cannot disagree. Backend measured the database session's
   *  `TimeZone` as **UTC**, so it is the UTC month, **not** Taipei's; the two are the same value
   *  except for the eight hours before each UTC month end. **Never convert it, and never derive a
   *  month here.** A conversion re-creates the two-clock defect at precisely the boundary this
   *  field exists to close, and would look correct in every test but one evening a month. If the
   *  boundary is ever ruled to be Taipei, this value moves and the client needs no change. */
  month: string
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
  ingredient_coverage: Coverage
  budget: {
    value: Band
    persist: boolean
    expires_on: string
    valid_from: string
    /** Still returned, deliberately. Expiry stops the band *contributing*; the flag exists so the
     *  screen can show D25's re-affirmation prompt rather than present a stale band as current. */
    expired: boolean
  } | null
  avoid_categories: Avoidance[]
  avoid_ingredients: Avoidance[]
}

/** The device's own credential, D74's operator-issued secret pasted on the device screen. Both
 *  halves or neither — a token with no circle addresses no endpoint. */
export type Device = { token: string; circle: string }

export function device(): Device | null {
  const token = localStorage.getItem('upto_token')
  const circle = localStorage.getItem('upto_circle')
  return token && circle ? { token, circle } : null
}

function auth(d: Device): HeadersInit {
  return { authorization: `Bearer ${d.token}` }
}

/**
 * **The API's `detail` is written for whoever is holding a terminal, and 401's is written in
 * English.** Driven on 2026-08-19 against a circle this credential does not hold: the preferences
 * screen rendered 「the token does not resolve to a member of this circle」 — a developer's sentence,
 * in the wrong language, on a screen whose whole promise is 「只有你看得到」.
 *
 * The same rule `round.ts` already follows, and it is a rule rather than a habit: **401 and 404 are
 * about the credential and are answered in the surface's own words; every other status keeps the
 * API's sentence**, because those are written for a person already and second-guessing them is how
 * a screen comes to state something the server did not.
 */
async function said(r: Response, fallback: string): Promise<Error> {
  if (r.status === 401) return new Error('這把鑰匙開不了這個圈子。回到裝置畫面重新貼一次。')
  if (r.status === 404) return new Error('找不到這個圈子。')
  const body = await r.json().catch(() => ({}))
  return new Error((body as { detail?: string }).detail || `${fallback}（${r.status}）`)
}

export async function fetchPreferences(d: Device): Promise<Preferences> {
  const r = await fetch(`/api/circles/${encodeURIComponent(d.circle)}/preferences`, {
    headers: auth(d),
    // `no-store` is not politeness. G3 drives a NEW browser context and asserts the value came
    // from the GET; a cached read would pass that gate while proving nothing about the server.
    cache: 'no-store',
  })
  if (!r.ok) throw await said(r, '讀取失敗')
  return r.json()
}

/**
 * Append one preference row. **204 and an empty body — there is nothing to parse and nothing to
 * echo**, and the caller re-reads rather than patching local state: the server owns "in force".
 *
 * `persist` is passed explicitly on every call. The endpoint defaults it to `false` (D17), and a
 * caller that relies on the default is one refactor away from sending `undefined` where it meant
 * `false` — same value, no record of a choice having been made.
 */
export async function postPreference(
  d: Device,
  body: { kind: Kind; value: string; persist: boolean; stance?: Stance },
): Promise<void> {
  const r = await fetch(`/api/circles/${encodeURIComponent(d.circle)}/preferences`, {
    method: 'POST',
    headers: { ...auth(d), 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (r.status === 204) return
  throw await said(r, '寫入失敗')
}

/** A whole-number percentage for a share the API already rounded. Rendered from the payload on
 *  every screen that states one — never written into the markup, because today's figure becomes
 *  false the moment a backfill runs and says nothing when it does. */
export function pct(share: number): string {
  return `${(share * 100).toFixed(1)}%`
}
