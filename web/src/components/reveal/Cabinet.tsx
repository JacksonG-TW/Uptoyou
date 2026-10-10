import type { ReactNode } from 'react'
import { faceOf, type Places } from '@/lib/reveal'
import { ganzhi, litCell, woodBoard, zhNumeral } from '@/lib/board'
import { drawable } from './Board'

/**
 * **The member's board as a 籤詩櫃: 36 numbered drawers** (`spec-reveal-qiantong-2026-10-09.md`).
 *
 * Each drawer is one outcome. **Its label is its own number in Chinese numerals, 一 … 三十六, and
 * its own 干支 name small in the corner** (owner 「A」, 2026-10-10) — drawer (r, c) is
 * (r − 1) × 6 + c, numbered left to right, top to bottom, the cell `board[r − 1][c − 1]` the server
 * drew. Neither names a shop. **A shop is its colour alone** (owner, after v11), and **from five
 * shops every drawer is the same plain wood** (`WOOD_FROM`): four face colours cannot name a fifth
 * shop, so colour stops claiming to.
 *
 * **No edge labels.** The pip axes and the corner went with v11; nothing replaces them. The dice
 * say the row and the column by where they rest (`Reveal.tsx`), and the run marks the answer:
 * - `lines` (the dice run): a gold frame along the drawn row and one along the drawn column,
 *   crossing on the drawer. Grid items placed on the row and the column, so nothing is measured.
 * - `frame` (the 籤筒 run): a gold frame inside the drawn drawer's edge, with an ink ring.
 *
 * **Every cell on screen is a cell the server decided** (spec-board §2): the nested map emits the
 * board as drawn, and each cell carries its row and column in the DOM. No count, no share, no
 * percentage, anywhere (§4). The grid is `aria-hidden`; the list beside it says the shops in text.
 *
 * `children` is the layer the dice (or the 籤筒) rest in, positioned against this section.
 */
export default function Cabinet({
  board,
  places,
  dice,
  lit,
  mark,
  children,
}: {
  board: number[][] | undefined
  places: Places
  dice: [number, number] | undefined
  /** Whether the drawn drawer is marked yet — handed in, because the reveal keeps the one clock. */
  lit: boolean
  mark: 'lines' | 'frame'
  children?: ReactNode
}) {
  if (!drawable(board)) return null
  const cell = litCell(dice)
  const wood = woodBoard(board)
  return (
    <section className="cabinet" data-part="board" data-wood={wood ? 'yes' : undefined} data-mark={mark}>
      {/* The mechanism, stated once — the dice run only. Under the 籤筒 no dice line is said and
          nothing replaces it (owner 「直接不講」). */}
      {mark === 'lines' && (
        <p className="boardNote" data-part="board-note">骰子指到哪一格，就是哪一家。</p>
      )}
      <div className="cabFrame">
        <div className="cabGrid" data-part="board-grid" aria-hidden="true">
          {board.map((row, r) =>
            row.map((placeId, c) => {
              const n = r * 6 + c + 1
              const face = faceOf(places, placeId)
              return (
                <span
                  key={`${r}-${c}`}
                  className="boardCell"
                  data-user-content
                  data-part="board-cell"
                  data-row={r + 1}
                  data-col={c + 1}
                  data-n={zhNumeral(n)}
                  data-place={placeId}
                  data-face={wood ? undefined : face ?? undefined}
                  data-unknown={face === null ? 'yes' : undefined}
                  /* The drawn drawer lights by its marks only — its fill never changes (BD-4). */
                  data-lit={lit && cell && r === cell[0] && c === cell[1] ? 'yes' : undefined}
                  /* Explicit placement: the traces below are placed items too, and auto-placed
                     cells would flow around them. */
                  style={{ gridRow: r + 1, gridColumn: c + 1 }}
                >
                  <span className="cabGz dSerif">{ganzhi(n)}</span>
                  <span className="cabNo dSerif">{zhNumeral(n)}</span>
                </span>
              )
            }),
          )}
          {lit && cell && mark === 'lines' && (
            <>
              <span className="cabTrace" data-part="trace-row" style={{ gridRow: cell[0] + 1, gridColumn: '1 / -1' }} />
              <span className="cabTrace" data-part="trace-col" style={{ gridColumn: cell[1] + 1, gridRow: '1 / -1' }} />
            </>
          )}
        </div>
        {children}
      </div>
    </section>
  )
}
