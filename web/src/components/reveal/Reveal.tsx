import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import Board, { drawable } from './Board'
import Cabinet from './Cabinet'
import Cube, { REST } from './Cube'
import Evidence from './Evidence'
import Field from './Field'
import Pairs from './Pairs'
import { TubeArt, TubeRun, TUBE_MS } from './Tube'
import { drawerOf, ganzhi, litCell, rollAnimFor, woodPool, zhNumeral } from '@/lib/board'
import { arrive, useReducedMotion } from '@/lib/motion'
import {
  evidenceIn, faceOf, fetchRaw, RoundStillOpen, signTrip,
  type Evidence as EvidenceData, type MemberReveal, type Trip,
} from '@/lib/reveal'
import { device, noteLastRound, type Device } from '@/lib/device'
import { SeatGone } from '@/lib/http'
/* §3a only. The operator's counts come from the same endpoint the member's 這一餐 used to render
   them from, so there is one definition of each figure and no second arithmetic. */
import { fetchPreferences, type Preferences } from '@/lib/preferences'

/**
 * The reveal — **the 籤詩櫃 rebuild with the cinematic cut C** (`spec-reveal-qiantong-2026-10-09.md`,
 * `spec-reveal-cinematic-2026-10-09.md` «C, as built»; owner 「電影版」 amended 「用C好了」).
 *
 * **The result is the payload's, decided by the committed seed before a frame animates** (D91,
 * D108). Both roll animations — the dice and the 籤筒, one per round, seeded from the round id so
 * every device in the circle plays the same one — read `dice`, `board` and `winning_place_id` and
 * only show them.
 *
 * **One clock, four phases, published on the element for the gates** (`data-stage`):
 *   `rolling`  the dice tumble and fly to their axis places, or the 籤筒 shakes and gives a stick;
 *   `landed`   the dice are at rest on the cabinet (dice run): **a held pause** (cut C, 0.8 s);
 *   `lit`      one frame: the drawn drawer is marked **and** 「第N籤 干支」 is on the slip (gate 5);
 *              **a second held pause** (0.6 s dice, 0.7 s 籤筒);
 *   `answered` the name, the flood, the list's bold row, the ground's poster dice and the act.
 * **Nothing answers early:** no marked drawer, no bold row, no flood and no ground dice before
 * their phase. The list's slot-machine sweep is gone (owner 「A」, 2026-10-10): its light landed on
 * the winner at the dice stop, before the pause.
 *
 * **Reduced motion is the end state from the first frame** (§5 rule 3): `answered`, lit and painted,
 * no camera, no pause, no close-up. Light and grain are not motion, so they stay.
 *
 * **This component cannot render the accounting, and that is structural.** It is typed on
 * `MemberReveal`, whose fields are the API's own whitelist; the operator's table and grid render only
 * when `evidence` arrived (D105), below the answer.
 */

type Phase = 'rolling' | 'landed' | 'lit' | 'answered'

/** The dice run's rhythm, cut C (ms): the tumble and flight, the pause after the dice settle, and
 *  the pause between the drawer and the name. */
const DICE_MS = { tumble: 3400, settle: 420, hold1: 800, hold2: 600 } as const

/** The camera: how far the proof group is pushed in, and how long it eases back at the name. */
const PUSH = 1.06
const PULL_MS = 900

/** **If frames stop, the screen still lands.** A background tab pauses animations; the person must
 *  still get the answer they are holding. Longer than either run, so it never beats a healthy one. */
const FAILSAFE_MS = 16000

/** A name's width in em, for the headline's fit (item 2 §5): a CJK or full-width character is
 *  one em, everything else about 0.6. Never below 1. */
function nameEm(name: string): number {
  let em = 0
  for (const ch of name) em += /[\u2e80-\u9FFF\uF900-\uFAFF\uff00-\uffef]/.test(ch) ? 1 : 0.6
  return Math.max(1, Math.round(em * 10) / 10)
}

export default function Reveal({ roundId }: { roundId: number }) {
  const [dev] = useState<Device | null>(device)
  const [data, setData] = useState<MemberReveal | null>(null)
  const [error, setError] = useState('')
  const [trip, setTrip] = useState<Trip>(null)
  /** `null` for a member because **nothing arrived** — D105's whole point. */
  const [evidence, setEvidence] = useState<EvidenceData | null>(null)
  /** §3a — the operator's own avoided categories, fetched only once `evidence` is non-null (WP-8). */
  const [counts, setCounts] = useState<Preferences | null>(null)
  const [signing, setSigning] = useState(false)
  /** 乙 §3 — whether the seal LANDS: only this device's 201. A 409 re-read is a fact, not an act. */
  const [sealLanded, setSealLanded] = useState(false)
  const reduce = useReducedMotion()
  const [phase, setPhase] = useState<Phase>('rolling')
  /** The phase as of the last render, for callbacks that outlive it (a flight finishing after the
   *  failsafe answered must not send the screen back to `landed`). */
  const phaseRef = useRef<Phase>('rolling')
  phaseRef.current = phase
  const [landedBy, setLandedBy] = useState<'animation' | 'fallback' | 'reduced' | null>(null)
  /** Where each die rests, in the cabinet layer's coordinates, and the die's size — measured from
   *  the drawn cells, so the rest is the row's start and the column's top at every width. */
  const [rest, setRest] = useState<{ size: number; row: [number, number]; col: [number, number]; tube: [number, number, number] } | null>(null)

  const root = useRef<HTMLElement | null>(null)
  const answerBox = useRef<HTMLDivElement | null>(null)
  const slipRef = useRef<HTMLDivElement | null>(null)
  const boardSlot = useRef<HTMLDivElement | null>(null)
  const layer = useRef<HTMLDivElement | null>(null)
  const tubeRest = useRef<HTMLDivElement | null>(null)
  const rowDie = useRef<HTMLDivElement | null>(null)
  const colDie = useRef<HTMLDivElement | null>(null)
  const rowSpin = useRef<HTMLDivElement | null>(null)
  const colSpin = useRef<HTMLDivElement | null>(null)
  const ran = useRef(false)

  const anim = rollAnimFor(roundId)
  const mounted = useRef(true)
  const runTimers = useRef<number[]>([])
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; runTimers.current.forEach((h) => window.clearTimeout(h)) }
  }, [])

  /* **If frames stop, the screen still lands** — one failsafe per reveal, keyed on the payload alone,
     so no re-measure can clear it. Never sooner than either run. */
  useEffect(() => {
    if (!data) return
    const h = window.setTimeout(() => {
      setLandedBy((b) => b ?? 'fallback'); setPhase('answered')
    }, FAILSAFE_MS)
    return () => window.clearTimeout(h)
  }, [data])

  /* §3a's fetch, keyed on `evidence` so a member never makes it. A failure is swallowed: the
     counts are a footnote to the operator's table, and a 500 on the footnote must not cost it. */
  useEffect(() => {
    if (!dev || !evidence) return
    let live = true
    fetchPreferences(dev)
      .then((p) => { if (live) setCounts(p) })
      .catch(() => { if (live) setCounts(null) })
    return () => { live = false }
  }, [dev, evidence])

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
        // The bar's 上一餐結果 — forward only (`noteLastRound`).
        noteLastRound(roundId)
        if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
          setLandedBy('reduced'); setPhase('answered')
        } else if (!drawable(d.board) || !litCell(d.dice)) {
          // Nothing to play the roll on (a swept pool draws no board): land at once rather than
          // waiting out the failsafe.
          setLandedBy('animation'); setPhase('answered')
        } else if (evidenceIn(raw)) {
          // The operator's screen is an instrument: no cabinet to play the roll on, so it lands.
          setLandedBy('animation'); setPhase('answered')
        }
      })
      .catch((e: Error) => {
        if (!live) return
        // Nothing to reveal yet: the round is still open, so the person belongs on 這一餐.
        if (e instanceof RoundStillOpen) { window.location.replace('/round'); return }
        // The key holds no seat here: lib/http has already dropped it; the message is the shared line.
        if (e instanceof SeatGone) {
          setError(e.message)
          window.setTimeout(() => { window.location.href = '/' }, 2500)
          return
        }
        // A void round's sentence is the API's own (RoundVoid), shown as it is.
        setError(e.message || '讀取失敗')
      })
    return () => { live = false }
  }, [dev, roundId])

  /**
   * **The composition's measured numbers**, read from the real boxes: where each die rests (the
   * drawn row's first drawer and the drawn column's top drawer), the 籤筒's resting place on the
   * cabinet's top edge, and the cabinet's centre for the painted light. A `ResizeObserver`, because
   * the list and the name arrive with the payload and the cabinet scales with the stage.
   */
  useLayoutEffect(() => {
    const measure = () => {
      const r = root.current, l = layer.current
      if (!r || !l || !data) return
      const grid = l.parentElement?.querySelector<HTMLElement>('.cabGrid')
      const cell = litCell(data.dice)
      if (!grid || !cell) return
      const lb = l.getBoundingClientRect(), gb = grid.getBoundingClientRect()
      const first = grid.querySelector<HTMLElement>(`[data-row="${cell[0] + 1}"][data-col="1"]`)
      const top = grid.querySelector<HTMLElement>(`[data-row="1"][data-col="${cell[1] + 1}"]`)
      if (!first || !top) return
      const fb = first.getBoundingClientRect(), tb = top.getBoundingClientRect()
      const size = Math.round(fb.width * 0.86)
      // The 3/4 view draws the cube about 1.25 × its box, so the gaps clear the cabinet's frame.
      // …and never off the left edge of the screen (the narrow column has little room beside the grid).
      const row: [number, number] = [Math.max(size * 0.72 - lb.left, gb.left - lb.left - size * 0.95), fb.top + fb.height / 2 - lb.top]
      const col: [number, number] = [tb.left + tb.width / 2 - lb.left, gb.top - lb.top - size * 0.95]
      const tubeW = Math.round(fb.width * 0.95)
      const tube: [number, number, number] = [gb.left - lb.left + 4, gb.top - lb.top - tubeW * 2 + 6, tubeW]
      setRest((was) => (was && was.size === size && was.row[0] === row[0] && was.row[1] === row[1]
        && was.col[0] === col[0] && was.col[1] === col[1] && was.tube[1] === tube[1] ? was : { size, row, col, tube }))
      // The key light is centred on the cabinet, in the page's coordinates: the painting is laid from
      // the page's top-left and onto each cover panel at its offset (cut C: no full-screen overlay).
      const pb = r.getBoundingClientRect()
      r.style.setProperty('--cx', `${Math.round(gb.left + gb.width / 2 - pb.left)}px`)
      r.style.setProperty('--cy', `${Math.round(gb.top + gb.height / 2 - 20 - pb.top)}px`)
      if (boardSlot.current) r.style.setProperty('--board-h', `${Math.round(boardSlot.current.offsetHeight)}px`)
      // The list column is absolute and adds nothing to the stage's height, so the stage is held open
      // to its measured end — or the last rows of a ten-place list sit past a page that cannot scroll.
      const list = r.querySelector<HTMLElement>('.right')
      if (list) r.style.setProperty('--right-end', `${Math.round(list.offsetTop + list.offsetHeight)}px`)
      // Each cover panel's offset from the page's top-left, so the one painting lines up across them.
      const rb = r.getBoundingClientRect()
      for (const el of [boardSlot.current, r.querySelector<HTMLElement>('.right')]) {
        if (!el) continue
        el.style.setProperty('--ox', `${Math.round(el.offsetLeft + (el.offsetParent as HTMLElement | null ?? r).getBoundingClientRect().left - rb.left)}px`)
        el.style.setProperty('--oy', `${Math.round(el.offsetTop + (el.offsetParent as HTMLElement | null ?? r).getBoundingClientRect().top - rb.top)}px`)
      }
    }
    measure()
    window.addEventListener('resize', measure)
    const ro = new ResizeObserver(measure)
    if (layer.current) ro.observe(layer.current)
    if (answerBox.current) ro.observe(answerBox.current)
    const rl = root.current?.querySelector<HTMLElement>('.right')
    if (rl) ro.observe(rl)
    return () => { window.removeEventListener('resize', measure); ro.disconnect() }
  }, [data])

  /** The camera, cut C: it scales the proof group (the cabinet and the dice resting in it), never
   *  the whole page — scaling the page halved the frame rate in the preview's A/B. */
  const camera = useCallback((frames: Keyframe[], duration: number, easing = 'cubic-bezier(.4,0,.2,1)') => {
    const el = boardSlot.current
    if (!el || reduce) return null
    return el.animate(frames, { duration, easing, fill: 'forwards' })
  }, [reduce])

  const toLit = useCallback(() => setPhase((p) => (p === 'answered' ? p : 'lit')), [])
  const toAnswered = useCallback(() => {
    if (phaseRef.current === 'answered') return
    setPhase('answered')
    // Back to the ruled framing, then no transform at all: a held `scale(1)` would still make the
    // group a transformed box, and its viewport-pinned light would stop lining up with the page's.
    const pull = camera([{ transform: `scale(${PUSH})` }, { transform: 'scale(1)' }], PULL_MS)
    void pull?.finished.then(() => boardSlot.current?.getAnimations().forEach((a) => a.cancel())).catch(() => {})
  }, [camera])

  /**
   * **The dice run.** The two cubes are rendered at their resting places in the cabinet layer; the
   * flight is a transform from the left column back to that place (FLIP), so the resting
   * composition is what the stylesheet and the measurement say, and the animation is the only thing
   * that has to be undone. Each die is thrown from its own point and spins its own way: two cubes
   * given one motion read as one object cut in half.
   */
  useEffect(() => {
    if (!data || !rest || reduce || anim !== 'dice' || ran.current) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const a = answerBox.current, l = layer.current
    const dice = [rowDie.current, colDie.current], spins = [rowSpin.current, colSpin.current]
    if (!a || !l || dice.some((d) => !d) || spins.some((s) => !s)) return
    ran.current = true
    const lb = l.getBoundingClientRect(), ab = a.getBoundingClientRect()
    const T = DICE_MS.tumble
    const starts: [number, number][] = [
      [ab.left + ab.width * 0.3, innerHeight * 0.47],
      [ab.left + ab.width * 0.62, innerHeight * 0.52],
    ]
    camera([{ transform: 'scale(1)' }, { transform: `scale(${PUSH})` }], T)
    const targets = [rest.row, rest.col]
    const flights = dice.map((d, i) => {
      const [sx, sy] = starts[i]
      const dx = sx - (lb.left + targets[i][0]), dy = sy - (lb.top + targets[i][1])
      d!.animate([
        { transform: `translate(${dx}px, ${dy - 180}px) scale(2.3)` },
        { transform: `translate(${dx}px, ${dy}px) scale(2.3)`, offset: 0.2 },
        { transform: `translate(${dx}px, ${dy}px) scale(2.3)`, offset: 0.74 },
        { transform: 'none' },
      ], { duration: T, easing: 'cubic-bezier(.35,.7,.3,1)', fill: 'both' })
      const w = i ? [1, -1] : [-1, 1]
      return spins[i]!.animate([
        { transform: `rotateX(${w[0] * 1080}deg) rotateY(${w[1] * 900}deg) rotateZ(${w[0] * 180}deg)` },
        { transform: REST, offset: 0.74 },
        { transform: REST },
      ], { duration: T, easing: 'cubic-bezier(.2,.7,.25,1)', fill: 'both' })
    })
    // **The run's timers outlive this effect's re-runs.** The slip arriving at `lit` changes the
    // column's height, which re-measures `rest` and re-runs this effect; clearing the timers then
    // left a narrow screen stuck at `lit` (found by g_multi_device at 430). They are cleared on
    // unmount only (`runTimers`).
    void Promise.all(flights.map((f) => f.finished)).then(() => {
      if (!mounted.current || phaseRef.current !== 'rolling') return   // the failsafe already answered
      setLandedBy((b) => b ?? 'animation'); setPhase((p) => (p === 'rolling' ? 'landed' : p))
      camera([{ transform: `scale(${PUSH})` }, { transform: `scale(${PUSH - 0.015})` }, { transform: `scale(${PUSH - 0.008})` }], DICE_MS.settle, 'ease-out')
      runTimers.current.push(window.setTimeout(toLit, DICE_MS.hold1))
      runTimers.current.push(window.setTimeout(toAnswered, DICE_MS.hold1 + DICE_MS.hold2))
    }).catch(() => { /* cancelled on unmount */ })
  }, [data, rest, reduce, anim, camera, toLit, toAnswered])

  /** The 籤筒 run's camera: in during the shake, back out as the stick leaves the tube. Its own
   *  phases come from `TubeRun`. */
  const tubeMounted = useRef(false)
  useEffect(() => {
    if (!data || reduce || anim !== 'tube' || tubeMounted.current) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return
    tubeMounted.current = true
    camera([{ transform: 'scale(1)' }, { transform: `scale(${PUSH})` }], TUBE_MS.shake * TUBE_MS.shakes)
  }, [data, reduce, anim, camera])
  const tubeStick = useCallback(() => camera([{ transform: `scale(${PUSH})` }, { transform: 'scale(1)' }], 600), [camera])
  const tubeLit = useCallback(() => { setLandedBy((b) => b ?? 'animation'); toLit() }, [toLit])
  const tubeNamed = useCallback(() => {
    setPhase('answered')
    boardSlot.current?.getAnimations().forEach((a) => a.cancel())
  }, [])

  const sign = useCallback(async () => {
    if (!dev || signing) return
    setSigning(true)
    try {
      const { trip: signed, created } = await signTrip(dev, roundId)
      setTrip(signed)
      if (created) setSealLanded(true)
    } catch (e) {
      // SeatGone and RoundVoid carry their own sentences.
      setError((e as Error).message || '簽不上')
      if (e instanceof SeatGone) window.setTimeout(() => { window.location.href = '/' }, 2500)
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
        <p className="revealErr" data-part="reveal-error" role="alert">{error}</p>
      </main>
    )
  }

  const answered = phase === 'answered'
  const lit = phase === 'lit' || answered
  const face = data ? faceOf(data.places, data.winning_place_id) : null
  const winner = data && data.winning_place_id !== null
    ? (data.winner_headline ?? data.places[String(data.winning_place_id)])
    : ''
  /** `design.md` §4b: no fallback — a missing qualifier renders no element. */
  const qualifier = data?.winner_qualifier ?? null
  const n = drawerOf(data?.dice)
  const qian = n ? `第${zhNumeral(n)}籤 ${ganzhi(n)}` : ''
  const wood = woodPool(data?.places)
  const member = !!data && !evidence
  const running = !reduce && landedBy !== 'reduced'

  return (
    <main
      ref={root}
      className="reveal"
      data-screen="reveal"
      data-roll-anim={anim}
      data-state={phase === 'rolling' ? 'rolling' : 'landed'}
      data-stage={phase}
      data-landed-by={landedBy ?? undefined}
      /* The slip is dimmed while the cabinet holds the eye and comes forward with the name (cut C:
         focus by dimming, never blur). */
      data-focus={answered ? 'slip' : 'cabinet'}
      /* The flood moves with the name, never with the stop. */
      data-face={answered && face ? face : undefined}
    >
      {/* The ground's printed pair names the drawer with the board beside it, so it arrives with
          the name and not before (gate 4). */}
      <Field dice={data?.dice} staged={answered} />

      <div className="stage">

      {/* The answer region holds its box from the first frame and only its opacity moves. From `lit`
          the slip shows and 「第N籤 干支」 is added inside it (the one insertion: at ≥ 1100 it sits in the slip's
          fixed height, so nothing outside the slip moves); the name and the act wait for
          `answered`. */}
      <p className="sr-only" aria-live="polite">{answered && winner ? winner : ''}</p>
      <div
        ref={answerBox}
        className="answer"
        data-part="answer"
        data-shown={lit ? (answered ? 'all' : 'slip') : undefined}
        aria-hidden={!answered}
        inert={!answered}
      >
        {/* Look D: the winner is a joss-paper slip. The red head band is drawn for the eye only. */}
        <div className="slip" data-part="slip" ref={slipRef}>
          <div className="slipHead" aria-hidden="true" />
          {/* **「第N籤 干支」 ties the answer to drawer N** — the drawer's numeral and its own name,
              never a shop's. It replaces the numbered swatch. */}
          {lit && n && <p className="qianNo dSerif" data-part="qian-no">{qian}</p>}
          <div className="winnerLine">
            <h1 className="winner" data-part="winner" data-user-content style={{ '--len': nameEm(winner ?? '') } as CSSProperties}>{winner}</h1>
          </div>
        </div>

        {/* Beside the slip at ≥ 1100, centred on its middle; under it below. */}
        <div className="answerSide">
          {/* **The qualifier — which branch** (`design.md` §4b): rendered only when non-null, no
              punctuation added back. */}
          {qualifier !== null && (
            <p className="qualifier" data-part="qualifier">{qualifier}</p>
          )}

          {/* **蓋章 — the reveal's act is a stamp** (evaluator-ruled 2026-08-20, `sign-act.html` 乙).
              The seal keeps its box in both states, so asking → signed is a cross-fade. */}
          <div className="act-row" data-part="act">
            {trip ? (
              /* D106 — the trip is named; the proposal it came from never is. */
              <p className="sealRow" data-part="trip" data-landed={sealLanded ? 'yes' : undefined}>
                <span className={sealLanded ? 'seal sealSigned sealLand' : 'seal sealSigned'}>
                  {/* Vertical for a name with CJK in it, horizontal for an all-Latin one: a rotated
                      word is not a stamped one. */}
                  <span
                    className="sealName"
                    data-user-content
                    data-set={/[\u3400-\u9FFF\uF900-\uFAFF]/.test(trip.nickname) ? 'vertical' : 'horizontal'}
                  >
                    {trip.nickname}
                  </span>
                </span>
                <span
                  className={sealLanded ? 'sealSaid arrive' : 'sealSaid'}
                  style={sealLanded ? arrive(1) : undefined}
                >說這一餐去了</span>
              </p>
            ) : (
              <button
                type="button"
                className="sealRow sealBtn"
                data-part="sign"
                data-primary
                onClick={() => void sign()}
                disabled={signing}
              >
                <span className="seal sealEmpty" aria-hidden="true"><span className="sealAsk sealGlyph">定</span></span>
                <span className="sealText">
                  <span className="sealAsk">這一餐，說定了嗎？</span>
                  <span className="sealHow" data-part="sign-explain">按下去會記下：是你說這一餐去了這家。</span>
                </span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* **The proof: the 籤詩櫃, with the dice (or the 籤筒) resting on it** — in the first screen
          from the first frame, unmarked until `lit` (D91). The camera pushes in on this group. */}
      <div className="boardSlot" ref={boardSlot} data-cine-cam="">
        {member && (
          <Cabinet board={data.board} places={data.places} dice={data.dice} lit={lit}
            mark={anim === 'dice' ? 'lines' : 'frame'}>
            <div className="cabLayer" ref={layer}>
              {anim === 'dice' && rest && data.dice && (
                <>
                  <Cube ref={rowDie} spinRef={rowSpin} value={data.dice[0]} axis="row"
                    style={{ left: rest.row[0], top: rest.row[1], '--cube': `${rest.size}px` } as CSSProperties} />
                  <Cube ref={colDie} spinRef={colSpin} value={data.dice[1]} axis="col"
                    style={{ left: rest.col[0], top: rest.col[1], '--cube': `${rest.size}px` } as CSSProperties} />
                </>
              )}
              {anim === 'tube' && rest && (
                <div ref={tubeRest} className="cabTube" data-part="tube-rest" aria-hidden="true"
                  data-hidden={running && !lit ? 'yes' : undefined}
                  style={{ left: rest.tube[0], top: rest.tube[1] }}>
                  <TubeArt width={rest.tube[2]} />
                </div>
              )}
            </div>
          </Cabinet>
        )}
      </div>

      {/* The places list: the names in play, never a number (§0b). No proposer on any row. The
          winning row's weight arrives with the name. */}
      <div className="right" data-part="right-column">
        {data && (
          <Evidence
            ev={evidence}
            places={data.places}
            winnerId={answered ? data.winning_place_id : null}
            wood={wood}
            counts={counts}
          />
        )}
      </div>

      {/* The receipt, after the answer: the pairs, and the operator's board. */}
      <div className="under">
        {answered && data && <Pairs rolls={data.rolls ?? []} />}
        {answered && data && evidence && (
          <Board board={data.board} places={data.places} dice={data.dice} lit={lit} />
        )}
      </div>

      </div>

      {/* The 籤筒's flight layer: fixed, outside the camera, played once on a reveal with motion. */}
      {member && anim === 'tube' && running && rest && n && (
        <TubeRun numeral={zhNumeral(n)} restRef={tubeRest} slipRef={slipRef}
          onStick={tubeStick} onLit={tubeLit} onNamed={tubeNamed} />
      )}
    </main>
  )
}
