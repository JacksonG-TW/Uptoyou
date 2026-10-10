import { faceOf, markOf, type Places } from '@/lib/reveal'
import { PIPS, RED } from './Die'
import { litCell } from '@/lib/board'

/**
 * **The OPERATOR's 36-cell board** (`spec-board-2026-09-11.md`). Since the 籤詩櫃 rebuild
 * (2026-10-10) the member's board is `Cabinet.tsx`: drawers numbered 一…三十六 with their 干支, no
 * marks and no axes. The text below is this component's own history, and still true of it — the
 * operator's instrument keeps the numbered cells, the pip axes and the legend. `drawable` is shared.
 *
 * Originally the member's board — the owner's three 「1」 of 2026-09-11.
 *
 * **What it is:** a 6×6 grid, one cell per outcome, each cell in its place's face colour **and
 * carrying its place's number**, with a legend of number → shop name beneath and one authored line
 * stating the mechanism. Row = die one, column = die two, both 1…6 from the top left, and the axes
 * are drawn as pip faces. A member reads their own two dice off the screen, finds the row and the
 * column, and the number there is the shop. **That sentence is the whole reason this exists;
 * anything that makes it false makes the picture decorative.**
 *
 * **Why a number and not colour alone** (§8, 2026-10-07): four faces cycle, so from the fifth
 * place two shops share a colour and colour stops naming anything. The number is the identity;
 * colour is a second cue. **Digits do one job here** — the place mark — which is why the axes are
 * pips: a 「3」 on the board is never a die value.
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
 * **The grid is `aria-hidden` and the legend is not.** Thirty-six cells announced one by one is
 * noise, and the two things a reader needs — the mechanism and which number is which shop — are
 * the note and the legend, both real text. Same division `ALLOC36` already makes one component
 * over. **For a member since item 2 there is no legend here** (`legend={false}`): the places list
 * beside the board says each row's mark in text (`Evidence`'s sr-only twin), which is the same
 * mark → shop line in the one place it is now drawn.
 */

/** 6 rows, 6 columns. Stated once; the grid's CSS reads the same number. */
const SIDE = 6
const AXIS = [1, 2, 3, 4, 5, 6] as const

/** One axis label: a small die face, pips only, no digit (§8 rule 2). The pip table is the
 *  die's own, so an axis face and a thrown die can never disagree about what 4 looks like. */
function AxisFace({ value, axis }: { value: number; axis: 'row' | 'col' }) {
  return (
    <span className="boardAxis" data-part="board-axis" data-axis={axis} data-value={value}>
      {Array.from({ length: 9 }, (_, i) => (
        <i key={i} className="boardPip" data-on={PIPS[value].includes(i + 1) ? 'yes' : 'no'}
          data-red={RED.has(value) ? 'yes' : 'no'} />
      ))}
    </span>
  )
}

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
export function drawable(board: number[][] | undefined): board is number[][] {
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
  legend = true,
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
  /** **False for the member's first-screen board (item 2):** the places list beside it carries
   *  each shop's mark on its row, so a legend here would say the same thing twice. */
  legend?: boolean
}) {
  if (!drawable(board)) return null

  /* The lit cell, read the ruling's way — `board[die1 − 1][die2 − 1]`, which is the access
     expression the nesting exists to make literal. Nothing is recomputed from `winning_place_id`:
     BD-3b's job is to assert that these two agree, and a client that derived one from the other
     would make that gate unfalsifiable. */
  const cell = litCell(dice)   // `lib/board.ts`, unit-tested there
  const litRow = cell ? cell[0] : -1
  const litCol = cell ? cell[1] : -1

  /* The legend is the pool, in pool order, which is what gives each place its face — `faceOf` keys
     off `Object.keys(places)` so a place wears the same colour here, on the round screen and in the
     operator's grid. Names only (§4). */
  const seats = Object.keys(places)

  return (
    <section className="board" data-part="board">
      {/* States the mechanism once, and states rather than advises (D20). **Names nobody since
          item 2:** it said 「你的兩顆骰子」, which was true for one reader in N — the dice that count
          are the decider's, and the line directly above the board already names them. */}
      <p className="boardNote" data-part="board-note">
        骰子指到哪一格，就是哪一家。
      </p>

      {/* **Nested map, not `board.flat()` with computed indices.** Backend's own note with the
          payload: if you flatten it, keep the row/column meaning in the markup rather than
          recomputing positions — the transpose this field's shape exists to prevent is exactly
          what index arithmetic reintroduces. Mapping rows then cells emits the right order for
          free, and `data-row`/`data-col` put the coordinates in the DOM so BD-2 can read a cell
          without trusting document order. */}
      <div className="boardGrid" data-part="board-grid" aria-hidden="true">
        {/* The corner, then die two's six faces across the top (§8 rule 2). */}
        <span className="boardCorner" />
        {AXIS.map((v) => <AxisFace key={`c${v}`} value={v} axis="col" />)}
        {board.map((row, r) => [
          <AxisFace key={`r${r + 1}`} value={r + 1} axis="row" />,
          ...row.map((placeId, c) => {
            const face = faceOf(places, placeId)
            return (
              <span
                key={`${r}-${c}`}
                className="boardCell"
                data-user-content
                data-part="board-cell"
                data-row={r + 1}
                data-col={c + 1}
                data-place={placeId}
                data-face={face ?? undefined}
                /* **A cell naming a place the legend does not hold is made loud, not blank.**
                   BD-11: that is a payload bug, and a blank tile reads as a styling one. So it
                   gets its own state rather than falling through to no colour — `faceOf` returns
                   `null` for a place outside the pool rather than defaulting to seat 0, because a
                   wrong colour is a wrong identity claim. It carries no number for the same
                   reason. */
                data-unknown={face === null ? 'yes' : undefined}
                /* The lit cell lights by OUTLINE only — its fill stays equal to its neighbours of
                   the same place (BD-4). A recoloured cell would read as «that cell's shop
                   changed», which is the one thing the picture must not say. */
                data-lit={lit && r === litRow && c === litCol ? 'yes' : undefined}
              >
                {markOf(places, placeId)}
              </span>
            )
          }),
        ])}
      </div>

      {/* Number → shop name, and nothing else (§4, §8 rule 3). The swatch carries the same number
          the cells do; the number is an index, never a count — no 「12 格」 anywhere. */}
      {legend && <ul className="boardLegend" data-part="board-legend">
        {seats.map((placeId) => (
          <li key={placeId} data-part="board-legend-row">
            <span className="boardSwatch" data-face={faceOf(places, Number(placeId))} aria-hidden="true">
              {markOf(places, Number(placeId))}
            </span>
            {/* `places` is keyed by string and the cells are ints; the legend is already on the
                string side of that join (BD-12). The mark is said in the text too, so a screen
                reader hears 「1 店名」 the way the eye reads it. */}
            <span className="boardLegendName" data-user-content>
              <span className="sr-only">{markOf(places, Number(placeId))} </span>
              {places[placeId]}
            </span>
          </li>
        ))}
      </ul>}
    </section>
  )
}
