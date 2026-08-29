import { useCallback, useEffect, useRef, useState } from 'react'
import Die, { SEQUENCE_MS } from './Die'
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
 * `STAGED` is the identity — the read position, the left column at `--stage-pad`, which is what
 * the stylesheet says and what the final frame must not depend on an animation for.
 *
 * **`ROLLING`'s x is MEASURED, not typed** (甲改, evaluator 2026-08-26: the tumbling group sits on
 * the viewport's true centre). It used to be the constant 288, which is right only because
 * 104 + 288 = 392 = (1440 − 656) / 2 — three numbers from three places agreeing at one width and
 * nowhere else. Now it is computed from the group's own `offsetWidth` (a transform does not change
 * it) and the viewport, so the tumble is centred at every width and a change to `--die` or the
 * dice gap cannot silently un-centre it. `RV-23` measures exactly that, ±2 px.
 *
 * y is 0: the group tumbles at the CSS `top` the composition gives it, no longer 114 px below it.
 */
const ROLLING_FALLBACK_X = 288

/** The gutter between the answer block and the places list in the staged column, **in stage units,
 *  not pixels** (§0c amendment E). One number, used by the measurement below and by `.under`'s
 *  reservation in CSS, so the two cannot disagree; multiplied by `--k` at the point of use, so it
 *  is 72 px at 1440 and grows with everything else. */
const LIST_GUTTER = 72
const STAGED = { x: 0, y: 0, scale: 0.42 }

/**
 * **The slot machine — §0c amendment B, the owner reversing his own 08-19 rule** (「選取條可以減速
 * 停在贏家上，並且一開始就從最上面的店家開始往下滾動，像拉霸機一樣」).
 *
 * The light starts on the FIRST row and runs downward, cyclic, on the dice's own ease-out — fast,
 * then slowing — and its last and longest step lands on the stored winner and stays there.
 *
 * **Why this is not `D91`'s forbidden case.** The outcome is committed at open (`D108`) and stored
 * before a frame animates, so a light decelerating onto the winner *displays a decided result*.
 * §0c's old rule was written against a screen where the animation looked like the mechanism; since
 * the seed commit it visibly is not. The argument is in the spec and was adopted there — it is not
 * a licence taken here.
 *
 * **What still binds, and all three are built rather than hoped for:**
 *
 * 1. *The end is the stored result.* The last index is chosen so `steps − 1 ≡ winner (mod n)`. The
 *    schedule cannot end anywhere else, on any roll.
 * 2. *The timing may not leak the answer.* `total` is a constant and the curve is normalised over
 *    the step count, so a winner on row 0 and a winner on row 4 take **exactly the same time**. A
 *    sweep that stopped sooner for an early row would announce the answer before the light did,
 *    which is the D91 violation this rule is actually about. The step *count* does differ with the
 *    winner's row — and that is not a second channel: it is the position of the light itself, which
 *    a person can already see. What must not differ is the duration, and it does not.
 * 3. *One clock.* `total` is `SEQUENCE_MS`, the longer of the two throws, imported from `Die` —
 *    the same number the dice are animated on. Deriving it from `--tumble` (a CSS duration nothing
 *    animates on any more) or from a typed constant is how the light and the dice drift apart, and
 *    the gate allows 120 ms between them.
 *
 * **The cost, which the owner heard and reaffirmed:** the light now reads as choosing. The seed,
 * the commitment and the dice remain the truth, and the reveal prints all three.
 */
const SWEEP_CYCLES = 3

/** How much longer the last step is than the first. **8, and it is the deceleration a person
 *  actually sees**: at five places that is a light stepping every ~50 ms at the throw and every
 *  ~390 ms as it settles. The gate asks for the last ≥ 2× the first; this is well past it, because
 *  2× is the floor for *measuring* deceleration and not the point at which it reads as one. */
const SWEEP_RAMP = 8

/**
 * The whole schedule, as the start time of each step. **Pure and total** — no clock, no DOM, no
 * randomness — so the gate's questions about it can be answered by reading it rather than by
 * filming it. Step `i` lights row `i mod n`; the array's length is what makes the last one the
 * winner.
 *
 * **The intervals ramp linearly from `d0` to `8 × d0`, and the ramp is what makes the two hard
 * properties true by construction rather than by tuning:**
 *
 * - *Monotonic, always.* `d(k) = d0 + k × step` with a positive step is non-decreasing for every
 *   pool size and every winner. A curve evaluated at `i / steps` is not: it has to be checked.
 * - *The winner lights at `total`, whatever row it is.* The intervals are made to SUM to `total`,
 *   so the last step starts exactly when the dice stop — the same instant on every roll. This is
 *   the leak check, and it is the one thing here that has to be exact: a schedule whose last step
 *   lands at `ease((steps−1)/steps) × total` finishes sooner when the winner sits high in the list,
 *   which announces the answer in the timing before the light gets there. **Measured on the first
 *   build of this, which did exactly that: 3137–3224 ms across six rolls, and the spread tracked
 *   the winner's row.**
 *
 * **A note for whoever compares this to `reveal-o-a2.html`.** The mock's schedule is
 * `ease(i/steps) × total` with `ease = 1 − (1 − x)^2.6`, and its comment says 「early steps ~90 ms,
 * last ones ~500 ms」. That function's derivative is *largest at zero*, so it does the opposite: the
 * mock's light starts slow and ends fast. This build follows the ruling's words — 減速 — and not
 * the mock's arithmetic. Flagged to the evaluator rather than silently matched.
 */
function slotSchedule(n: number, winnerIndex: number, total: number): number[] | null {
  if (n < 2 || winnerIndex < 0 || winnerIndex >= n) return null
  const steps = SWEEP_CYCLES * n + winnerIndex + 1
  const gaps = steps - 1
  // sum of a linear ramp d0 … R·d0 over `gaps` terms = gaps × d0 × (1 + R) / 2
  const d0 = (2 * total) / (gaps * (1 + SWEEP_RAMP))
  const grow = gaps > 1 ? (SWEEP_RAMP - 1) * d0 / (gaps - 1) : 0
  const times = [0]
  for (let k = 0; k < gaps; k++) times.push(times[k] + d0 + k * grow)
  return times
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
  /** **`too-many-rows` is gone with the equal-dwell rule it belonged to.** The slot machine's
   *  schedule is normalised over its own step count, so a large pool makes the steps shorter
   *  rather than making the schedule impossible; there is no cap left to hit. `no-winner` replaces
   *  it: a payload whose winner is not in its own places list is a broken payload, and a sweep that
   *  quietly ran anyway would end on a row chosen by an accident. */
  const [skipped, setSkipped] = useState<'one-row' | 'no-winner' | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const root = useRef<HTMLElement | null>(null)
  const group = useRef<HTMLDivElement | null>(null)
  const list = useRef<HTMLDivElement | null>(null)
  const answerBox = useRef<HTMLDivElement | null>(null)
  /** Where the tumbling group has to be so it is centred on the viewport — see `STAGED` above. */
  const [rollX, setRollX] = useState(ROLLING_FALLBACK_X)

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
   * The sweep — the slot machine. See `slotSchedule` above for the rule and for why it is allowed
   * to stop on the answer.
   *
   * **`rAF`, not `setInterval`.** The steps are 60 ms apart at the start and ~500 ms at the end, so
   * a fixed interval cannot express them; and the gate measures the last step against the dice's
   * stillness to 120 ms, which a timer chain's accumulated drift would spend on its own.
   *
   * **It does not stop at `landed`, and that is amendment C.** The winner's light is held through
   * the stop, through the 1000 ms hold and through the entrance, and hands over to the row's bold
   * weight at ③ — cleared by the effect below, not by this one. `landed` is no longer in this
   * effect's dependencies at all: re-running it on the landing is what used to blank the row.
   */
  useEffect(() => {
    if (!data) { setSweep(null); return }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const ids = Object.keys(data.places)
    const winnerIndex = ids.indexOf(String(data.winning_place_id))
    const times = slotSchedule(ids.length, winnerIndex, SEQUENCE_MS)
    // **Never a silent cap.** A recording with no sweep in it should say which of the two it is —
    // an effect that was skipped by rule, or an effect that was built and does not work.
    if (!times) { setSkipped(ids.length < 2 ? 'one-row' : 'no-winner'); return }
    setSkipped(null)
    let t0: number | null = null
    let i = 0
    let raf = 0
    const tick = (now: number) => {
      // **`t0` is the first animation frame, not the moment the effect ran.** The effect runs
      // inside the render that the round's close triggered, and the first frame after it can be
      // 100 ms later — a schedule started from `performance.now()` is already four steps behind
      // when it gets its first frame.
      if (t0 === null) t0 = now
      const t = now - t0
      // **One step per frame, and never a catch-up loop.** The loop this replaces advanced `i`
      // while it was behind, so a late first frame made the light jump straight to row 3 — rows
      // 0,1,2 were set in the same React batch and only the last of them ever rendered. Measured:
      // 3–4 of the opening steps never appeared, on every roll. §0c's binding is that the light
      // starts on the first row and visits them **in order**; a dropped row breaks the visible
      // rule, where a stalled frame merely delays the light — so if the machine is too busy to
      // keep up, the sweep runs late rather than incomplete, and the gate's 120 ms to the dice
      // will say so honestly.
      if (i < times.length && t >= times[i]) {
        setSweep(ids[i % ids.length])
        i += 1
      }
      // The loop ends with the last row lit. Nothing clears it here.
      if (i < times.length) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [data])

  /**
   * **C · the light hands over to the weight.** The winner's row stays lit from the stop until the
   * answer arrives, then fades as the bold does — the same moment, so the row is never unmarked
   * for a frame and never doubly marked for long. Cleared at `ANSWER_AFTER_STAGED_MS`; the 600 ms
   * fade is the stylesheet's, on the row's own background.
   *
   * Owner's words: 「選取條可以在結果揭示時顯示久一點」 — about 2.4 s lit after the dice stop.
   */
  useEffect(() => {
    if (!staged) return
    const h = window.setTimeout(() => setSweep(null), ANSWER_AFTER_STAGED_MS)
    return () => window.clearTimeout(h)
  }, [staged])

  /**
   * **The two measured numbers of the composition** (甲改), both read from the real boxes rather
   * than typed: where the tumbling group must sit to be centred, and how tall the places list is.
   *
   * The list's height becomes `--list-h` on the root, and the staged column reserves its hole with
   * it. **The mock reserved that hole with a fixed 440 px margin, and a fixed margin is wrong here
   * for a reason a static page cannot show:** the list is as long as the round's pool, which runs
   * from two places to D110's ten, so the number that looks right in a mock puts the seal on top of
   * the list in one round and a hand's width below it in another.
   *
   * A `ResizeObserver` rather than a one-shot read, because the list arrives with the payload and
   * grows again when the sweep's rows render.
   */
  useEffect(() => {
    const measure = () => {
      const r = root.current
      if (!r) return
      if (group.current) {
        // **The pad is read off the element, not out of the custom property.** `--stage-pad` is a
        // `calc()` on `--k` and computes to its token stream unless it is declared; the group's own
        // used `left` is the same number and cannot be anything else.
        const pad = parseFloat(getComputedStyle(group.current).left) || 0
        // `offsetWidth` is the untransformed box, which is what centring is about — reading the
        // rect would fold in whatever the retreat spring is doing at that instant.
        const w = group.current.offsetWidth
        if (w > 0) setRollX(Math.round((window.innerWidth - w) / 2 - pad))
      }
      if (list.current) {
        r.style.setProperty('--list-h', `${Math.round(list.current.offsetHeight)}px`)
      }
      // **Where the list may sit once the answer is on screen: under it, never through it.**
      // The mock puts the staged list at a flat 380 px, which is 「140 px up from 520」 and is
      // right for the name it happened to draw. Measured with a real one — STARBUCKS COFFEE
      // （北投湖山路） wraps to three lines of the 104 px headline — the answer block runs to 667
      // and the flat number puts the list straight through the middle of it. So the column's
      // order is kept by DERIVING the position: the list starts a gutter below whatever the
      // headline actually needed. A long name pushes it down the page rather than into the text.
      // `--k` is one stage unit as a length — see `reveal.css`'s E block. Everything measured here
      // is already in real pixels; only the numbers this file *types* have to be multiplied.
      const k = parseFloat(getComputedStyle(r).getPropertyValue('--k')) || 1
      if (answerBox.current) {
        // **`offsetTop`/`offsetHeight`, never the rect.** The answer sits 26 px low under its own
        // entrance transform until ③, and a rect folds that in — the list would be placed against
        // a box that is about to move, and land 26 px out of true (measured: 765 where 739 was
        // right). The offset pair is the untransformed box, measured against `.stage`, which is
        // this element's offset parent.
        const top = Math.round(
          answerBox.current.offsetTop + answerBox.current.offsetHeight + LIST_GUTTER * k,
        )
        r.style.setProperty('--list-top', `${top}px`)
      }
    }
    measure()
    window.addEventListener('resize', measure)
    const ro = new ResizeObserver(measure)
    if (group.current) ro.observe(group.current)
    if (list.current) ro.observe(list.current)
    if (answerBox.current) ro.observe(answerBox.current)
    return () => { window.removeEventListener('resize', measure); ro.disconnect() }
  }, [data])

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
  /** A16: the headline takes the API's shortened form, and falls back to the composed name when
   *  the payload carries none. Nothing is computed here — see `winner_headline` in `lib/reveal`. */
  const winner = data && data.winning_place_id !== null
    ? (data.winner_headline ?? data.places[String(data.winning_place_id)])
    : ''
  /** `design.md` §4b. **No fallback, and that asymmetry is the ruling.** A missing headline still
   *  has to say something, so it falls back to the composed name; a missing qualifier has nothing
   *  to say and renders no element at all. Deriving one here from the composed name would be the
   *  browser computing a name, which is the one thing A16 exists to stop. */
  const qualifier = data?.winner_qualifier ?? null

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
        ref={group}
        className="group"
        data-part="dice-group"
        animate={reduce ? { x: 0, y: 0, scale: 1 } : staged ? STAGED : { x: rollX, y: 0, scale: 1 }}
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
        ref={answerBox}
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

        {/* **The qualifier — which branch** (owner-ruled 2026-08-28, `design.md` §4b). The bracket
            D92 composes onto a name that needs one, set as its own line under the headline instead
            of inside it: the headline reads 一階堂拉麵, this reads 大安和平東路, and the 提名 row below
            still reads 一階堂拉麵餐飲有限公司（大安和平東路）, which is how the two are matched by eye.

            **Rendered only when non-null — no empty element and no reserved box.** A single-site
            winner has nothing to say here and the sentence moves up by exactly the line it did not
            need. That is the opposite of `.winner`'s reserved second line above, deliberately: the
            headline's height is a property of the screen (`R-D9`'s floor), and this line's is a
            property of the name.

            **No parentheses, no dash, no icon.** The API sends the bracket's content without its
            punctuation and the browser adds none back — a parenthesis appearing here is a defect.

            It is inside `.answer`, so it rides the block's `aria-hidden` / `inert` and its fade
            and `D91`'s zero-shift clause is kept for free — the same argument the act below it
            already runs on. */}
        {qualifier !== null && (
          <p className="qualifier" data-part="qualifier">{qualifier}</p>
        )}

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
      <div className="right" data-part="right-column" ref={list}>
      {data && (
        <Evidence
          ev={evidence}
          places={data.places}
          winnerId={data.winning_place_id}
          ingredientData={data.ingredient_data}
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
