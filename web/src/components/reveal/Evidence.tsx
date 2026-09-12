import { FACES, type Evidence as EvidenceData, type Places } from '@/lib/reveal'
/* §3a. `pct` is the same helper the member's 這一餐 rendered these shares with before the ruling
   moved them here — one definition, so the operator's figure and the payload's cannot part
   company. `touchedLine` stays where it is: its sentence is written for a member («比較少中»), and
   this block is a column of figures for a reader auditing them. */
import { pct, type Preferences } from '@/lib/preferences'

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

/**
 * 甲's bar picture — `spec-weights-picture-2026-09-11.md` §3, the owner 「甲」.
 *
 * **What a contributor is called on this screen, and nothing else reads this map.** The payload
 * names contributors the way the engine does (`preference` · `last_trip` · `weather`); those are
 * `upto.engine`'s own identifiers and they travel in the wire because the operator audits against
 * the database. An unknown contributor **keeps its payload name** rather than being dropped or
 * labelled 「其他」: a fifth contributor landing in `engine/contributors.py` must show up on this
 * drawing as itself, unlabelled and obvious, instead of disappearing into a name that reads
 * finished (D112 — an absence needs a shape, or it reads as a presence).
 */
const LABEL: Record<string, string> = {
  preference: '有人避開',
  last_trip: '上次去過',
  weather: '降雨',
}

/**
 * **The bar's width, and this one line is the whole claim the picture makes.**
 *
 * `spec-weights-picture-2026-09-11.md` §3: «a bar that reads 0.79 must be 0.79 of the track», and
 * WP-6 measures the rendered width against the wire. So the width is the payload's own string,
 * parsed and never rounded for looks, and nothing here recomputes a factor from anything else
 * (§4: a recomputed number and a pinned one disagree the day the formula moves, and then the
 * auditable figure is the wrong one).
 *
 * **The track is 0 → 1 and a factor above 1 is given a shape rather than a full bar.** Nothing
 * on today's build can produce one — `private` and `contextual` both cap at 1 (D45) — but a
 * `commercial` contributor that nudged upward would otherwise draw exactly the same bar as an
 * honest ×1, which is the `fired` mistake one column over. `over` is returned so the row can say
 * so; it is never clamped silently.
 */
function bar(effect: string): { pct: string; over: boolean; at1: boolean } {
  const v = Number(effect)
  if (!Number.isFinite(v) || v < 0) return { pct: '0%', over: false, at1: false }
  return {
    pct: `${(Math.min(v, 1) * 100).toFixed(4)}%`,
    over: v > 1,
    at1: v === 1,
  }
}

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
  counts = null,
}: {
  ev: EvidenceData | null
  places: Places
  winnerId: number | null
  /** A7 — the place id the sweep is lighting during the tumble, or `null`. **It is handed in and
   *  never derived here**: the schedule that guarantees equal dwell and an order uncorrelated with
   *  the winner lives in one place, and a component that decided its own highlight would be a
   *  second, unmeasured one. */
  sweep?: string | null
  /** §3a — the counts that left the member's 這一餐. `null` for a member (the fetch never runs)
   *  and `null` for an operator whose preferences call failed; both draw nothing, because a
   *  footnote must not be able to cost this screen its bars. */
  counts?: Preferences | null
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
                  {/* **A19's 原料未公開／已公開 mark was here and is gone** (2026-08-30,
                      `spec-return-choice.md` §4). The ingredient kind was withdrawn wholesale, so
                      the wire carries no state and the row has none to state. The rule it was
                      built on is still doctrine and is why nothing replaced it with a blank: an
                      absent mark reads as a claim, so the answer to withdrawing the feature was to
                      withdraw the row's second column, not to leave an empty one. */}
                </td>
                {/* tabular-nums and right-aligned, so the column reads as a column */}
                {ev && <td className="evNum">{n}<span className="evOf">/36</span></td>}
                {ev && <td className="evWhy">
                  {/* **甲: the numbers became a drawing** (§3). The rows are `base` then
                      `factors` **in the payload's own order, with no client-side reordering** —
                      the evaluator's ruling, because the picture's only claim is that it is
                      auditable, so row *i* must be `factors[i]` and checkable against the wire by
                      eye. D46's order is private → contextual, which lands as 有人避開 ·
                      上次去過 · 降雨 and is also the honest reading order: what a person chose,
                      then what the world did.

                      The first draft of the spec enumerated the last three backwards while calling
                      it fold order. Nothing here restates an order for exactly that reason. */}
                  <div className="evBars" data-part="factor-bars">
                    {/* 起點 — **its own row and not a `factors` entry.** `fold()` starts at 1 and
                        multiplies, with no `weight_contribution` record behind it; a fabricated
                        起點 row inside `factors` would put a row in the one payload an operator
                        audits that no record backs. It always ran, so it always draws a bar. */}
                    <Bar label="起點" effect={ev.panel[placeId]?.base ?? '1'} fired part="factor-base" />
                    {factors.map((f, i) => (
                      <Bar
                        key={i}
                        /* An unknown contributor keeps its payload name — see `LABEL`. */
                        label={LABEL[f.contributor] ?? f.contributor}
                        effect={f.effect}
                        fired={f.fired}
                        part="factor-row"
                        contributor={f.contributor}
                        /* **The contributor and the factor travel; the REASON does not, unless
                           D13 lets it.** A `represented_member` reason reaches that member alone
                           and nobody else, the operator included — this view audits the
                           arithmetic, not the people. `null` here is the database enforcing that,
                           not this component choosing to be discreet. */
                        reason={f.reason}
                      />
                    ))}
                    {/* The total — the place's own share of the 36, its bar the same fraction, in
                        that place's face colour. It reads `allocation`, the same single source
                        `ALLOC36` is filled from (D91's third clause), so the bar and the grid
                        cannot disagree. */}
                    <Bar
                      label="格數"
                      effect={String(n / 36)}
                      fired
                      part="factor-total"
                      face={FACES[seat % FACES.length]}
                      value={`${n}／36`}
                    />
                  </div>
                </td>}
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* ─── §3a — where the member-side numbers now live ───────────────────────────────────
          `spec-weights-picture-2026-09-11.md` §3a. The owner's ruling took the counts off the
          member's screen because they are 「SDE 需要知道的資訊」; that sentence names a reader, so
          the figures were moved rather than deleted.

          **Below the bars and clearly separated**, per §3a, because the bars are this round's
          arithmetic and these are the corpus the round drew from — two different kinds of fact.

          **`ev &&` as well as `counts &&`, and both guards matter.** `counts` is only ever fetched
          when the response carried accounting, but the operator/member split on this screen is
          decided by what arrived and by nothing else (see `evidenceIn`), so this block is gated on
          the same field every other numeric column here is gated on rather than trusting the
          fetch's own condition one file away.

          **Every figure is the payload's, and the denominators are named in the screen's own
          words** — the rule the member's 這一餐 followed for the same numbers: today's figure is
          false the moment a backfill runs, and a hard-coded one says nothing when it does. */}
      {ev && counts && (
        <dl className="evCounts" data-part="counts">
          <div>
            <dt>帶有分類</dt>
            <dd>
              {(counts.category_coverage.with_category ?? 0).toLocaleString('en-US')}
              <span className="evOf"> / {counts.category_coverage.reference_rows.toLocaleString('en-US')}</span>
              <span className="evOf">（{pct(counts.category_coverage.share)}）</span>
            </dd>
          </div>
          <div>
            <dt>這一輪可提名</dt>
            <dd>{counts.breadth.proposable.toLocaleString('en-US')}</dd>
          </div>
          {/* **One row per avoided category, and nothing when none is set.** No 「目前沒有避開」
              line: D20 holds here too — the surface states, it does not reassure, and an empty
              list already says it. The `touched` figure is this reader's own, because the endpoint
              is member-scoped; it is not the table's, and §3.0 is why that is not a limitation to
              work around. */}
          {counts.avoid_categories.map((a) => (
            <div key={a.value}>
              <dt>{a.value}</dt>
              <dd>
                {a.touched.toLocaleString('en-US')}
                <span className="evOf">（{pct(a.share)}）</span>
              </dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  )
}

/**
 * One row of 甲's picture — `name · track · value`.
 *
 * **`fired` decides the empty track, and `effect` must not** (§3, candidate 16). A padded row and
 * a real one that measured no difference both read ×1, so drawing the absence off the value would
 * report a measurement as an absence the moment any contributor stores a 1.000. `fired: false`
 * draws an empty track and 「—」, because 「上次去過 showing nothing is information」: it says this
 * place was not last week's.
 *
 * **Colour is the ruling's, not a choice made here** (§3's last bullet): below 1 in `hot`, at 1 in
 * `ink`, the total in its place's face colour. No sixth token.
 */
function Bar({
  label,
  effect,
  fired,
  part,
  face,
  value,
  reason = null,
  contributor,
}: {
  label: string
  effect: string
  fired: boolean
  part: string
  face?: string
  /** The total row prints `N／36` rather than the fraction it drew — the same number the 格數
   *  column carries, from the same `allocation`. */
  value?: string
  reason?: string | null
  contributor?: string
}) {
  const { pct, over, at1 } = bar(effect)
  return (
    <div
      className="evBar"
      data-part={part}
      data-contributor={contributor}
      data-fired={fired ? 'yes' : 'no'}
      /* `hot` below 1, `ink` at 1, the face colour on the total. An un-fired row takes none of
         them: there is no factor to colour. */
      data-tone={!fired ? 'none' : face ? 'face' : at1 ? 'ink' : 'hot'}
      data-face={face}
    >
      <span className="evBarName">{label}</span>
      <span className="evBarTrack">
        {/* The width IS the payload's factor (WP-6). An un-fired row draws no fill at all rather
            than a zero-width one, so 「did not run」 and 「×0」 are not the same picture. */}
        {fired && <span className="evBarFill" style={{ width: pct }} data-over={over ? 'yes' : undefined} />}
      </span>
      <span className="evBarValue">
        {fired ? (value ?? `×${effect}`) : <span className="evNone">—</span>}
      </span>
      {reason && <span className="evReason">（{reason}）</span>}
    </div>
  )
}
