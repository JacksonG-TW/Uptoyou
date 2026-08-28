/**
 * 甲・日報 — the masthead's dateline. `spec-home-dateline.md` §1, evaluator 2026-08-26.
 *
 * Four segments — date · weekday · solar term · edition — computed here and never fetched. The
 * page is a dated sheet; this is its date.
 *
 * **Every word is a statement of fact (D20).** That is the whole reason 甲 won over the two
 * rejected ornament layers, and it is why the solar-term segment is allowed to vanish: a blank
 * segment is true, and a wrong 節氣 is not.
 *
 * ## The solar-term table is a claim, and this is its source
 *
 * The 24 terms below are 2026's, read from **中央氣象署「曆象資料 → 日曆資料表」·
 * 中華民國115年日曆資料表** (`https://www.cwa.gov.tw/Data/astronomy/2026cal.pdf`, published
 * 2025-02; times are 臺灣時 = UT+8). Checked 2026-08-28 by reading the document twice and
 * requiring the two readings to agree: once from page 2's 節氣 table, which prints the term, the
 * day and the minute, and once from page 1's month grids, where a term's name replaces the lunar
 * date in the cell of the day it falls on. All 24 matched.
 *
 * **The check was not a formality.** 冬至 2026 is **12/22**, not 12/21 as a plausible-looking
 * table would have it, and 立冬 is 11/7 rather than 11/8 — the kind of one-day error that reads
 * as correct all year and is wrong on exactly the day someone looks. The spec asked for the
 * source and for a `false` here if it could not be had; it could, so this is `true`.
 *
 * Only 2026 is listed. **A year absent from the table renders no segment at all** rather than an
 * extrapolation — the terms move by up to a day between years, so a copied table is a guess with
 * a citation on it. When 2027 is wanted, read 2027's own 日曆資料表 and add it here.
 */

/**
 * The wall clock in Taipei, whatever clock the reader is on.
 *
 * **One shift for the whole surface.** `weather.ts` owns it (`taipeiNow`) because it needed it
 * first; this module imports rather than repeating it. Two timezone helpers is how one of them
 * gets fixed alone.
 */
import { taipeiNow } from './weather'

/** The switch the spec names. `false` renders three segments and two dots, and is the honest
 *  state whenever the table below is not sourced. It is `true` because the table is. */
export const SOLAR_TERMS_VERIFIED = true

/** `[name, month, day]` in Taipei date, calendar order. */
type Term = readonly [string, number, number]

const SOLAR_TERMS: Record<number, readonly Term[]> = {
  2026: [
    ['小寒', 1, 5], ['大寒', 1, 20], ['立春', 2, 4], ['雨水', 2, 18],
    ['驚蟄', 3, 5], ['春分', 3, 20], ['清明', 4, 5], ['穀雨', 4, 20],
    ['立夏', 5, 5], ['小滿', 5, 21], ['芒種', 6, 5], ['夏至', 6, 21],
    ['小暑', 7, 7], ['大暑', 7, 23], ['立秋', 8, 7], ['處暑', 8, 23],
    ['白露', 9, 7], ['秋分', 9, 23], ['寒露', 10, 8], ['霜降', 10, 23],
    ['立冬', 11, 7], ['小雪', 11, 22], ['大雪', 12, 7], ['冬至', 12, 22],
  ],
}

const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六'] as const
const COUNT = ['一', '二', '三'] as const

/** Whole days from `a` to `b`, both taken as Taipei dates at midnight. */
function daysBetween(a: Date, bMonth: number, bDay: number): number {
  const from = Date.UTC(a.getFullYear(), a.getMonth(), a.getDate())
  const to = Date.UTC(a.getFullYear(), bMonth - 1, bDay)
  return Math.round((to - from) / 86400000)
}

/**
 * The solar-term segment, or `null` when it cannot be stated.
 *
 * Three sayings, in the spec's order of precedence:
 * - on the term's own day → the bare name (`處暑`)
 * - one to three days before the next term → `<next>前N日`
 * - otherwise → the name of the period we are **inside**, which is true of every day of it
 *
 * `null` on two conditions, and both are real days rather than defensive padding: a year with no
 * table, and a date that falls **before its year's first term** — 2026-01-01 sits inside 冬至's
 * period, which began on 2025-12-22 and lives in a table this module does not have. Naming the
 * period would need a year we have not sourced, so the segment goes rather than the rule.
 */
export function solarTerm(taipei: Date): string | null {
  if (!SOLAR_TERMS_VERIFIED) return null
  const table = SOLAR_TERMS[taipei.getFullYear()]
  if (!table) return null

  let current: Term | null = null
  for (const term of table) {
    const gap = daysBetween(taipei, term[1], term[2])
    if (gap === 0) return term[0]
    if (gap >= 1 && gap <= 3) return `${term[0]}前${COUNT[gap - 1]}日`
    if (gap < 0) current = term
  }
  return current ? current[0] : null
}

/** 05–10 早報 · 11–16 午報 · otherwise 晚報 — the hour in Taipei. */
export function edition(hour: number): string {
  if (hour >= 5 && hour <= 10) return '早報'
  if (hour >= 11 && hour <= 16) return '午報'
  return '晚報'
}

export type Dateline = {
  date: string
  weekday: string
  /** `null` renders nothing — three segments, two dots. */
  term: string | null
  edition: string
}

/**
 * **Computed once, on mount.** A sheet printed at 16:59 does not become the evening edition while
 * you look at it, so nothing here ticks and there is no timer to clean up.
 */
export function dateline(now: Date = new Date()): Dateline {
  const taipei = taipeiNow(now)
  return {
    date: `${taipei.getFullYear()}年${taipei.getMonth() + 1}月${taipei.getDate()}日`,
    weekday: WEEKDAYS[taipei.getDay()],
    term: solarTerm(taipei),
    edition: edition(taipei.getHours()),
  }
}
