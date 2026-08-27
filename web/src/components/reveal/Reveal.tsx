import { useCallback, useEffect, useRef, useState } from 'react'
import Die from './Die'
import Evidence from './Evidence'
import Field from './Field'
import Pairs from './Pairs'
import { m, useReducedMotion } from '@/lib/motion'
import {
  device, evidenceIn, faceOf, fetchRaw, signTrip,
  type Device, type Evidence as EvidenceData, type MemberReveal, type Trip,
} from '@/lib/reveal'

/**
 * A3 — the reveal, **member state**, built to `spec-reveal-two-states.md` §1–§4 and `design.md` §4b.
 *
 * **This component cannot render the accounting, and that is structural rather than careful.** It is
 * typed on `MemberReveal`, whose fields are the API's own whitelist — `round_id · status · dice ·
 * sum · winning_place_id · places · trip`. There is no `weights`, no `allocation` and no `panel` in
 * the type, so there is nothing here to hide, gate or forget to gate. §8's order says member first
 * for exactly this reason: **build the operator state and subtract, and a field survives in the
 * member payload.** The operator state will be an addition in its own component.
 *
 * **What is deliberately absent from member state (§1a), each an assertion to test for rather than a
 * feature to omit:** no per-place share, count, percentage or fraction — in any element, attribute,
 * `title` or `aria-label`; no reason and no channel label; no count of contributors; **no operator
 * affordance of any kind — no disabled control, no mode hint, because a disabled door is a door**;
 * and no promise of a member-verifiable audit, including any paraphrase of the removed line
 * 「每一個數字都查得到出處。」
 *
 * **`D91` is honoured by construction:** the result is decided by the server before a frame animates,
 * the answer is genuinely absent from the screen mid-tumble via `opacity` while its box is held, and
 * nothing here changes a layout box at any point in the sequence.
 */

/** How long one row should hold, near enough. The real dwell is derived from it and from the row
 *  count so that every row gets exactly the same number of visits of exactly the same length —
 *  this is the target the derivation rounds to, never a duration anything is scheduled on. */
/**
 * **The hold, in milliseconds** — see `staged` below. A timer is right here and nowhere else on
 * this screen: it does not measure a thing that is happening, it *is* the thing that is happening,
 * and its whole content is that nothing else is.
 *
 * **1000 since the owner watched it — D109's amendment, evaluator's number (2026-08-26).** He
 * passed the tumble and asked for one thing: 「顯示最終骰子結果停頓一下再縮小」. The hold was not
 * missing, it was too short to read as a pause — 500 measured **386–468 ms on screen**, because the
 * timer runs from composed stillness and gives back whatever confirming stillness cost. So this is
 * a number that failed a person rather than an instrument, and the fix is the number, not the
 * mechanism: the constraints below are unchanged and the shrink's own spring is untouched (the ask
 * was the pause, ruled by the evaluator, not a slower retreat).
 *
 * **500 since `RV-20` (2026-08-20), and that history is still the point.** 700 was tuned against a
 * signal that fired 637 ms early, and then measured against an instrument that watched one cube
 * inside a group that could still be moving. **A number tuned twice against instruments that missed
 * a mover has no claim left**, so it was re-ruled from a corrected measurement rather than nudged —
 * and the same discipline applies now: 1000 comes from a measurement of what 500 actually put on
 * the screen, not from doubling a number that felt small. The paragraphs below are the original 700
 * argument, kept because the reasoning about the tail is still true and only the number has moved.
 *
 * **700 and not the prototype's 380, and the number came from frames rather than from taste.** The
 * die reports itself landed when `motion`'s animation resolves, and that resolution runs
 * **290–350 ms ahead of the element actually coming to rest** — measured four ways across four
 * builds, and not fixable from this side: rest thresholds shortened the tail, a zero-duration snap
 * was out-run by the animation still in flight, re-sequencing the springs did not close it, and
 * watching the computed transform for stillness sees style writes rather than paint.
 *
 * So the recording settled it. At 380 the whole-frame pixel diff went
 * `…13078 · 583 · 8350 · 8123 · 771 · 133754…` — **one still frame, then more movement, then the
 * flood.** The beat existed on paper and not on the screen. The tail is ~300 ms, so a beat a person
 * can see needs the hold to be that plus the beat.
 *
 * **What this does NOT paper over:** the retreat has never begun while the dice were settling — the
 * prohibition half of D111's rule held at 380 and holds now. What was missing was the positive
 * half, the visible pause, and that is what this buys.
 */
const HOLD_MS = 1000

/**
 * **The stage arrives in three steps, not one — D109's second amendment (owner, 2026-08-26:
 * 「有點突兀，像是突然就出現結果」), evaluator's numbers under D101's delegation.**
 *
 * The complaint was not about any single movement. Everything downstream of `staged` fired on the
 * same frame — the retreat, the flood and the answer at once — so the screen changed completely
 * between two frames and gave the eye three things to follow and no order to follow them in.
 * **The fix is sequence, not slowness**: the same movements, in the order a person would read
 * them, each starting as the previous one finishes.
 *
 *   ① `staged`   +0 ms     the dice retreat to the read position (the existing spring, ~900 ms)
 *   ② `flooded`  +900 ms   the ground takes the winner's colour; the list settles into it
 *   ③ `answered` +1400 ms  decider · winner · sentence · act rise; the winning row goes bold
 *
 * **The offsets are from `staged`, and `staged` still flips at the hold's end** — `RV-20` measures
 * that edge and is untouched by everything here.
 *
 * **Why timers and not the retreat's own completion callback.** `motion` resolves a spring
 * **290–350 ms before the element is actually at rest** — measured four ways across four builds,
 * and it is what `HOLD_MS`'s note above is about. So `onAnimationComplete` would start the flood
 * while the dice were still visibly moving, which is precisely the constraint `RV-21` gates
 * (「group at rest before the colour begins」). A timer at the spring's *measured* rest is the
 * honest instrument here, and the dishonest-looking one would have been the callback.
 *
 * **Rejected: `transition-delay` in CSS.** Fewer moving parts, and it puts the sequence where the
 * durations already live. But then no DOM signal marks ② and ③, so the gate has to infer them from
 * paint, and reduced motion has to zero every delay separately — a rule that decays the first time
 * someone adds a fourth element. Explicit states cost two timers and give the evaluator two
 * attributes to read.
 */
const FLOOD_AFTER_STAGED_MS = 900
const ANSWER_AFTER_STAGED_MS = 1400

/** **How long a total absence of animation frames means the sequence is not coming.** Not a guess
 *  at how long the dice take — that number is what `RV-19` forbids. Two seconds of *silence* is far
 *  past any frame gap a running browser produces (a 60 Hz tab pings every ~16 ms; even a heavily
 *  throttled one is well inside it), so reaching it means frames have stopped, which is the only
 *  condition this failsafe exists for. */
const WATCHDOG_MS = 2000

/**
 * The dice group's two places, as transforms from its resting CSS position.
 *
 * `ROLLING` puts it centred and full size; `STAGED` is the identity, which is the left column at
 * `--stage-pad`. **Derived from the stylesheet's own numbers rather than typed twice** — the
 * group is 2×300 + 56 = 656 wide, so centring it in a 1440 canvas puts its left edge at 392, and
 * it sits 114 px lower while it tumbles. Change the composition in CSS and these two lines are the
 * ones that have to move with it; there is no third copy.
 */
const ROLLING = { x: 288, y: 114, scale: 1 }
const STAGED = { x: 0, y: 0, scale: 0.42 }

const TARGET_DWELL_MS = 120

/** **The floor, and it is the evaluator's instrument that sets it, not taste.** The tumble is
 *  gated from video at ~25 fps, so a frame is 40 ms; a dwell under two frames cannot be told apart
 *  from a dropped frame, and *equal dwell per row* stops being a claim anyone can confirm or
 *  refute. Their floor is 80 ms and this is 90, because a schedule that lands exactly on an
 *  instrument's limit is one rounding away from being unmeasurable. */
const FLOOR_DWELL_MS = 90

/** The tumble's length, read from `--tumble` on the reveal's own element rather than typed here.
 *  The CSS animation and this schedule must divide the *same* number: a second copy drifting by
 *  even 50 ms truncates the sweep's last cycle, and a truncated cycle is one row visited fewer
 *  times than its neighbours — §0c's unequal dwell, arriving as a rounding error instead of as a
 *  decision. Falls back to the value in `reveal.css` if the property is ever absent. */
function tumbleMs(el: HTMLElement | null): number {
  const raw = el ? getComputedStyle(el).getPropertyValue('--tumble').trim() : ''
  if (raw.endsWith('ms')) return parseFloat(raw) || 1400
  if (raw.endsWith('s')) return (parseFloat(raw) || 1.4) * 1000
  return 1400
}

/** Fisher–Yates, on a copy. Used for decoration and for nothing else — the roll itself was decided
 *  by the server before this file ran, which is the whole of `D91`. */
function shuffled<T>(xs: readonly T[]): T[] {
  const a = xs.slice()
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

/**
 * The sweep's order — **§0c's three constraints, built rather than tuned.**
 *
 * **Equal visits and equal dwell, exactly.** The schedule is whole cycles of a permutation of every
 * row, so each row is visited the same number of times; the dwell is the tumble divided by the step
 * count, so each visit is the same length. Not *approximately* — a schedule that merely aims at
 * equality has to be measured to be believed, and `RV-13` is an honesty line rather than a
 * tolerance.
 *
 * **The order is uniformly random and the winner is not consulted.** This function is not given the
 * winning place and could not favour it if it tried. **The tempting extra step — forbidding the
 * winner from the final position, so the sweep visibly does not stop on the answer — is refused,
 * and it is worth saying why**: that is also a correlation with the winner, merely negative, and a
 * gate looking for *does the order correlate* would find it just as surely. Zero correlation is a
 * uniform shuffle and nothing else. Landing last on the winner one roll in `n` is what chance looks
 * like, and engineering that away would be the lie the constraint exists to prevent.
 *
 * The one adjustment: a row is never allowed to appear twice in a row across a cycle boundary,
 * which would read as a single double-length dwell. That is a fact about consecutive positions and
 * carries no information about which row it is.
 */
function sweepOrder(ids: readonly string[], total: number): string[] | null {
  if (ids.length < 2) return null
  // **A pool too large to sweep honestly is not swept, and the surface says so.** One whole cycle
  // at the floor needs `n × 90 ms`; past about fifteen places that exceeds the tumble, and the
  // three ways out are all worse than stopping. Going faster makes the dwell unmeasurable — the
  // effect would still *look* fine, which is the point. Visiting a subset makes the visits
  // unequal, which is the constraint itself. Stretching the tumble makes the animation's length a
  // function of the pool size, so a big round takes visibly longer to decide and the reader has
  // every reason to think the size mattered. **And a strobe across twenty rows in 1.4 s does not
  // read as choosing anyway** — it reads as noise, so the honest option is also the better-looking
  // one, which is not always how this goes.
  if (ids.length * FLOOR_DWELL_MS > total) return null
  const fits = Math.floor(total / (FLOOR_DWELL_MS * ids.length))
  const wanted = Math.round(total / (TARGET_DWELL_MS * ids.length))
  const cycles = Math.max(1, Math.min(wanted, fits))
  const order: string[] = []
  for (let c = 0; c < cycles; c++) {
    const next = shuffled(ids)
    if (order.length > 0 && next[0] === order[order.length - 1]) {
      ;[next[0], next[1]] = [next[1], next[0]]
    }
    order.push(...next)
  }
  return order
}

export default function Reveal({ roundId }: { roundId: number }) {
  const [dev] = useState<Device | null>(device)
  const [data, setData] = useState<MemberReveal | null>(null)
  const [landed, setLanded] = useState(false)
  const [error, setError] = useState('')
  const [trip, setTrip] = useState<Trip>(null)
  /** `null` for a member, and for a member it is null because **nothing arrived** — not because
   *  this component declined to read something that did. D105's whole point. */
  const [evidence, setEvidence] = useState<EvidenceData | null>(null)
  const [signing, setSigning] = useState(false)
  const reduce = useReducedMotion()
  /** Which row the sweep is lighting, or `null`. A place id, never an index — the row order is the
   *  pool's and an index would silently re-point if it ever changed. */
  const [sweep, setSweep] = useState<string | null>(null)
  /** `animation` on the normal path, `fallback` if the failsafe below had to land the screen.
   *  **Published on the element rather than kept private**: the two paths differ in timing, and a
   *  measurement taken on the second one while believing it was the first is exactly the reading
   *  that gets a defect reported against the wrong thing. */
  const [landedBy, setLandedBy] = useState<'animation' | 'fallback' | 'reduced' | null>(null)
  /**
   * **D111's second stage, and the gap between it and `landed` is the whole ruling.**
   *
   * `landed` means *the dice have stopped*. `staged` means *the screen has reacted to that*. They
   * are separated by a deliberate beat, because a screen that begins rearranging while the dice are
   * still settling has reacted before the answer was final — the animation asserting something it
   * does not yet have, which is `D91` word for word.
   *
   * **So the flood, the retreat and the name all hang off `staged`, and nothing hangs off `landed`
   * except the beat itself.** The owner's prototype makes the pause visible on purpose; the
   * evaluator's instruction was not to tighten it away as dead time, and the reason it is not dead
   * time is that it is the only moment on this screen where the result is settled and nothing has
   * claimed it yet.
   */
  const [staged, setStaged] = useState(false)
  /** ② and ③ of the staged sequence — see `FLOOD_AFTER_STAGED_MS`. Separate booleans rather than
   *  one enum because each is read on its own by a different part of the tree, and a comparison
   *  like `stage >= 'flooded'` on a string union is the kind of ordering nobody can see is wrong. */
  const [flooded, setFlooded] = useState(false)
  const [answered, setAnswered] = useState(false)
  /** Why the sweep did not run, when it did not. Published on the element for the same reason
   *  `landedBy` is: an absent effect and a broken effect look identical in a recording. */
  const [skipped, setSkipped] = useState<'one-row' | 'too-many-rows' | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const root = useRef<HTMLElement | null>(null)

  /** **The dice landing is observed, not predicted.** `animationend` from the cube's own `tumble`
   *  is the moment the tumble is over; a `setTimeout` matching the CSS duration is a second clock
   *  that agrees until something makes it not — a throttled tab, a slower device, an edited
   *  duration — and when it disagrees the answer appears over a die still moving. Both dice fire
   *  it and the first one wins, because they run the same animation for the same length. */
  /** Restart the watchdog. Called by every `Die` on every animation frame it is alive for; the
   *  screen lands on `fallback` only if this stops being called entirely. */
  const beat = useCallback(() => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => land('fallback'), WATCHDOG_MS)
  }, [])

  /** When the composed image actually went still, in `performance.now()` terms. The beat is
   *  measured from THIS, not from the moment the observation finished — confirming stillness costs
   *  three frames, and a hold started at the confirmation is systematically ~120 ms long, which put
   *  the measured beat at the top of its own tolerance by construction. */
  const stillAt = useRef<number | null>(null)

  const land = useCallback((by: 'animation' | 'fallback' | 'reduced', at?: number) => {
    if (at != null && stillAt.current === null) stillAt.current = at
    window.clearTimeout(timer.current)
    setLanded((was) => {
      if (!was) setLandedBy(by)
      return true
    })
  }, [])

  useEffect(() => {
    if (!dev) return
    let live = true
    fetchRaw(dev, roundId)
      .then((raw) => {
        if (!live) return
        const d = raw as MemberReveal
        setData(d)
        setTrip(d.trip)
        setEvidence(evidenceIn(raw))
        // Demo scaffolding: the switcher's 開獎 stop needs a round to point at and there is no
        // endpoint for "this circle's latest". Recording the one actually looked at is the
        // cheapest honest answer, and it disappears with the switcher.
        localStorage.setItem('upto_last_round', String(roundId))
        // **Reduced motion lands instantly and still lands** (§5 rule 3: the end states apply, the
        // transitions do not). Not "no animation and no reveal" — the person still gets the answer.
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) land('reduced')
        // **The failsafe is a watchdog on the dice's own heartbeat, not a race against them
        // (`RV-19`, ruled 2026-08-20).** If the sequence never runs — a background tab, an
        // animation that never started, a chain that threw — the reveal would hang on a screen
        // whose whole purpose is to show an answer it is already holding. So it still exists.
        //
        // **What it must never do is beat a healthy sequence, and the old one did on every run.**
        // It fired at `--tumble + 250` = 1650 ms; since the springs the real sequence ends at
        // ~2190 ms, so `land('animation')` never once spoke and the hold began 637 ms before the
        // dice stopped. Measured from the DOM, twice. The comment above it asserted the opposite
        // — true when `--tumble` described a CSS keyframe that really was the whole animation, and
        // silently false from the moment the springs replaced it.
        //
        // **A bigger constant would be the same bug waiting for the next spring change.** This
        // measures *silence* instead: each `Die` pings once per animation frame while its sequence
        // is alive, every ping restarts the clock, and only `WATCHDOG_MS` with no ping at all can
        // land the screen. That is derived from frames arriving, so no duration, spring or stage
        // added later can outgrow it.
        else beat()
      })
      .catch((e: Error) => { if (live) setError(e.message || '讀取失敗') })
    return () => { live = false; window.clearTimeout(timer.current) }
  }, [dev, roundId])

  /**
   * The sweep. **It starts with the tumble and it runs until the dice actually land** — not until
   * `--tumble` elapses, which is a different moment and was the defect (`RV-13`, evaluator
   * 2026-08-26, measured on 11/11 rolls).
   *
   * **The two clocks, and why the schedule could not have been right.** `--tumble` is a CSS
   * duration, 1400 ms; the dice land when `motion`'s spring resolves, ~2.5–2.7 s from load. The
   * schedule was built to fill `--tumble` exactly and then stopped, leaving the last row it
   * happened to be on lit for the remaining 1.0–1.4 s — one row dwelling four to five times longer
   * than every other, which is §0c's equal-dwell constraint failing by construction rather than by
   * tuning. The comment here used to say 「the last step ends as the dice stop」; it was describing
   * an intention, and the instrument found that no run had ever done it.
   *
   * **The fix is to keep stepping.** When the schedule runs out it is extended by another whole
   * shuffled cycle at the same dwell, so every visit is the same length whenever the spring
   * happens to resolve. `--tumble` stops being the sweep's length and becomes only what sets the
   * dwell, which is the one thing it was ever measuring.
   *
   * **Its cost, stated rather than hidden: the final cycle is cut off wherever landing falls, so
   * across a whole roll some rows are visited once more than others (±1).** Equal *visits* is
   * therefore approximate now where it used to be exact. That is the right trade and not merely
   * the convenient one: the truncation point is set by a spring that has never seen the pool, so
   * the extra visit carries no information about which row wins — the honesty constraint is about
   * correlation with the winner, and there is none. Equal *dwell*, which is what a person can
   * actually see and what `RV-13` measures, is now exact instead of broken.
   *
   * **Rejected: clearing the highlight when the schedule ends.** It also fixes the dwell, and it is
   * one line. But it leaves 1.0–1.4 s of tumbling dice beside a dead list — the sweep would stop
   * before the mechanism it is supposed to be in sync with, and 「in sync」 is the other half of the
   * same constraint. A fix that trades one half of a rule for the other is not a fix.
   *
   * **A row lit at the moment of landing would be the animation pointing at an answer**, which is
   * the one thing §0c forbids however random the order was that got it there. So `landed` clears it
   * unconditionally, before anything else is read — and that is what ends the sweep now.
   */
  useEffect(() => {
    if (!data || landed) { setSweep(null); return }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ids = Object.keys(data.places)
    const total = tumbleMs(root.current)
    const order = sweepOrder(ids, total)
    // **Never a silent cap.** A recording with no sweep in it should say which of the two it is —
    // an effect that was skipped by rule, or an effect that was built and does not work.
    if (!order) { setSkipped(ids.length < 2 ? 'one-row' : 'too-many-rows'); return }
    setSkipped(null)
    // The dwell is still `--tumble` divided by one schedule's worth of steps: the token sets how
    // fast the sweep moves, and nothing else reads it. The length is set by `landed`.
    const dwell = total / order.length
    let i = 0
    setSweep(order[0])
    const h = window.setInterval(() => {
      i += 1
      // Out of schedule and the dice are still going: extend by another whole cycle rather than
      // stop. Same boundary rule as `sweepOrder`'s — a row may not open a cycle it just closed,
      // which would read as one double-length dwell and undo what this effect is here to fix.
      if (i >= order.length) {
        const next = shuffled(ids)
        if (next[0] === order[order.length - 1]) {
          ;[next[0], next[1]] = [next[1], next[0]]
        }
        order.push(...next)
      }
      setSweep(order[i])
    }, dwell)
    return () => window.clearInterval(h)
  }, [data, landed])

  /** The beat. Long enough to read as a stop rather than as a stutter — the prototype's own
   *  proportion, 6% of a 6.4 s loop. Reduced motion has no stages to separate, so it goes straight
   *  through. */
  useEffect(() => {
    if (!landed) return
    // **Reduced motion applies all three at once, instantly** (evaluator's ruling, 2026-08-26):
    // there is no tumble to separate them from and no sequence to read, so the end state is the
    // whole animation — §5 rule 3's 「the end states still apply」.
    if (landedBy === 'reduced') { setStaged(true); setFlooded(true); setAnswered(true); return }
    // **The beat runs from composed stillness, so it is `HOLD_MS` on the screen and not
    // `HOLD_MS` plus whatever the instrument cost.** Clamped at zero: if confirming took longer
    // than the whole beat the answer is *stage now*, never *stage in the past*.
    const spent = stillAt.current === null ? 0 : performance.now() - stillAt.current
    const h = window.setTimeout(() => setStaged(true), Math.max(0, HOLD_MS - spent))
    return () => window.clearTimeout(h)
  }, [landed, landedBy])

  /** ② and ③, measured from `staged` itself rather than from the hold — so a long confirm eats
   *  into the hold (which is what `HOLD_MS − spent` is for) and never into the sequence a person
   *  is watching. Both clear on unmount and on any re-run, so a second roll cannot leave a timer
   *  from the first one alive. */
  useEffect(() => {
    if (!staged || answered) return
    const a = window.setTimeout(() => setFlooded(true), FLOOD_AFTER_STAGED_MS)
    const b = window.setTimeout(() => setAnswered(true), ANSWER_AFTER_STAGED_MS)
    return () => { window.clearTimeout(a); window.clearTimeout(b) }
  }, [staged, answered])

  const sign = useCallback(async () => {
    if (!dev || signing) return
    setSigning(true)
    try {
      setTrip(await signTrip(dev, roundId))
    } catch (e) {
      setError((e as Error).message || '簽不上')
    } finally {
      setSigning(false)
    }
  }, [dev, roundId, signing])

  if (!dev) {
    return (
      <main className="reveal" data-screen="reveal">
        <p className="revealNote">這台裝置還沒有鑰匙。</p>
      </main>
    )
  }
  if (error) {
    return (
      <main className="reveal" data-screen="reveal">
        <p className="revealErr" data-part="reveal-error">{error}</p>
      </main>
    )
  }

  const face = data ? faceOf(data.places, data.winning_place_id) : null
  /** Derived from the seat marked `counts`, falling back to `deciding_member` only if no seat is
   *  marked — a payload that predates A6 has neither, and the line simply does not render. */
  const decider = data
    ? (data.rolls?.find((r) => r.counts)?.nickname ?? data.deciding_member?.nickname ?? '')
    : ''
  const winner = data && data.winning_place_id !== null
    ? data.places[String(data.winning_place_id)]
    : ''

  return (
    // The flood (§5 rule 1) — the winning place's own face colour becomes the whole ground, over
    // .45s ease-out. `data-face` carries it; the colour lives in CSS, so no palette value is
    // written in a component.
    <main
      ref={root}
      className="reveal"
      data-screen="reveal"
      data-state={landed ? 'landed' : 'rolling'}
      data-stage={answered ? 'answered' : flooded ? 'flooded' : staged ? 'staged' : 'rolling'}
      data-landed-by={landedBy ?? undefined}
      data-sweep-skipped={skipped ?? undefined}
      // **The flood moves with the stage, not with the stop.** Flooding the instant the dice
      // settle would put a full-screen colour change inside the beat, and the beat's entire
      // content is that nothing has reacted yet. The screen reacts after it — and since D109's
      // second amendment it reacts in three steps, so the colour waits for the dice to be at
      // rest (②) instead of moving with them.
      //
      // **The list settles on this same cue and needs no gate of its own**: the flood repaints
      // the ground and `color: inherit` carries every row with it. One attribute, one moment.
      data-face={flooded && face ? face : undefined}
    >
      {/* The ground's printed pair belongs to the flood, not to the retreat — it is the colour
          arriving, drawn in the flood's own darker step. */}
      <Field dice={data?.dice} staged={flooded} />

      <div className="stage">

      {/* **The dice mount only once the round is known, and that closed a latent bug.** They used
          to render immediately with a placeholder 1 and start tumbling, so the landing angle was
          re-targeted mid-flight when the real value arrived. Nothing showed for it, because the CSS
          re-resolved and the die still landed on the right face — a throw aimed at the wrong number
          that corrected itself invisibly. `.dice` holds its box from `min-height`, so waiting costs
          no layout.

          `data-dice-state` is set from the die's own settle completing rather than from a timer:
          **a spring has no duration anyone outside it can know**, which is precisely why it feels
          different from an ease, and the die calls back when its spring has decayed onto the
          face. */}
      {/* **The group is anchored where it ENDS and transformed to where it starts.** The landed
          position is the CSS one — left column, x 104 — and 「centred and large」 is a transform
          away from it. That way the resting composition is what the stylesheet says, and the
          animation is the only thing that has to be undone; the other way round leaves the final
          frame depending on an animation having run.

          Transform only, so the retreat reflows nothing: the name's box, the list's box and the
          bar are exactly where they were before the dice moved. */}
      <m.div
        className="group"
        data-part="dice-group"
        animate={reduce ? { x: 0, y: 0, scale: 1 } : staged ? STAGED : ROLLING}
        transition={
          reduce
            ? { duration: 0 }
            : { type: 'spring', stiffness: 140, damping: 22, mass: 1.1 }
        }
      >
        <div className="dice" data-part="dice" data-dice-state={landed ? 'landed' : 'tumbling'}>
          {data && (
            <>
              <Die value={data.dice[0]} seat={0} onLanded={(at) => land('animation', at)} onProgress={beat} />
              <Die value={data.dice[1]} seat={1} onLanded={(at) => land('animation', at)} onProgress={beat} />
            </>
          )}
        </div>
      </m.div>

      {/* **The answer region holds its box from the first frame.** `opacity` alone moves — never
          `display`, never `height` — so the tumble→land sequence shifts 0.00 px and the answer is
          genuinely not on screen while the dice move. `aria-hidden` while rolling so a screen
          reader is not told the winner before the sighted reader gets it; `inert` would also stop
          the trip control being reachable early. */}
      {/* **D108 — the deciding seat is named from the first frame, before any dice are seen.**
          That ordering is the ruling's own honesty mechanism: five results with one silently
          chosen afterwards is indistinguishable from picking the roll somebody liked. So this
          line sits OUTSIDE `.answer` and is visible during the tumble, deliberately.

          **It is safe there and I checked rather than assumed.** `RV-16` asks that nothing on
          screen distinguishes the WINNER mid-tumble; this names a person, carries no place and no
          number, and is identical whichever place wins. The name comes from `counts` on the seat
          rather than from `deciding_member`, though both are on the wire — one fact, one source,
          so a sentence cannot name somebody a row does not mark.

          **「以 … 的骰子為準」 and never 「… 擲出了」.** The seed was drawn at open and every pair
          derives from it; the tap discloses a number that already existed. Wording that credits
          the tap with producing it is D108's stated prohibition in prose. */}
      {decider && (
        <p className="decider" data-part="deciding">以 {decider} 的骰子為準。</p>
      )}

      <m.div
        className="answer"
        data-part="answer"
        aria-hidden={!answered}
        inert={!answered}
        initial={false}
        animate={{ opacity: answered ? 1 : 0, y: reduce || answered ? 0 : 26 }}
        transition={reduce ? { duration: 0 } : { type: 'spring', stiffness: 300, damping: 24, mass: 1 }}
      >
        {/* **`sum` is in the member payload and is deliberately NOT rendered.** It is an innocent
            number — the two dice added up — but §1's table does not list it in member state, and
            §1a refuses *any bare number the eye can pair with a place*. A digit sitting directly
            above a restaurant's name is that shape exactly, whatever it happens to mean, and
            `RV-2` is written to walk text and attributes looking for precisely it. The dice
            already say what they rolled, in pips, which is the form that cannot be mistaken for a
            share of anything. */}
        <h1 className="winner" data-part="winner">{winner}</h1>

        {/* **The sentence.** Everything the evidence table used to carry now rests on nine
            characters, so they are load-bearing typography and not a caption: `text-lead`, full
            `ink`, the body face's regular weight. It does not animate and it is present from the
            first painted frame of the landed state — a fact that arrives late reads as an apology.

            **It is inert until `[OPEN-1]` is ruled**: plain text, no handler, no link styling, no
            tooltip, no icon. Inert is the reversible option — a door added later changes nothing
            already built, whereas a door removed later leaves a dead region people have learned to
            press. It claims that the allocation happened and that weight drove it. It does not
            claim the reader can check that, and it must not be dressed to imply so. */}
        <p className="sentence" data-part="sentence">三十六格已按權重分配</p>

        {/* **The act, inline and inside `.answer` — owner-ruled 2026-08-20, option 乙.** The pinned
            BAR is retired; the act belongs to the composition it acts on. It sits under the winner
            block and starts at the same left edge as the headline, so the column reads as one
            column rather than a page with a control bolted to its foot.

            **Inside `.answer` on purpose, and that is what "renders only in the staged state"
            buys.** The block already carries `aria-hidden` and `inert` while the dice tumble and
            fades in with the name, so there is no moment where a control invites a press that
            would do nothing — which deletes the disabled state from this screen entirely rather
            than restyling it. `D91`'s zero-shift clause is kept for free: the act arrives with the
            block it lives in, so nothing above it moves.

            **The seal is drawn in `currentColor`, never in hot.** The old bar was hot-on-cobalt and
            that clash is what died with it; `currentColor` means one declaration serves all four
            winning faces and no frame can render ink on ink. */}
        {/* **蓋章 — the reveal's act is a stamp** (evaluator-ruled 2026-08-20 under D101's
            delegation; `sign-act.html` 乙). Not a button that says 我們去了: an empty seal waiting
            for a mark, and the act of pressing it is the act of agreeing. That is §5 質感 rule 1's
            whole argument — the control is drawn as the thing it means from print culture, and a
            seal is what a Taiwanese page uses to mean *settled*.

            **The seal keeps its box across both states**, so the change from asking to signed is a
            cross-fade in a box that never resizes (§5 rule 2) and `RV-17`'s reserve-the-box logic
            applies to the nickname: the name is 900-weight display type and arrives where its
            space already was.

            **The seal is FIRST in both states, and that is what "same position" costs.** Reading
            order would rather the name came before 說這一餐去了 — and it does, because the name is
            *inside* the seal. Putting the question first instead would move the seal 200 px
            sideways the moment someone signed. */}
        <div className="act-row" data-part="act">
          {trip ? (
            /* D106 — the trip is named; the proposal it came from never is. The nickname is the
               one the wire carries, and it is the only member identity this screen keeps. */
            <p className="sealRow" data-part="trip">
              <span className="seal sealSigned">
                {/* **Vertical for a name with CJK in it, horizontal for an all-Latin one**
                    (evaluator-ruled 2026-08-20). `vertical-rl` sets CJK top-to-bottom, which is
                    what a seal does; it rotates Latin 90 degrees, and **a rotated word is not a
                    stamped one** — it reads as a label lying on its side. The fork is on the data
                    rather than on a setting, because the nickname is whatever someone typed.

                    The test is *does it contain CJK*, not *is it all Latin*: a mixed name like
                    `Amy美` is set vertically, which is right — the CJK half is the half the
                    vertical setting exists for. */}
                <span
                  className="sealName"
                  data-set={/[\u3400-\u9FFF\uF900-\uFAFF]/.test(trip.nickname) ? 'vertical' : 'horizontal'}
                >
                  {trip.nickname}
                </span>
              </span>
              <span className="sealSaid">說這一餐去了</span>
            </p>
          ) : (
            <button
              type="button"
              className="sealRow sealBtn"
              data-part="sign"
              onClick={() => void sign()}
              disabled={signing}
            >
              {/* `aria-hidden` on the seal itself: it is the drawing, and the button's accessible
                  name is the question. A screen reader announcing an empty box before the question
                  would be describing the ink rather than the act. */}
              <span className="seal sealEmpty" aria-hidden="true" />
              <span className="sealAsk">這一餐，說定了嗎？</span>
            </button>
          )}
        </div>
      </m.div>

      {/* **§0b, owner-amended: the member sees the LIST, never the numbers.** 「使用者畫面我認為可
          以套用開發者的這頁，只是需要移除36格的畫面，以及權重點數」 — the same panel as the
          operator's, minus the grid and minus the counts. D105 removed the whole thing because
          「麻辣火鍋 0/36」 in a circle of five is one guess; **the guessable object was always the
          number, never the name** — the places were proposed openly by the people in the room.

          One component renders both states, and that is the point rather than a convenience: §0
          says the operator state is the member state *plus* two things, so the two states cannot
          drift into two layouts. `evidence` is null for a member because nothing arrived, and every
          numeric column is gated on it — so a member's screen cannot show a count even if someone
          later adds one to the markup without thinking.

          **No proposer name on any row** (owner-ruled 2026-08-19, separately): the winning place
          would reveal whose pick won, and a repeat winner becomes a pattern about a person. The
          spec's §0b still calls that question open — it was ruled after that line was written. */}
      <div className="right" data-part="right-column">
      {data && (
        <Evidence
          ev={evidence}
          places={data.places}
          winnerId={data.winning_place_id}
          sweep={sweep}
        />
      )}
      </div>

      {/* Owner-ruled 「要」 2026-08-19. **After the dice land**, not before: the pairs are the
          receipt for a result the screen has just shown, and printing them while the dice are still
          in the air would be the answer available in numbers beside an animation withholding it —
          the same argument that keeps the revealed seed until the landing. */}
      <div className="under">
      {answered && data && <Pairs rolls={data.rolls ?? []} />}

      {/* ── D108 · the commitment, and the seed that opens it ──────────────────────────────
          **The hash is shown throughout; the seed only once the dice have landed.** The commitment
          is a hash and discloses nothing, so it is safe during the tumble and belongs there — it is
          the claim that the outcome predates the round. **The seed is the answer in another form**:
          every pair, the decider and the winner recompute from it, so putting it on screen mid-
          tumble would be the whole result sitting beside an animation built to withhold it. Nobody
          is going to compute sha256 by hand in 1.4 seconds, and that is not the standard — `D91`
          says the animation may not assert a fact it lacks, and a screen holding the answer in a
          recoverable form has not withheld it.

          Both are shown in full. A hash exists to be compared with another hash, and half of one
          cannot be. */}
      {data?.seed_commit && (
        <p className="commit" data-part="seed-commit">
          這一輪的結果在開局時就固定了 · {data.seed_commit}
          {answered && data.revealed_seed && (
            <><br />種子 · {data.revealed_seed}</>
          )}
        </p>
      )}
      </div>

      </div>

    </main>
  )
}
