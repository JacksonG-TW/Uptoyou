import { useEffect, useRef } from 'react'

/**
 * **The 籤筒 — the reveal's second roll animation** (owner, decision-log 6c743a5: one of two,
 * picked per round; `spec-reveal-qiantong-2026-10-09.md` «The 籤筒 sequence»; the cinematic cut C,
 * `spec-reveal-cinematic-2026-10-09.md`).
 *
 * Decoration only: `aria-hidden`, no text a screen reader needs, no control. The result is the
 * payload's, decided before anything moves; the tube shows it, it does not draw it (D91, D108).
 */

/** The tube, drawn once, 150 × 300 at full size: seven sticks, red tops, a lacquer body with a gold
 *  band and panel. */
export function TubeArt({ width = 150 }: { width?: number }) {
  const sticks = [18, 34, 50, 66, 82, 98, 114]
  return (
    <svg viewBox="0 0 150 300" width={width} height={width * 2} aria-hidden="true" focusable="false">
      {sticks.map((x, i) => (
        <g key={x}>
          <rect x={x + 8} y={10 + (i % 3) * 9} width="9" height="120" rx="2" fill="#e6c57a" stroke="#2B1713" strokeWidth="1.5" />
          <rect x={x + 8} y={10 + (i % 3) * 9} width="9" height="12" fill="#b3261e" />
        </g>
      ))}
      <path d="M14 88 h122 v190 a12 12 0 0 1 -12 12 h-98 a12 12 0 0 1 -12 -12z" fill="#8f1d14" stroke="#2B1713" strokeWidth="3" />
      <rect x="14" y="88" width="122" height="14" fill="#D9A93A" stroke="#2B1713" strokeWidth="2" />
      <rect x="14" y="250" width="122" height="10" fill="#D9A93A" />
      <rect x="34" y="128" width="82" height="100" fill="none" stroke="#D9A93A" strokeWidth="2" />
      <path d="M40 140 h70 M40 160 h70 M40 180 h70 M40 200 h70 M40 216 h70" stroke="#D9A93A" strokeWidth="1.2" opacity=".55" />
    </svg>
  )
}

/** The cut-C rhythm, in ms. One table, so the hold the owner watched is a number in one place. */
export const TUBE_MS = {
  shake: 1400,
  shakes: 2,
  rise: 600,
  forward: 520,
  closeup: 1000,
  fade: 200,
  open: 600,
  hold1: 800,
  hold2: 700,
} as const

const wait = (ms: number) => new Promise<void>((r) => window.setTimeout(r, ms))

/**
 * **The run, played once on a reveal with motion.** It flies its own tube and stick in a fixed
 * layer, then hands over: `onLit` is the frame that shows 「第N籤」 on the slip and frames drawer N
 * (gate 5: the same frame), `onNamed` brings the name. The resting tube and the slip are the
 * reveal's own elements; this only animates towards their boxes.
 *
 * **The close-up enlarges the drawer number alone, centred on the stick** (owner 「籤筒的籤繁體字
 * 至中」): the stick comes forward, large, carrying only 「二十七」 — the numeral, never 第 or 籤,
 * never the shop — then it fades and the stick opens into the slip.
 */
export function TubeRun({
  numeral,
  restRef,
  slipRef,
  onStick,
  onLit,
  onNamed,
}: {
  numeral: string
  restRef: React.RefObject<HTMLElement | null>
  slipRef: React.RefObject<HTMLElement | null>
  onStick?: () => void
  onLit: () => void
  onNamed: () => void
}) {
  const tube = useRef<HTMLDivElement | null>(null)
  const stick = useRef<HTMLDivElement | null>(null)
  const label = useRef<HTMLSpanElement | null>(null)
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true
    const t = tube.current, st = stick.current, nm = label.current
    const slip = slipRef.current, rest = restRef.current
    if (!t || !st || !nm || !slip || !rest) { onLit(); onNamed(); return }
    let cancelled = false
    const run = async () => {
      const s = slip.getBoundingClientRect()
      const board = rest.getBoundingClientRect()
      // The tube starts on the left column, between the slip and the cabinet, like the dice did.
      const cx = Math.max(160, (s.right + board.left) / 2 - 75), cy = Math.max(120, innerHeight * 0.33)
      Object.assign(t.style, { left: `${cx}px`, top: `${cy}px`, visibility: 'visible' })
      await wait(400)
      // 1 · the shake
      for (let i = 0; i < TUBE_MS.shakes && !cancelled; i++) {
        await t.animate(
          [0, -8, 7, -6, 8, -7, 5, 0].map((d) => ({ transform: `rotate(${d}deg)` })),
          { duration: TUBE_MS.shake, easing: 'ease-in-out' },
        ).finished
      }
      if (cancelled) return
      onStick?.()
      // 2 · one stick rises and tilts free
      const sx = cx + 66, sy = cy + 20
      Object.assign(st.style, { left: `${sx}px`, top: `${sy}px`, width: '14px', height: '150px', visibility: 'visible' })
      await st.animate([{ transform: 'translateY(0) rotate(0)' }, { transform: 'translateY(-150px) rotate(-14deg)' }],
        { duration: TUBE_MS.rise, easing: 'cubic-bezier(.2,.7,.3,1)', fill: 'forwards' }).finished
      st.getAnimations().forEach((a) => a.cancel())
      Object.assign(st.style, { top: `${sy - 150}px`, transform: 'rotate(-14deg)' })
      // 2b · the close-up: forward, large, the numeral alone, centred
      const H = Math.min(innerHeight * 0.62, 420), W = Math.round(H * 0.2)
      const L = Math.round(innerWidth / 2 - W / 2), T = Math.round(innerHeight / 2 - H / 2)
      nm.style.fontSize = `${Math.round(W * 0.62)}px`
      await st.animate([
        { left: `${sx}px`, top: `${sy - 150}px`, width: '14px', height: '150px', transform: 'rotate(-14deg)' },
        { left: `${L}px`, top: `${T}px`, width: `${W}px`, height: `${H}px`, transform: 'rotate(0)' },
      ], { duration: TUBE_MS.forward, easing: 'cubic-bezier(.3,.8,.3,1)', fill: 'forwards' }).finished
      if (cancelled) return
      nm.style.opacity = '1'
      await wait(TUBE_MS.closeup)
      nm.style.opacity = '0'
      await wait(TUBE_MS.fade)
      // 3 · the stick opens into the slip; the tube retreats to its resting place on the cabinet
      const r = rest.getBoundingClientRect()
      const slipBg = getComputedStyle(slip).backgroundColor
      const go = st.animate([
        { left: `${L}px`, top: `${T}px`, width: `${W}px`, height: `${H}px` },
        { left: `${s.left}px`, top: `${s.top}px`, width: `${s.width}px`, height: `${s.height}px`, backgroundColor: slipBg },
      ], { duration: TUBE_MS.open, easing: 'cubic-bezier(.3,.8,.3,1)', fill: 'forwards' })
      const scale = r.width / 150
      const back = t.animate([
        { left: `${cx}px`, top: `${cy}px`, transform: 'scale(1)' },
        { left: `${r.left}px`, top: `${r.top}px`, transform: `scale(${scale})` },
      ], { duration: TUBE_MS.open, easing: 'cubic-bezier(.3,.8,.3,1)', fill: 'forwards' })
      await Promise.all([go.finished, back.finished])
      if (cancelled) return
      await wait(TUBE_MS.hold1)
      // 4 · one frame: 「第N籤」 on the slip and drawer N framed
      st.style.visibility = 'hidden'
      t.style.visibility = 'hidden'
      onLit()
      await wait(TUBE_MS.hold2)
      if (!cancelled) onNamed()
    }
    void run()
    return () => { cancelled = true }
    // The run is played once per mounted reveal; the callbacks are stable refs of the parent.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <>
      <div ref={tube} className="tubeFly" data-part="tube" aria-hidden="true"><TubeArt /></div>
      <div ref={stick} className="stick" data-part="stick" aria-hidden="true">
        <span ref={label} className="stickNo dSerif" data-part="stick-no">{numeral}</span>
      </div>
    </>
  )
}
