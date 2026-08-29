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

/** **衛福部's eleven food-label groups**, mirrored from revision 0023's CHECK for the same
 *  reason the categories are: the list is closed and versioned by a migration, and a screen that
 *  discovered its own controls at runtime would render an empty settings page on a failed request.
 *
 *  **The word for why a person avoids one of these appears nowhere in this file, on this screen,
 *  or in any string it renders.** What is recorded is a dietary choice. The moment the copy names
 *  a medical reason, the row stops being a preference and becomes health information about an
 *  identified person, which this product does not hold. That is a PDPA boundary and it is kept by
 *  the wording — there is no flag to set.
 *
 *  **亞硫酸鹽類 was removed and restored on 2026-08-28, and the round trip is recorded here so it
 *  is not re-proposed.** The case for removing it: it is an additive rather than an ingredient a
 *  dish is made of, and no source this product holds states it at the level of a restaurant. The
 *  owner's reversal within the hour: **the other ten rest on exactly the same missing data** —
 *  `ingredient_coverage` is 0 for every one of the eleven — so sulfites are not a special case,
 *  and singling them out would claim a distinction the data does not support. The screen's honesty
 *  about all eleven is `pref-ingredient-coverage`, which states that nothing acts on any of them
 *  yet; that sentence is the answer to the worry, not a shorter list.
 *
 *  So this list is the API's eleven, whole. Backend's ⊆ guard passes because it is the same set. */
export const INGREDIENTS = [
  '甲殼類', '芒果', '花生', '牛奶／羊奶', '蛋', '堅果類',
  '芝麻', '含麩質之穀物', '大豆', '魚類', '亞硫酸鹽類',
] as const

/**
 * **Where each group is commonly found** — the owner's ask, verbatim: 「若我是一般的使用者會希望
 * 亞硫酸鹽類，可以舉例說明。像我就不知道亞硫酸鹽類是甚麼，有哪些食材有用到」.
 *
 * **Sourced, not authored — every name below is quoted from a government document, and the three
 * sources are named per row.** The spec's draft table was written from memory and said so; it was
 * checked line by line and it was wrong in one place that mattered, which is the argument for the
 * rule rather than a footnote to it: the draft put 啤酒 under 含麩質之穀物, and the Q&A's A17 says
 * 由穀類製得的酒類 is explicitly EXEMPT from the labelling regulation. A hint naming a food the
 * regulation excludes is worse than no hint.
 *
 * **A · 食藥署「食品過敏原標示規定問答集」107.08.21**
 *   https://www.fda.gov.tw/tc/includes/GetFile.ashx?id=f636703601345760449
 *   Q10 芝麻油 · Q12 鮭魚卵 · Q13 堅果類 · Q15 含麩質穀物 · Q19 大豆製品 · Q20/Q21 魚類製品
 * **B · 食藥署「食品過敏原標示規定第一點所定六項含有致過敏性內容物及其製品之案例」103.03.13**
 *   https://www.fda.gov.tw/upload/133/Content/2014031216074266953.pdf
 *   (一) 蝦 · (二) 蟹 · (三) 芒果 · (四) 花生 · (五) 牛奶 · (六) 蛋
 * **C · 食品添加物使用範圍及限量暨規格標準 附表一 第（四）類 漂白劑**
 *   https://law.moj.gov.tw/LawClass/LawGetFile.ashx?FileId=0000079439&lan=C
 *   the permitted uses of 亞硫酸鉀／鈉／氫鈉 etc., which is where an ADDITIVE's answer to
 *   "what is it in" actually lives — the allergen material names only the chemicals and the
 *   10 mg/kg threshold, so B and A cannot answer this row and C can.
 *
 * All three read 2026-08-28. **A row that could not be sourced would ship with no line at all**
 * (the solar-term rule, `spec-home-dateline` §1a): a blank is true, a guess is not. Every row
 * found a source, but two are thin and are flagged rather than padded — 芝麻 has exactly one named
 * product in the whole Q&A, and 魚類's named products are the non-obvious ones rather than fish.
 * Padding either from general knowledge is the thing this comment exists to forbid.
 *
 * **Statements only** (D20), and no 過敏 anywhere (D103 clause 2) — including in this comment's
 * neighbours on the screen. What a row says is where a thing turns up, not what to do about it.
 */
export const INGREDIENT_EXAMPLES: Record<string, string> = {
  甲殼類: '蝦、蟹、蝦餅、蟹肉棒',                        // B(一)(二)
  芒果: '芒果乾、芒果醬、芒果冰棒、芒果蛋糕',              // B(三)
  花生: '花生醬、花生粉、花生糖、沙嗲醬',                  // B(四)
  '牛奶／羊奶': '起士、奶粉、優格、人造奶油',              // B(五)
  蛋: '蛋糕、蛋塔、皮蛋、蛋黃醬',                        // B(六)
  堅果類: '杏仁、核桃、腰果、開心果',                     // A Q13
  芝麻: '芝麻油',                                      // A Q10 — the only product the Q&A names
  含麩質之穀物: '小麥、大麥、黑麥、燕麥',                  // A Q15 (A17: 由穀類製得的酒類 is exempt)
  大豆: '豆腐、豆漿、醬油、味噌',                         // A Q19
  魚類: '魚油、魚類取得的明膠、鮭魚卵',                    // A Q20/Q21/Q12
  亞硫酸鹽類: '金針乾製品、白葡萄乾、脫水蔬菜、糖漬果實類（用作漂白）',  // C
}

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

/**
 * The statement itself. **抽不到, never 拿掉／少掉／移除** (`A2-G8-verb`): the place keeps its
 * seat, stays proposable and still appears in the round and in the table at `0/36`. What changed
 * is that no roll reaches it. `D37` stands beside this — nothing is hidden from the typeahead on
 * a preference.
 *
 * **The second sentence is the evaluator's, and the reason is parallelism rather than accuracy.**
 * My draft ended 「這個選擇目前不會生效」 — true, and a different frame from every other row.
 * Four rows should read as four of the same thing; 「不會生效」 costs the reader a translation
 * step (*what does that mean for me?*) **on the row where a translation step is most expensive**.
 * 「沒有任何店家會因此抽不到」 lands in the vocabulary the screen already uses, so the comparison
 * against 480 家 and 8,664 家 is immediate rather than inferred. D20 still holds: it states the
 * consequence and advises nothing.
 *
 * **`A2-G8-zero`: where the KIND has no coverage, the row states why there is no number instead
 * of stating zero.** The first build printed 「0 家抽不到（0.0%）」 for an ingredient, and the
 * evaluator was right that this is worse than silence: **a count of zero reads as a result —
 * *we looked and nothing needed excluding*. What is true is that we hold no ingredient data at
 * all, so the choice does not act.** Those are opposite meanings and the false one is the
 * reassuring one, on the single kind the owner ruled about because 「過敏是會致死的」.
 *
 * **It keys on the kind's COVERAGE and never on `touched === 0`**, and the distinction is the
 * whole rule. A category stance that genuinely reaches nothing at 42.6% coverage HAS been
 * measured, and 「0 家」 is then the true answer. Zero-because-measured and
 * no-measurement-exists must not render the same way, which is exactly the absent-subject
 * failure we have found all day — arriving here in the one place it costs more than a wrong
 * verdict.
 *
 * **The two kinds no longer say the same thing, because they no longer DO the same thing**
 * (A13 / `spec-avoid-discount.md` AD-9, evaluator 2026-08-27). An ingredient is still ×0, so
 * 抽不到 stays true for it and stays. A category is now a discount of `1 − 1/N` — a 火鍋 place
 * can still be drawn — so 抽不到 became a false statement on every category row overnight, and
 * the honest phrase is 比較少中. **This is why one helper became two rather than growing a
 * flag**: the whole content of each is its verb, and a shared function with a boolean would put
 * the two claims one typo apart.
 */
export function touchedLine(a: { touched: number; share: number } | undefined, coverage: number): string | null {
  if (!a) return null
  if (!(coverage > 0)) return '店家資料還沒有這一項。目前沒有任何店家會因此比較少中。'
  return `${a.touched.toLocaleString('en-US')} 家會比較少中（${pct(a.share)}）`
}

/**
 * The ingredient half of the pair, **dormant since 2026-08-29 and kept for when the wire wakes**.
 *
 * The two helpers exist as a pair because the two kinds no longer DO the same thing: a category is
 * a discount of `1 − 1/N` — a 火鍋 place can still be drawn, so 比較少中 — and an ingredient is
 * still ×0, so 抽不到 stays true for it. **The whole content of each is its verb**, which is why
 * this is a second function and not a boolean on the first: a shared helper with a flag would put
 * the two claims one typo apart.
 *
 * **Its second branch is A2-G8-zero, and it is the reason this file still holds it.** Where the
 * KIND has no coverage the row must state why there is no number rather than state zero: 「0 家」
 * reads as a RESULT — *we looked and nothing needed excluding* — when what is true is that nothing
 * was measured. Opposite meanings, and the false one is the reassuring one, on the kind the owner
 * ruled about because 「過敏是會致死的」.
 *
 * **Why nothing calls it today.** A19 gave ingredients coverage (4,509 places), which flips this
 * function to its count branch — and the count on the wire is a placeholder: the GET answers
 * `touched: 0, share: 0.0` for every ingredient because the per-ingredient figure is not computed
 * yet. So both branches are false at once, and the row renders no stat at all until the field is
 * real. Deleting this would mean rewriting the argument above when it is; leaving it, unused and
 * explained, costs one export.
 */
export function zeroLine(a: { touched: number; share: number } | undefined, coverage: number): string | null {
  if (!a) return null
  if (!(coverage > 0)) return '店家資料還沒有這一項。目前沒有任何店家會因此抽不到。'
  return `${a.touched.toLocaleString('en-US')} 家抽不到（${pct(a.share)}）`
}

/** A whole-number percentage for a share the API already rounded. Rendered from the payload on
 *  every screen that states one — never written into the markup, because today's figure becomes
 *  false the moment a backfill runs and says nothing when it does. */
export function pct(share: number): string {
  return `${(share * 100).toFixed(1)}%`
}
