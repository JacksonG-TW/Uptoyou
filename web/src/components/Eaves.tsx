import { useEffect, useRef, useState } from 'react'

/**
 * Roof C, 整片屋頂 — the temple roof across the top of the inner screens (owner 「照建議做」,
 * 2026-10-09; `idea & img/frontend/specs/spec-roof-inner-screens-2026-10-09.md`).
 *
 * **Decoration only**: no words, no control, `aria-hidden`. It sits under the bar and scrolls with
 * the page. Its room comes from `--eaves-h` (`switcher.css`), which `main.tsx` turns on by setting
 * `data-eaves` on `<html>` for the ruled screens. **Not on the reveal**: its first view is full,
 * and the roof pushed the answer card past the fold in the preview the owner judged.
 *
 * **Drawn from the viewport width, not stretched.** A `preserveAspectRatio="none"` SVG would pull
 * the upturned corners and the round tile ends out of shape at every width but one. The geometry
 * is the preview's own, so what ships is what was judged.
 */
/** **The roof's own box decides its width, not the window.** A scrollbar that appears after first
 *  paint (the page grew tall enough to scroll) narrows the box by its width with no `resize` event,
 *  and a width read from the window then drew the right-hand corner past the edge, where
 *  `overflow: hidden` cut its upturned tip off (the reviewer's check on 3d1c796). */
function useBoxWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(() => document.documentElement.clientWidth)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(Math.round(el.getBoundingClientRect().width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

/** **The scale is decided by the SAME media query that sets `--eaves-h`** (`switcher.css`). A
 *  `clientWidth < 700` test excludes the scrollbar while the media query includes it, so a window
 *  of about 700–716 px drew the small roof over the large room (the reviewer's catch on 95c405c). */
const NARROW = '(max-width: 699px)'
function useNarrow() {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches)
  useEffect(() => {
    const mq = window.matchMedia(NARROW)
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}

export default function Eaves() {
  const [box, W] = useBoxWidth()
  const s = useNarrow() ? 0.7 : 1
  const H = Math.round(118 * s)
  const top = 30 * s, eaveY = H - 26 * s, lip = 46 * s, rx = lip + 40 * s
  const roof = `M ${rx} ${top} L ${W - rx} ${top} Q ${W - lip} ${eaveY - 30 * s} ${W - 4 * s} ${eaveY - 24 * s} `
    + `Q ${W - lip * 0.6} ${eaveY + 4 * s} ${W - lip - 20 * s} ${eaveY} L ${lip + 20 * s} ${eaveY} `
    + `Q ${lip * 0.6} ${eaveY + 4 * s} ${4 * s} ${eaveY - 24 * s} Q ${lip} ${eaveY - 30 * s} ${rx} ${top} Z`
  const ridge = `M ${rx} ${top} L ${W - rx} ${top} Q ${W - rx + 40 * s} ${top} ${W - rx + 56 * s} ${2 * s} `
    + `L ${W - rx + 44 * s} ${top - 12 * s} Q ${W - rx + 30 * s} ${top - 10 * s} ${W - rx} ${top - 10 * s} `
    + `L ${rx} ${top - 10 * s} Q ${rx - 30 * s} ${top - 10 * s} ${rx - 44 * s} ${top - 12 * s} `
    + `L ${rx - 56 * s} ${2 * s} Q ${rx - 40 * s} ${top} ${rx} ${top} Z`
  const stripes = Array.from({ length: Math.ceil(W / (14 * s)) }, (_, i) => i * 14 * s)
  const ends = Array.from({ length: Math.max(0, Math.floor((W - 2 * lip - 40 * s) / (22 * s))) }, (_, i) => lip + 30 * s + i * 22 * s)

  return (
    <div ref={box} className="eaves" data-part="eaves" aria-hidden="true">
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} focusable="false">
        <defs><clipPath id="eaves-roof"><path d={roof} /></clipPath></defs>
        <path d={roof} fill="var(--color-ink)" />
        <g clipPath="url(#eaves-roof)">
          {stripes.map((x) => <rect key={x} x={x} y={0} width={2 * s} height={H} fill="var(--color-gold)" opacity={0.22} />)}
        </g>
        <path d={roof} fill="none" stroke="var(--color-gold)" strokeWidth={2 * s} />
        <path d={ridge} fill="var(--color-ink)" stroke="var(--color-gold)" strokeWidth={1.5 * s} />
        {ends.map((x) => <circle key={x} cx={x} cy={eaveY + 5 * s} r={5 * s} fill="var(--color-gold)" stroke="var(--color-ink)" strokeWidth={1.5 * s} />)}
      </svg>
    </div>
  )
}
