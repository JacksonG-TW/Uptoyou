import type { Roll } from '@/lib/reveal'

/**
 * D108 — every member's pair, listed after the dice land. Owner-ruled 「要」 on 2026-08-19, after
 * 「同一對」 had already settled that the *animation* shows one pair only.
 *
 * **Those two rulings are not in tension and the split is the whole design.** One pair is thrown,
 * because there was one outcome and a screen showing five pairs above one winner invites a reader
 * to invent the rule connecting them. Every pair is *listed*, because they all exist, they all
 * derive from the same seed, and hiding them would make the commitment unfalsifiable in the one
 * place a person could check it. **The animation is the moment; this is the receipt.**
 *
 * **Evidence register, and no animation at all.** It does not fade, rise, stagger or count up. A
 * number that arrives with a flourish is asking to be admired; these are here to be checked against
 * the seed printed directly underneath them, and the register that says so is the one the operator
 * table already uses.
 *
 * **Both states render it identically** — it is not accounting. A pair is a member's own die roll,
 * carries no place, no weight and no share, and D55 was narrowed to *proposal* authorship on the
 * same day precisely because a roll is performed visibly on purpose. So there is nothing here to
 * gate on the operator credential, and gating it would imply there was.
 *
 * **Every seat is filled at close, whoever tapped.** Backend's change of 2026-08-19: the round
 * closes on the first tap, and all pairs are derived from the seed rather than from anyone's
 * action. So a member who never touched the screen still has a pair here, and that is the honest
 * rendering of a mechanism where tapping reveals rather than throws.
 */
export default function Pairs({ rolls }: { rolls: Roll[] }) {
  if (rolls.length === 0) return null
  return (
    <section className="pairs" data-part="pairs">
      <h2 className="pairsH">每個人的骰子</h2>
      <ul className="pairRows">
        {rolls.map((r, i) => {
          const shown = r.die1 !== null && r.die2 !== null
          return (
            <li
              key={r.member_id}
              className="pairRow"
              data-roll-seat={i + 1}
              data-roll-state={shown ? 'rolled' : 'waiting'}
              data-counts={r.counts ? 'yes' : 'no'}
            >
              {/* A missing nickname renders as the seat rather than as `undefined` — the same
                  insurance the round screen carries, for the same reason. */}
              <span className="pairName" data-user-content>{r.nickname || `座位 ${i + 1}`}</span>
              <span className="pairDice">{shown ? `${r.die1} · ${r.die2}` : '—'}</span>
            </li>
          )
        })}
      </ul>
      {/* **It says what the marked row does not, rather than repeating the line above it.** Under
          D111's composition the decider is already named at the top of this column, 400 px up; a
          second sentence naming them again is the same fact twice and reads as the screen not
          trusting the reader. What is NOT stated anywhere else is where the other pairs came
          from — and that is the sentence that makes the seed printed underneath mean something. */}
      {rolls.some((r) => r.counts) && (
        <p className="pairsNote">每一對都由同一顆種子產生，開局時就固定了。</p>
      )}
    </section>
  )
}
