import { m, useReducedMotion } from '@/lib/motion'
import { PIPS } from './Die'

/**
 * The ground the dice are thrown onto — 網點即骰點, evaluator-ruled 2026-08-20 under D101's
 * delegation.
 *
 * **The owner's complaint was 單調 and the licence was a static image; the ruling spends it on
 * pattern instead.** The halftone dot is print's own texture AND the die's pip — the one mark this
 * product owns — so the ground can be busy without importing a second visual language. Riso-print
 * logic: paper, spot colours, halftone. Pure CSS tiles, **zero image assets**, so §6's dead-wifi
 * rule is untouched by a decision about decoration.
 *
 * **The glow is gone. Print does not glow.** It survived two tunings on the argument that a light
 * source is not a shadow, and the ruling retires the whole idea rather than the sizing: a page that
 * behaves like paper cannot have a lamp behind it.
 *
 * **Tumble — neutral, and neutral is a D91 requirement rather than a taste.** A field of even dots
 * plus a denser table band at the bottom edge for the dice to land on. **No cluster may read as a
 * die face before the result exists**, because a ground that answers first is the animation
 * asserting something it does not yet have.
 *
 * **Staged — the ground repeats the truth, it never invents it.** This round's real pair prints as
 * two poster-scale faces in a darker step of the flood's own colour. They are the *stored* dice, so
 * `RV-16` is untouched — nothing appears before landed, and nothing on screen mid-tumble
 * distinguishes the winner. The tone sits under the text layer: **copy is always the brightest
 * layer.**
 *
 * **A face needs its border to read as a face.** Cropped bare dots read as blobs, which is the
 * rubric's own named slop; the 4px tone rule is what makes the shape legible while it bleeds off
 * the edge.
 */

/** Slow enough to be felt rather than watched, and out of phase so the two layers never move
 *  together — synchronised drift reads as the page wobbling rather than as paper breathing. */
const DRIFT = [
  { d: 6.5, delay: 0, x: [0, 7, 0], y: [0, -9, 0] },
  { d: 7.4, delay: -2.6, x: [0, -6, 0], y: [0, 8, 0] },
]

/**
 * **The ground's six tilted dice** — §0c amendment D, owner 2026-08-27: 「綠底＋不同角度的立體骰子，
 * 我認為很棒，可以按照你說的四色」. Replaces the two flat poster faces.
 *
 * Positions, sizes and angles are `design-proposals/reveal-ground.html` §五's, which is the page
 * the ruling was made from. `x`/`y` are percentages of the stage, `s` is the cube's edge as a
 * percentage of the stage's width, `r` is the flat rotation of the whole cube's box, `rx`/`ry` the
 * 3-D turn of the cube inside it. **Fixed, never random** — a ground that lands differently on
 * every load reads as a glitch, and this one is a record of a result.
 */
const GROUND = [
  { x: -6, y: -20, s: 19, r: -8,  rx: -22, ry: 28 },
  { x: 82, y: -12, s: 17, r: 11,  rx: 18,  ry: -30 },
  { x: 48, y: 62,  s: 11, r: -14, rx: -26, ry: 22 },
  { x: -4, y: 66,  s: 14, r: 5,   rx: 16,  ry: 34 },
  { x: 86, y: 54,  s: 15, r: -4,  rx: -20, ry: -24 },
  { x: 66, y: 84,  s: 9,  r: 16,  rx: 24,  ry: 18 },
] as const

/** The face opposite each value — a real die's pairs sum to seven. Used to REFUSE a side, never to
 *  pick one: a cube showing 3 and 4 at once is not a die, and a ground made of impossible dice is
 *  decoration pretending to be evidence. */
const OPPOSITE: Record<number, number> = { 1: 6, 2: 5, 3: 4, 4: 3, 5: 2, 6: 1 }

/** The two sides a cube may show beside `value`: any neighbour, never the opposite face. The mock's
 *  own derivation, kept rather than re-invented so the built ground and the ruled page agree. */
function neighbours(value: number): [number, number] {
  const a = (value % 6) + 1
  const b = OPPOSITE[a] === value ? ((value + 1) % 6) + 1 : ((value + 2) % 6) + 1
  return [a, b]
}

function Pips({ value }: { value: number }) {
  return (
    <>
      {Array.from({ length: 9 }, (_, i) => i + 1).map((cell) => (
        <i key={cell} className={PIPS[value]?.includes(cell) ? 'p' : undefined} />
      ))}
    </>
  )
}

function GroundCube({ value, at }: { value: number; at: (typeof GROUND)[number] }) {
  const [side, top] = neighbours(value)
  return (
    <span
      className="cube3"
      style={{
        left: `${at.x}%`, top: `${at.y}%`,
        width: `${at.s}%`, aspectRatio: '1',
        transform: `rotate(${at.r}deg)`,
        // **The half-depth is a percentage of the cube's own width**, so the six faces close at
        // every size without a second number per cube. `--half` is what the stylesheet's
        // `translateZ` reads; typing a pixel depth here is how a cube comes apart when the stage
        // is scaled (`--k`).
        ['--half' as string]: '50cqw',
      }}
    >
      <span className="c" style={{ transform: `rotateX(${at.rx}deg) rotateY(${at.ry}deg)` }}>
        <span className="f front"><Pips value={value} /></span>
        <span className="f right"><Pips value={side} /></span>
        <span className="f top"><Pips value={top} /></span>
      </span>
    </span>
  )
}

export default function Field({ dice, staged }: { dice?: readonly number[]; staged: boolean }) {
  const reduce = useReducedMotion()
  /** Reduced motion stops the drift **on a legible frame** rather than removing the layers — the
   *  halftone is texture, not motion, and it is what the screen looks like. */
  const drift = (i: number) =>
    reduce
      ? {}
      : {
          animate: { x: DRIFT[i].x, y: DRIFT[i].y },
          transition: {
            duration: DRIFT[i].d,
            delay: DRIFT[i].delay,
            repeat: Infinity,
            ease: 'easeInOut' as const,
          },
        }

  return (
    <div className="field" data-part="field" aria-hidden="true">
      <m.span className="halftone halftoneA" {...drift(0)} />
      <m.span className="halftone halftoneB" {...drift(1)} />
      {/* The table the dice land on — present only while they are in the air, because once they
          have landed the composition is a printed page and not a table. */}
      {!staged && <span className="tableBand" />}
      {/* **Gated on `staged` AND on the values existing.** Two conditions rather than one: `staged`
          is the screen's own state and `dice` is what the server stored, and a ground drawn from a
          state without a value is exactly the ground that could answer first (`RV-16`).

          **Six cubes, and each front face is one of this round's two stored values — three each.**
          Rejected in the ruling: all six values, which would have the ground assert numbers that
          were never rolled. The two visible sides are real neighbours of the front, so every cube
          on the page is a die that could exist. */}
      {staged && dice && dice.length >= 2 && (
        <span className="posters" data-part="ground-dice">
          {GROUND.map((at, i) => (
            <GroundCube key={`${at.x}-${at.y}`} value={dice[i % 2]} at={at} />
          ))}
        </span>
      )}
    </div>
  )
}
