/**
 * **The die's two facts every drawing of a die shares**: where the pips sit for each value, and
 * which values carry red pips. A Taiwanese die prints 1 and 4 in red (`--color-pipred`, its own
 * token, deliberately not the accent: the accent measured 2.74:1 on the die's face, under the 3:1
 * floor for a graphical object).
 *
 * The thrown 2-D/3-D `Die` component that lived here went with the 籤詩櫃 rebuild (2026-10-10): the
 * reveal's dice are now `Cube.tsx`, which come to rest on the cabinet in a 3/4 view. The operator's
 * board (`Board.tsx`), the ground (`Field.tsx`) and `Cube.tsx` read these two tables, so a pip
 * drawn anywhere agrees with a pip drawn everywhere else.
 */

/** The pip positions on a 3×3 grid, by value. Index 1–9, reading left to right, top to bottom. */
export const PIPS: Record<number, number[]> = {
  1: [5],
  2: [1, 9],
  3: [1, 5, 9],
  4: [1, 3, 7, 9],
  5: [1, 3, 5, 7, 9],
  6: [1, 3, 4, 6, 7, 9],
}

export const RED = new Set([1, 4])
