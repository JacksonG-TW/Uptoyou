import { faceOf, type Places } from '@/lib/reveal'

/**
 * The member's 36-cell board — `spec-board-2026-09-11.md`, the owner's three 「1」 of 2026-09-11.
 *
 * **What it is:** a 6×6 grid, one cell per outcome, each cell in its place's face colour, with a
 * legend of colour → shop name beneath and one authored line stating the mechanism. Row = die one,
 * column = die two, both 1…6 from the top left. A member reads their own two dice off the screen,
 * finds the row and the column, and the colour there is the shop. **That sentence is the whole
 * reason this exists; anything that makes it false makes the picture decorative.**
 *
 * **Every cell on screen is a cell the server decided.** The payload is the drawn board, not
 * `{place_id: count}` — with counts the client would lay the cells out itself and the drawing would
 * stop being the table the server drew and become the client's arithmetic wearing the server's
 * authority (§2). So nothing here computes a position, an order or a share.
 *
 * **No count, no share, no percentage — not in the text, not in `title`, not in `aria-label`, at
 * any width (§4).** That is the ruling's whole point and it is the one thing to check before adding
 * anything to this file. The cells stay countable by eye, and ruling 1 bought that *after the round
 * closes*; it is not licence to write the number down.
 *
 * **The grid is `aria-hidden` and the legend is not.** Thirty-six coloured cells announced one by
 * one is noise, and the two things a reader needs — the mechanism and which colour is which shop —
 * are the note and the legend, both real text. Same division `ALLOC36` already makes one component
 * over.
 */

/** 6 rows, 6 columns. Stated once; the grid's CSS reads the same number. */
const SIDE = 6

/**
 * **Is this board drawable at all**, and the answer is never «nearly».
 *
 * §5: a missing or short `board` draws **nothing**, and never a grey grid — an even grid is the
 * statement «everyone had the same chance», which is false, and D112's rule is that an absence
 * gets a shape rather than a plausible-looking presence. A swept pool sends no `board` for exactly
 * this reason, so «absent» is a state the payload means rather than one it fell into.
 *
 * The shape is checked rather than assumed because the alternative is a `.map` over `undefined`
 * inside a screen whose whole job is to have already landed.
 */
function drawable(board: number[][] | undefined): board is number[][] {
  return (
    Array.isArray(board) &&
    board.length === SIDE &&
    board.every((row) => Array.isArray(row) && row.length === SIDE &&
      row.every((c) => typeof c === 'number'))
  )
}

export default function Board({
  board,
  places,
  dice,
  lit,
}: {
  board: number[][] | undefined
  places: Places
  /** The deciding pair. `rolls` carries every member's pair and exactly one has `counts: true`;
   *  `dice` is that one, already resolved by the API, so this component never picks a winner. */
  dice: [number, number] | undefined
  /** **Whether the lit cell's outline is on yet** — the board fades in after the answer block and
   *  the cell lights after the board (§3). Handed in rather than timed here: the reveal's sequence
   *  lives in one place, and a component running its own clock would be a second, unmeasured one. */
  lit: boolean
}) {
  if (!drawable(board)) return null

  /* The lit cell, read the ruling's way — `board[die1 − 1][die2 − 1]`, which is the access
     expression the nesting exists to make literal. Nothing is recomputed from `winning_place_id`:
     BD-3b's job is to assert that these two agree, and a client that derived one from the other
     would make that gate unfalsifiable. */
  const litRow = dice ? dice[0] - 1 : -1
  const litCol = dice ? dice[1] - 1 : -1

  /* The legend is the pool, in pool order, which is what gives each place its face — `faceOf` keys
     off `Object.keys(places)` so a place wears the same colour here, on the round screen and in the
     operator's grid. Names only (§4). */
  const seats = Object.keys(places)

  return (
    <section className="board" data-part="board">
      {/* States the mechanism once, and states rather than advises (D20). */}
      <p className="boardNote" data-part="board-note">
        三十六格，你的兩顆骰子會指到其中一格。
      </p>

      {/* **Nested map, not `board.flat()` with computed indices.** Backend's own note with the
          payload: if you flatten it, keep the row/column meaning in the markup rather than
          recomputing positions — the transpose this field's shape exists to prevent is exactly
          what index arithmetic reintroduces. Mapping rows then cells emits the right order for
          free, and `data-row`/`data-col` put the coordinates in the DOM so BD-2 can read a cell
          without trusting document order. */}
      <div className="boardGrid" data-part="board-grid" aria-hidden="true">
        {board.map((row, r) =>
          row.map((placeId, c) => {
            const face = faceOf(places, placeId)
            return (
              <span
                key={`${r}-${c}`}
                className="boardCell"
                data-part="board-cell"
                data-row={r + 1}
                data-col={c + 1}
                data-place={placeId}
                data-face={face ?? undefined}
                /* **A cell naming a place the legend does not hold is made loud, not blank.**
                   BD-11: that is a payload bug, and a blank tile reads as a styling one. So it
                   gets its own state rather than falling through to no colour — `faceOf` returns
                   `null` for a place outside the pool rather than defaulting to seat 0, because a
                   wrong colour is a wrong identity claim. */
                data-unknown={face === null ? 'yes' : undefined}
                /* The lit cell lights by OUTLINE only — its fill stays equal to its neighbours of
                   the same place (BD-4). A recoloured cell would read as «that cell's shop
                   changed», which is the one thing the picture must not say. */
                data-lit={lit && r === litRow && c === litCol ? 'yes' : undefined}
              />
            )
          }),
        )}
      </div>

      {/* Colour → shop name, and nothing else. No count, no share, no 「12 格」. */}
      <ul className="boardLegend" data-part="board-legend">
        {seats.map((placeId) => (
          <li key={placeId} data-part="board-legend-row">
            <span className="boardSwatch" data-face={faceOf(places, Number(placeId))} aria-hidden="true" />
            {/* `places` is keyed by string and the cells are ints; the legend is already on the
                string side of that join (BD-12). */}
            <span className="boardLegendName">{places[placeId]}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
