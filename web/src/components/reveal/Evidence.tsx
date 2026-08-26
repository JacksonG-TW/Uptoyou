import { FACES, type Evidence as EvidenceData, type Places } from '@/lib/reveal'

/**
 * A3's second half — `TABLE` and `ALLOC36`, **operator state only** (`D105`, `design.md` §4b).
 *
 * **This is an addition, not a toggle.** It renders only when the response carried the accounting,
 * which happens only for a credential issued with `--operator`. Nothing in the member state moves,
 * resizes or re-flows when it is present: it appends below the answer region, so a person who has
 * seen both recognises the second as the first.
 *
 * **`D91`'s third clause: the table and the grid are drawn from ONE source.** Both read
 * `allocation` — the grid colours a cell per outcome, the table prints the same count as `n/36`.
 * Two derivations of "the same" shares is how a grid comes to disagree with the table beside it,
 * and a disagreement there destroys precisely the credibility both exist to build. So `share()`
 * exists once and both callers use it.
 *
 * **No 「示意」 caveat, and its absence is deliberate** (§5). The grid *was* an illustration on the
 * home screen and is not one here — it is this round's real allocation. A caveat left on a true
 * figure is worse than no caveat, because it teaches the reader to discount a real number.
 */

/** The 36 outcomes, in pool order, each carrying the face of the place that holds it. Built from
 *  `allocation` alone so the grid cannot drift from the table. */
const COLS = 6

function cells(
  ev: EvidenceData,
  places: Places,
): { face: string; placeId: string; startsRun: boolean; col: number }[] {
  const out: { face: string; placeId: string; startsRun: boolean; col: number }[] = []
  Object.keys(places).forEach((placeId, seat) => {
    const n = ev.allocation[placeId] ?? 0
    const face = FACES[seat % FACES.length]
    for (let i = 0; i < n; i++) {
      out.push({
        face,
        placeId,
        // **The boundary is drawn on the first cell of each run, not between colours.** With more
        // than four places `FACES` cycles, so colour alone stops identifying a place — but the grid
        // is filled in pool order and the table lists in pool order, so the Nth *run* is the Nth
        // row whatever colour it wears. Bounding the runs makes that reading available; leaving
        // them unbounded is what let two same-coloured runs read as one 15-cell block.
        startsRun: out.length > 0 && i === 0,
        col: (out.length % COLS) + 1,
      })
    }
  })
  return out
}

export default function Evidence({
  ev,
  places,
  winnerId,
  sweep = null,
}: {
  ev: EvidenceData | null
  places: Places
  winnerId: number | null
  /** A7 — the place id the sweep is lighting during the tumble, or `null`. **It is handed in and
   *  never derived here**: the schedule that guarantees equal dwell and an order uncorrelated with
   *  the winner lives in one place, and a component that decided its own highlight would be a
   *  second, unmeasured one. */
  sweep?: string | null
}) {
  const grid = ev ? cells(ev, places) : []
  const seats = Object.keys(places)

  /* **The state follows the payload, like everything else on this screen.** It was the literal
     string `operator`, so a member's DOM announced itself as the operator's while carrying none of
     the operator's numbers — a reader (or a gate) checking the attribute got the wrong answer, and
     telling the two states apart is the one thing it is for (evaluator 2026-08-26). `ev` is null
     for a member because nothing arrived; that absence is the same signal every numeric column
     here is already gated on. */
  return (
    <section className="evidence" data-part="evidence" data-state={ev ? 'operator' : 'member'}>
      {/* ALLOC36 — beside the table as evidence, never above it as decoration. Cells are ≥ 36 px
          square (§3's rescue floor): below that the colour blocks stop being countable and the
          figure reads as a texture rather than as thirty-six things. */}
      {/* **Option A, owner-ruled 2026-08-19 (D105 at `d94b54f`): the grid is hidden once the pool
          exceeds four, and the table is always kept.** `FACES` has four colours and the `CHIP` is
          keyed to the cycle, so at five places two runs wear the same colour and a reader counting
          by colour gets a number no table row contains — measured `[7,7,7,15]` against an
          allocation of `[7,7,7,7,8]`. **A figure that cannot say which place holds a cell is not
          weaker evidence, it is a false statement**, and the table carries the same allocation
          correctly at any size. The hairline was built and measured first, per his ruling, and
          failed: it separates *adjacent* runs, and adjacent seats never share a colour.

          The cost, stated rather than hidden: on five devices — the product's canonical case — the
          most striking operator figure is absent. Eight faces (option B) is parked, not rejected;
          it is what restores the figure, because what broke is identity. */}
      {ev && seats.length <= FACES.length && (
      <div className="alloc36" data-part="alloc36" aria-hidden="true">
        {grid.map((c, i) => (
          <span
            key={i}
            className="allocCell"
            data-face={c.face}
            // A run that starts mid-row takes a leading edge; one that starts at the left margin
            // takes a top edge instead, because a left border there would sit on the grid's own
            // outer edge and say nothing.
            data-run-start={c.startsRun ? (c.col === 1 ? 'top' : 'left') : undefined}
          />
        ))}
      </div>
      )}

      <table className="evTable" data-part="table">
        <thead>
          <tr>
            <th scope="col" className="evPlace">提名</th>
            {ev && <th scope="col" className="evNum">格數</th>}
            {/* 「權重來源」 rather than 「理由」: what this column prints is the contributor and the
                factor it applied. A *reason* is a sentence, and D13 lets one travel only at `table`
                visibility — so most rows would have carried a column heading promising something
                the payload is not allowed to hand over. */}
            {ev && <th scope="col" className="evWhy">權重來源</th>}
          </tr>
        </thead>
        <tbody>
          {seats.map((placeId, seat) => {
            const n = ev?.allocation[placeId] ?? 0
            const factors = ev?.panel[placeId]?.factors ?? []
            return (
              <tr
                key={placeId}
                data-part="table-row"
                data-sweep={sweep === placeId ? 'on' : undefined}
              >
                <td className="evPlace" data-won={String(placeId) === String(winnerId) ? 'yes' : 'no'}>
                  {/* CHIP — identity, never quantity, and **operator only**. It exists to key a row
                      to its cells in `ALLOC36`; with no grid to key to, it would be a colour that
                      means nothing, and above four places it would repeat and mean something
                      wrong. */}
                  {ev && <span className="chip" data-face={FACES[seat % FACES.length]} />}
                  {/* **The name is laid out twice and painted once**, and `reveal.css` explains
                      why: the winner's mark is a real 900 weight that appears at the landing
                      frame, and on a name that ends near a line's edge a weight change adds a
                      line. Measured at 1440: a space-breaking name at the boundary grew the row
                      by 29.64 px. The ghost in `::before` reserves the BOLD box from first paint,
                      so the visible text can change weight inside a box that was never the
                      regular weight's to begin with. `data-name` feeds the ghost; the one real
                      text node is the one below. */}
                  <span className="evName" data-name={places[placeId]}>
                    <span className="evNameInk">{places[placeId]}</span>
                  </span>
                </td>
                {/* tabular-nums and right-aligned, so the column reads as a column */}
                {ev && <td className="evNum">{n}<span className="evOf">/36</span></td>}
                {ev && <td className="evWhy">
                  {factors.length === 0
                    ? <span className="evNone">—</span>
                    : factors.map((f, i) => (
                        <span key={i} className="evFactor">
                          {/* **The contributor and the factor travel; the REASON does not, unless
                              D13 lets it.** A `represented_member` reason reaches that member alone
                              and nobody else, the operator included — this view audits the
                              arithmetic, not the people. `null` here is the database enforcing
                              that, not this component choosing to be discreet. */}
                          {f.contributor} ×{f.effect}
                          {f.reason && <span className="evReason">（{f.reason}）</span>}
                        </span>
                      ))}
                </td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </section>
  )
}
