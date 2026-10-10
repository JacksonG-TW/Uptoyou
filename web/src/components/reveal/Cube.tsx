import { forwardRef } from 'react'
import { RED } from './Die'

/**
 * **A die at rest on the cabinet, in a 3/4 view, value on top** (owner 「A」 on preview v9:
 * 「新的立體骰子好看」; `spec-reveal-qiantong-2026-10-09.md`, Layout). A CSS 3-D cube: six faces,
 * each `translateZ(size / 2)` from the centre, so the object is real under any rotation the flight
 * puts it through, and it comes to rest at `REST` with the rolled value on its TOP face.
 *
 * **The two visible sides are never opposite each other**, and opposite faces sum to seven, as on a
 * real die — a reader who works the pips out from the sides gets the same die (two v9 reads did).
 * Face 1 and face 4 carry red pips, as the reveal's thrown die always has.
 *
 * Decoration for a screen reader: `aria-hidden`. The rolled pair is said in text by the pairs list.
 */

/** The resting pose: the top face toward the viewer, the front and right sides showing. The flight
 *  in `Reveal.tsx` ends its spin on exactly this transform, so nothing snaps at the landing. */
export const REST = 'rotateX(-32deg) rotateY(-42deg)'

/** Pip centres in unit space, by value. Six is drawn in two columns of three. */
const SPOTS: Record<number, [number, number][]> = {
  1: [[0.5, 0.5]],
  2: [[0.25, 0.25], [0.75, 0.75]],
  3: [[0.25, 0.25], [0.5, 0.5], [0.75, 0.75]],
  4: [[0.25, 0.25], [0.75, 0.25], [0.25, 0.75], [0.75, 0.75]],
  5: [[0.25, 0.25], [0.75, 0.25], [0.5, 0.5], [0.25, 0.75], [0.75, 0.75]],
  6: [[0.25, 0.22], [0.75, 0.22], [0.25, 0.5], [0.75, 0.5], [0.25, 0.78], [0.75, 0.78]],
}

/** Which value sits on each face once `value` is on top: the front is the lowest value that is not
 *  `value` or its opposite, the right the next one off both axes. Pure, so the gate can recompute it. */
export function facesFor(value: number): Record<'top' | 'front' | 'right' | 'back' | 'left' | 'bottom', number> {
  const all = [1, 2, 3, 4, 5, 6]
  const front = all.find((x) => x !== value && x !== 7 - value) ?? 1
  const right = all.find((x) => ![value, 7 - value, front, 7 - front].includes(x)) ?? 2
  return { top: value, front, right, back: 7 - front, left: 7 - right, bottom: 7 - value }
}

const FACE_TRANSFORM = {
  front: 'translateZ(var(--half))',
  back: 'rotateY(180deg) translateZ(var(--half))',
  right: 'rotateY(90deg) translateZ(var(--half))',
  left: 'rotateY(-90deg) translateZ(var(--half))',
  top: 'rotateX(90deg) translateZ(var(--half))',
  bottom: 'rotateX(-90deg) translateZ(var(--half))',
} as const

const Cube = forwardRef<HTMLDivElement, {
  value: number
  /** `row` for die one (it rests at its row's start), `col` for die two (on top of its column). */
  axis: 'row' | 'col'
  /** The spinning element, for the flight to animate. */
  spinRef?: React.Ref<HTMLDivElement>
  style?: React.CSSProperties
}>(function Cube({ value, axis, spinRef, style }, ref) {
  const faces = facesFor(value)
  return (
    <div ref={ref} className="cube" data-part={`axis-die-${axis}`} data-value={value} aria-hidden="true" style={style}>
      <div ref={spinRef} className="cubeSpin">
        {(Object.keys(FACE_TRANSFORM) as (keyof typeof FACE_TRANSFORM)[]).map((side) => (
          <div key={side} className="cubeFace" data-side={side} style={{ transform: FACE_TRANSFORM[side] }}>
            {SPOTS[faces[side]].map(([x, y], i) => (
              <i key={i} className="cubePip" data-red={RED.has(faces[side]) ? 'yes' : undefined}
                style={{ left: `${x * 100}%`, top: `${y * 100}%` }} />
            ))}
          </div>
        ))}
      </div>
    </div>
  )
})

export default Cube
