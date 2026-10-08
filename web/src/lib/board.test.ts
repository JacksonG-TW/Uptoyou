import { describe, expect, it } from 'vitest'
import { evenBoard, litCell } from './board'

/** A 6×6 board filled row by row from a list of (place id, cell count). */
function board(...shares: [number, number][]): number[][] {
  const flat = shares.flatMap(([id, n]) => Array<number>(n).fill(id))
  if (flat.length !== 36) throw new Error(`a board has 36 cells, this one ${flat.length}`)
  return Array.from({ length: 6 }, (_, r) => flat.slice(r * 6, r * 6 + 6))
}

describe('evenBoard — the odds sentence says what the board shows', () => {
  it('is true when every shop holds the same number of cells', () => {
    expect(evenBoard(board([1, 6], [2, 6], [3, 6], [4, 6], [5, 6], [6, 6]))).toBe(true)   // the gate's case
    expect(evenBoard(board([1, 12], [2, 12], [3, 12]))).toBe(true)
    expect(evenBoard(board([1, 18], [2, 18]))).toBe(true)
    expect(evenBoard(board([1, 9], [2, 9], [3, 9], [4, 9]))).toBe(true)
  })
  it('is false when any two shops differ by even one cell', () => {
    expect(evenBoard(board([1, 12], [2, 13], [3, 11]))).toBe(false)
    expect(evenBoard(board([1, 7], [2, 7], [3, 7], [4, 7], [5, 8]))).toBe(false)   // five shops can never be even
  })
  it('makes no claim about a board that is not 6×6', () => {
    expect(evenBoard(undefined)).toBe(false)
    expect(evenBoard([])).toBe(false)
    expect(evenBoard(board([1, 18], [2, 18]).slice(0, 5))).toBe(false)
    expect(evenBoard([[1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 2, 3]])).toBe(false)
  })
  it('reads a one-shop board as not even (the roll refuses one, but the rule does not lean on that)', () => {
    expect(evenBoard(board([1, 36]))).toBe(false)
  })
})

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
