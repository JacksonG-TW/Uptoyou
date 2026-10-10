/**
 * **The rolled cell, as 0-based [row, column]: `board[die1 − 1][die2 − 1]`** — the first die picks
 * the row, the second the column (`spec-board-2026-09-11.md` §2). A transposed reading lights the
 * wrong shop on every non-double, and the board would still look right. `null` before the dice are
 * known, or for a value off a die.
 */
export function litCell(dice: readonly [number, number] | undefined | null): [number, number] | null {
  if (!dice) return null
  const [a, b] = dice
  if (![a, b].every((v) => Number.isInteger(v) && v >= 1 && v <= 6)) return null
  return [a - 1, b - 1]
}

/**
 * **The drawn drawer's number, N = (die1 − 1) × 6 + die2** (`spec-reveal-qiantong-2026-10-09.md`):
 * rows are die one and columns die two, both 1…6 from the top left, so the 36 drawers are numbered
 * left to right, top to bottom — the same cell `litCell` names. `null` when the dice are not known.
 */
export function drawerOf(dice: readonly [number, number] | undefined | null): number | null {
  const cell = litCell(dice)
  return cell ? cell[0] * 6 + cell[1] + 1 : null
}

const DIGIT = '〇一二三四五六七八九'

/** A drawer number, 1…36, in Chinese numerals as a 籤 is written: 一, 十, 十四, 二十, 二十七, 三十六.
 *  Anything outside 1…99 is `''` — the board has 36 drawers and never asks for more. */
export function zhNumeral(n: number): string {
  if (!Number.isInteger(n) || n < 1 || n > 99) return ''
  if (n < 10) return DIGIT[n]
  const tens = Math.floor(n / 10), ones = n % 10
  return (tens === 1 ? '' : DIGIT[tens]) + '十' + (ones ? DIGIT[ones] : '')
}

const STEMS = '甲乙丙丁戊己庚辛壬癸'
const BRANCHES = '子丑寅卯辰巳午未申酉戌亥'

/** **Each drawer's own 干支 name, in sixty-cycle order** (owner 「A」, 2026-10-10): drawer n →
 *  天干[(n − 1) mod 10] + 地支[(n − 1) mod 12], so 一 = 甲子, 二十七 = 庚寅, 三十六 = 己亥. It names the
 *  drawer and never a shop. `''` outside 1…60. */
export function ganzhi(n: number): string {
  if (!Number.isInteger(n) || n < 1 || n > 60) return ''
  return STEMS[(n - 1) % 10] + BRANCHES[(n - 1) % 12]
}

/** **From this many shops the cabinet is plain wood** (owner 「A」, 2026-10-10; the threshold set by
 *  frontend and the evaluator on one fixture round per count): the palette has four face colours, so
 *  from the fifth shop a colour repeats and stops naming a shop. */
export const WOOD_FROM = 5

/** Is this round's cabinet plain wood? **Counted from the POOL, not the drawn board** (the
 *  reviewer's should on 9f7e999): colours are given by pool seat (`faceOf`, seat mod 4), so a
 *  fifth pooled shop repeats a colour even when a veto left it no drawer — five pooled shops with
 *  one vetoed drew four on the board and two of them shared hot, on the cabinet and in the list. */
export function woodPool(places: Record<string, unknown> | undefined | null): boolean {
  return !!places && Object.keys(places).length >= WOOD_FROM
}

/**
 * **Which roll animation this reveal plays: the dice or the 籤筒** (owner, decision-log 6c743a5:
 * one picked at random each time). Seeded from the round id, so every device in the circle sees
 * the same one and a reload shows it again. A small integer hash (mulberry-style mix), not
 * `Math.random`: the same round id must give the same answer everywhere.
 */
export function rollAnimFor(roundId: number): 'dice' | 'tube' {
  let x = (roundId | 0) ^ 0x9e3779b9
  x = Math.imul(x ^ (x >>> 16), 0x85ebca6b)
  x = Math.imul(x ^ (x >>> 13), 0xc2b2ae35)
  x ^= x >>> 16
  return (x & 1) === 0 ? 'dice' : 'tube'
}
