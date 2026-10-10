import { describe, expect, it } from 'vitest'
import { drawerOf, ganzhi, litCell, rollAnimFor, woodBoard, WOOD_FROM, zhNumeral } from './board'

/** A 6×6 board filled row by row from a list of (place id, cell count). */
function board(...shares: [number, number][]): number[][] {
  const flat = shares.flatMap(([id, n]) => Array<number>(n).fill(id))
  if (flat.length !== 36) throw new Error(`a board has 36 cells, this one ${flat.length}`)
  return Array.from({ length: 6 }, (_, r) => flat.slice(r * 6, r * 6 + 6))
}

describe('litCell — the rolled cell is board[die1 - 1][die2 - 1], row then column', () => {
  it('takes the first die as the row and the second as the column', () => {
    expect(litCell([4, 3])).toEqual([3, 2])   // a transpose would give [2, 3]
    expect(litCell([1, 6])).toEqual([0, 5])
    expect(litCell([6, 6])).toEqual([5, 5])
  })
  it('lights nothing before the dice are known or for a value off a die', () => {
    expect(litCell(undefined)).toBeNull()
    expect(litCell(null)).toBeNull()
    expect(litCell([0, 3])).toBeNull()
    expect(litCell([7, 1])).toBeNull()
    expect(litCell([2.5, 1])).toBeNull()
  })
})

describe('drawerOf — N = (die1 − 1) × 6 + die2', () => {
  it('numbers drawers left to right, top to bottom', () => {
    expect(drawerOf([1, 1])).toBe(1)
    expect(drawerOf([1, 6])).toBe(6)
    expect(drawerOf([2, 1])).toBe(7)
    expect(drawerOf([5, 3])).toBe(27)
    expect(drawerOf([6, 6])).toBe(36)
  })
  it('mirrors: 5·3 is 二十七 and 3·5 is 十七', () => {
    expect(drawerOf([5, 3])).toBe(27)
    expect(drawerOf([3, 5])).toBe(17)
  })
  it('agrees with litCell on every pair', () => {
    for (let a = 1; a <= 6; a++) for (let b = 1; b <= 6; b++) {
      const [r, c] = litCell([a, b])!
      expect(drawerOf([a, b])).toBe(r * 6 + c + 1)
    }
  })
  it('is null without dice', () => {
    expect(drawerOf(undefined)).toBeNull()
    expect(drawerOf([0, 3])).toBeNull()
  })
})

describe('zhNumeral — the drawer number as a 籤 writes it', () => {
  it('writes 1…36', () => {
    expect([1, 9, 10, 11, 14, 19, 20, 21, 27, 30, 33, 36].map(zhNumeral))
      .toEqual(['一', '九', '十', '十一', '十四', '十九', '二十', '二十一', '二十七', '三十', '三十三', '三十六'])
  })
  it('never writes an Arabic digit', () => {
    for (let n = 1; n <= 36; n++) expect(zhNumeral(n)).not.toMatch(/[0-9]/)
  })
  it('is empty off the board', () => {
    expect(zhNumeral(0)).toBe('')
    expect(zhNumeral(100)).toBe('')
    expect(zhNumeral(1.5)).toBe('')
  })
})

describe('ganzhi — each drawer’s own name, sixty-cycle order', () => {
  it('names the ruled anchors', () => {
    expect(ganzhi(1)).toBe('甲子')
    expect(ganzhi(27)).toBe('庚寅')
    expect(ganzhi(36)).toBe('己亥')
  })
  it('gives 36 different names', () => {
    expect(new Set(Array.from({ length: 36 }, (_, i) => ganzhi(i + 1))).size).toBe(36)
  })
})

describe('woodBoard — plain wood from five shops', () => {
  it('is coloured up to four shops and wood from five', () => {
    expect(WOOD_FROM).toBe(5)
    expect(woodBoard(board([1, 9], [2, 9], [3, 9], [4, 9]))).toBe(false)
    expect(woodBoard(board([1, 8], [2, 7], [3, 7], [4, 7], [5, 7]))).toBe(true)
    expect(woodBoard(undefined)).toBe(false)
  })
})

describe('rollAnimFor — one animation per round, the same on every device', () => {
  it('is stable for a round id', () => {
    for (const id of [1, 42, 2487, 99999]) expect(rollAnimFor(id)).toBe(rollAnimFor(id))
  })
  it('picks both across round ids', () => {
    const seen = new Set(Array.from({ length: 40 }, (_, i) => rollAnimFor(1000 + i)))
    expect(seen).toEqual(new Set(['dice', 'tube']))
  })
})
