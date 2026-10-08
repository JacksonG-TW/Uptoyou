/**
 * **Does every pooled shop hold the same number of the 36 cells?** — 6 shops × 6, 4 × 9, 3 × 12,
 * 2 × 18. Then the reveal's 「每一家的機會不一樣」 would be false, and it says 「這一輪每一家的機會一樣」
 * instead (owner kept both wordings, 2026-10-08). Read from the drawn board, never from the pool
 * size: the same `board` the cells draw, so the sentence and the cells cannot disagree.
 *
 * Anything that is not a 6 × 6 board is `false` — no board, no claim of evenness. A one-shop board
 * cannot reach a reveal (the roll refuses a pool under two), and reads `false` too.
 */
export function evenBoard(board: unknown): boolean {
  if (!Array.isArray(board) || board.length !== 6) return false
  const counts = new Map<number, number>()
  for (const row of board) {
    if (!Array.isArray(row) || row.length !== 6) return false
    for (const id of row) counts.set(id, (counts.get(id) ?? 0) + 1)
  }
  return counts.size > 1 && new Set(counts.values()).size === 1
}

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
