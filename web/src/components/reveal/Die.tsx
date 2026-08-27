import { useEffect } from 'react'
import { m, useAnimate, useReducedMotion } from '@/lib/motion'

/**
 * `DIE` — the cube from `design.md` §4. A real object with six faces, not a picture of a number.
 *
 * **One variable, `--die`, and the `translateZ` that closes the cube derives from it** (`calc(var(--die) / 2)`
 * in `reveal.css`). Change the value; never change the derivation — a hand-typed half is how a cube
 * develops a seam at one breakpoint and nobody sees it at the others.
 *
 * **The pips are round, and that is the system's single radius exemption** (§3). Squaring them makes
 * the face read as a grid rather than as a die.
 *
 * **Face 1 and face 4 carry red pips**, which is what a Taiwanese die looks like — `--color-pipred`,
 * its own token, deliberately not following the accent (`design.md` §1: reusing the accent measured
 * 2.74:1 on the die's face, under the 3:1 floor for a graphical object).
 *
 * **`D91`: the cube's box never changes size.** A transform moves no layout, so the tumble and the
 * landing shift 0.00 px by construction rather than by tuning — which is the only way that clause
 * can be true across three breakpoints without being re-measured at each.
 */

/** Which side of the cube each value lives on. Opposite faces sum to seven, as on a real die —
 *  1/6, 2/5, 3/4 — so the object survives being looked at from any angle mid-tumble. */
const SIDES = ['front', 'back', 'right', 'left', 'top', 'bottom'] as const
const VALUE_ON: Record<(typeof SIDES)[number], number> = {
  front: 1, back: 6, right: 2, left: 5, top: 3, bottom: 4,
}

/** The rotation that brings a value to the front, in DEGREES on each axis. Derived from `VALUE_ON`
 *  by hand once and pinned here, because a lookup is checkable and a computation over Euler angles
 *  is not.
 *
 *  **Numbers rather than transform strings, and A7 is why.** They are handed to CSS as `--tx` /
 *  `--ty` so the tumble's own final keyframe can be `calc(1440deg + var(--tx))` — four whole turns
 *  plus the landing angle. That makes the animation END on the landing orientation instead of
 *  stopping somewhere generic and then being transitioned to it. A string cannot be added to. */
const SHOW: Record<number, { x: number; y: number }> = {
  1: { x: 0,   y: 0 },
  2: { x: 0,   y: -90 },
  3: { x: -90, y: 0 },
  4: { x: 90,  y: 0 },
  5: { x: 0,   y: 90 },
  6: { x: 0,   y: 180 },
}

/** The pip positions on a 3×3 grid, by value. Index 1–9, reading left to right, top to bottom. */
export const PIPS: Record<number, number[]> = {
  1: [5],
  2: [1, 9],
  3: [1, 5, 9],
  4: [1, 3, 7, 9],
  5: [1, 3, 5, 7, 9],
  6: [1, 3, 4, 6, 7, 9],
}

const RED = new Set([1, 4])

/**
 * **A7 direction A — 拋擲, owner-ruled from three animated candidates 2026-08-19; rebuilt on
 * springs the same night after 「這些動畫沒有達到我的標準」.**
 *
 * **D109's camera swing is retracted and is gone from this file.** What replaced it is not another
 * camera: the die simply never leaves an axis it cannot land square-on from, so 「square-on at
 * rest」 is now a property of the target angles rather than of a second element correcting for
 * them. One fewer moving part, and the constraint it existed to satisfy is satisfied harder.
 * Each die is
 * thrown from its own point, spins its own number of turns, and holds its own outward offset while
 * it spins. **All three differ per die on purpose**: two cubes given one motion read as one object
 * cut in half, which is the failure the ruling's 「一擲定案」 depends on not having.
 *
 * **THE DICE TUMBLE IN PLACE. There is no fly-in, and `ex`/`ey` are gone** (owner-ruled
 * 2026-08-20). The argument is `D108`'s and it is about honesty rather than taste: **the roll
 * already exists before anyone taps.** The seed is committed at open, every pair is derived from
 * it, and the tap reveals rather than throws. Dice flying in from off-frame say *being thrown
 * now* — an entrance animating an event that happened earlier, which is `D91`'s prohibition
 * pointed at the entry instead of at the exit.
 *
 * **What was dropped is the travel, not the clearance.** The tween no longer carries `x`/`y`, and
 * the cube starts at the tumbling posture rather than arriving at it: held apart by `hold`, lifted
 * by `FLY_Y`, and small at `FLY_SCALE`. All three are still spent and still given back by the
 * settle, so the landed frame is `design.md`'s gap exactly and the body diagonal still clears the
 * top of the window. `turnz`, the camera-free landing angles and every measured clearance are
 * untouched — the change is the entry alone.
 *
 * **`RV-15` is unaffected and is now easier to satisfy.** The question it asks is what the *first
 * painted frame* contains: it must hold both dice and must not hold the answer's own position.
 * The first frame is the tumbling posture — lifted, small, unrotated — which is neither off-screen
 * nor the landed hull.
 *
 * **`turnz` is what actually breaks the lockstep, and the two attempts before it did not — for a
 * reason worth writing down, because it is a property of the keyframes and not of the numbers.**
 * The dice first shared `1080/720` against `720/1080`, then `720/1440`, and both times they flew in
 * visible lockstep, showing the same face at the same angle. Changing the totals cannot fix it:
 * every keyframe is `turns ± 360deg` or `turns + tx`, and turns are whole revolutions, so **at each
 * keyframe both cubes are at the same orientation mod 360 and the rotation travelled BETWEEN two
 * keyframes is the same for both by construction.** Only the die's own landing angle differed, and
 * one axis of difference is not enough to look like two objects.
 *
 * `turnz` is a whole turn in opposite directions — invisible at the landing, since ±360° is the
 * identity, and a barrel roll neither cube can borrow from the other at any instant in between.
 *
 * **Screenshotting the frame is what caught this, twice. Nothing in the numbers looks wrong.**
 *
 * **`hold` is the anti-collision offset, and it had to be rebuilt from scratch after the camera
 * was retracted.** The first spring build dropped it with the CSS keyframes and the two cubes
 * passed **17.7 px through each other** in flight — measured, and invisible in any still frame that
 * happens to catch them apart. A cube's rotated bounding box is its body diagonal, about 1.7× its
 * face, so two cubes spaced for their flat footprint intersect. The separation is spent while they
 * are wide and given back by the settle, so the landed frame is `design.md`'s gap exactly.
 *
 * **The old `hold`:** A cube's rotated bounding box is its body diagonal, about
 * 1.7× its face, so two cubes spaced for their flat footprint pass through each other. The gap is
 * `design.md`'s and the landed frame is gated, so the separation is bought during the spin and
 * given back before the landing.
 */
const THROW = [
  { turnx: 1080, turny: 720,  turnz: -360, hold: -62, ms: 3400 },
  { turnx: 720,  turny: 1440, turnz: 360,  hold: 62,  ms: 3700 },
] as const

/**
 * **The two throws' lengths, and they are deliberately different** (§0c amendment A, 2026-08-27:
 * 「骰子的動畫改動非常好」 — the deceleration made visible). Two dice that stop on the same frame
 * read as one object with two halves; 300 ms apart reads as two dice thrown by a person.
 *
 * **Exported, because the sweep's schedule is derived from them rather than from a second clock.**
 * §0c's binding (3) on the slot machine is that the light and the dice stop within 120 ms of each
 * other; the only way to promise that is for one number to feed both. `SEQUENCE_MS` is the longer
 * throw — the moment the composed image is still.
 */
export const SEQUENCE_MS = Math.max(...THROW.map((t) => t.ms))

/**
 * The deceleration curve, and it is the whole of amendment A.
 *
 * `cubic-bezier(.12, .72, .18, 1)` — steep out of the throw, long tail into the face. **One finite
 * motion, no re-target**: the keyframe is `whole turns + the face's own angle`, so the last turn
 * settles square-on onto `SHOW[value]` because the arithmetic lands there, not because anything
 * snaps at the end.
 *
 * **What this replaces, and why the replacement is simpler rather than richer.** The build before
 * it was three animations in a chain — a 1.05 s tween that stopped 34° short, a spring that rocked
 * over the face, and a third spring that gave the clearance back. It met every honesty constraint
 * and the owner still called it 突兀: three motions, each ending, is not a die coming to rest. The
 * rock existed to make a spring settle look like a die settling; a long ease-out does not need one.
 */
const DECELERATE = [0.12, 0.72, 0.18, 1] as const

/** Where in the motion the die gives back its clearance — the last 28%, once it is turning slowly
 *  enough that growing does not read as a lurch, and late enough that the two cubes are past each
 *  other. **The clearance itself is unchanged**: the separation is spent while they are wide and
 *  returned before the landing, which is what keeps `design.md`'s gap exact in the landed frame. */
const GIVE_BACK_AT = 0.72


/** How far below its resting place, and how much smaller, the die **sits while it spins**. **This
 *  is the clearance D109's camera used to provide** — a cube presents its body diagonal while it
 *  tumbles, about 1.7× its face, and at full size that runs off the top of this screen. Since the
 *  in-place ruling these are the starting posture rather than a waypoint travelled to: the die is
 *  already lifted and already small on the first painted frame. It arrives at its real size on the
 *  settle, which reads as the die coming toward the viewer rather than merely stopping. */
const FLY_Y = 40
const FLY_SCALE = 0.74

/**
 * Resolve once the **composed image** has held identical for three consecutive frames.
 *
 * **`RV-20`, ruled 2026-08-20: the subject is the composed image, never `.cube` alone.** This
 * function used to read one cube's computed transform, which certifies a still child inside a
 * moving parent — the dice group carries its own spring, and a cube that has stopped rotating
 * inside a group that is still translating is a die still moving on the screen. The rule the
 * failure keeps teaching: **an instrument aimed at part of its subject reports the part.**
 *
 * So it watches the die's whole field: the group's box, every `[data-part]` inside it, and every
 * cube's own transform. Any of them changing is motion, and stillness is all of them holding.
 *
 * Bounded, so a browser that never settles cannot hang the reveal — the cap is generous enough
 * that reaching it means something is wrong rather than merely slow.
 */
function stillness(el: Element, frames = 3, capMs = 1600): Promise<number> {
  /** The composed subject: the whole dice field if this die is inside one, else this element.
   *  Resolved once — the group does not appear or vanish mid-sequence, and re-querying every frame
   *  would make the instrument's own cost part of what it measures. */
  const field = el.closest('[data-part="dice-group"]') ?? el

  const snapshot = () => {
    const parts: string[] = []
    const box = (n: Element) => {
      const r = n.getBoundingClientRect()
      // Two decimals: a sub-pixel tail is still movement, and rounding it away is how a settling
      // spring gets certified as stopped.
      parts.push(`${r.left.toFixed(2)},${r.top.toFixed(2)},${r.width.toFixed(2)},${r.height.toFixed(2)}`)
    }
    box(field)
    field.querySelectorAll('[data-part]').forEach(box)
    // The cubes' rotation does not move their boxes — a rotating cube inside a still group has a
    // constant rect — so the transform is read as well. Rect alone would call a spinning die still.
    field.querySelectorAll('.cube').forEach((c) => parts.push(getComputedStyle(c).transform))
    return parts.join('|')
  }

  return new Promise((resolve) => {
    const start = performance.now()
    let prev = ''
    let same = 0
    /** **When the image first went still, not when we became sure of it.** Confirming stillness
     *  costs three frames, and a hold started at the confirmation is systematically ~120 ms late —
     *  which put the measured beat at the top of its own tolerance by construction rather than by
     *  chance. Reporting the first identical frame lets the caller subtract its instrument's cost,
     *  so the beat a person experiences is the number that was ruled. */
    let firstStill = 0
    const tick = () => {
      const t = performance.now()
      const now = snapshot()
      if (now === prev) {
        if (same === 0) firstStill = t
        same += 1
      } else {
        same = 0
      }
      prev = now
      if (same >= frames) resolve(firstStill)
      else if (t - start > capMs) resolve(t)
      else requestAnimationFrame(tick)
    }
    requestAnimationFrame(tick)
  })
}

export default function Die(
  { value, seat, onLanded, onProgress }: {
    value: number; seat: number; onLanded?: (stillAt: number) => void; onProgress?: () => void
  },
) {
  const { x, y } = SHOW[value] ?? SHOW[1]
  const t = THROW[seat % THROW.length]
  const reduce = useReducedMotion()
  const [scope, animate] = useAnimate()
  const TX = t.turnx + x
  const TY = t.turny + y

  useEffect(() => {
    // **Reduced motion is honoured by never starting, not by animating to the same place fast.**
    // With no `animate` call the element keeps `.cube`'s own resting transform from the stylesheet,
    // which IS the landed frame — §5 rule 3's "the end states still apply, instantly".
    if (reduce || !scope.current) return
    let alive = true
    // **A heartbeat, so the failsafe can be a watchdog instead of a race (`RV-19`).** The old
    // failsafe was `--tumble + 250`, a constant tuned near the sequence's length; the springs made
    // the real sequence ~2190 ms against a 1400 ms `--tumble`, so the timer won **every** run and
    // `land('animation')` never spoke. The screen was landing on a clock while the dice were still
    // moving, and `HOLD_MS` was accidentally compensating for it.
    //
    // This pings once per animation frame for as long as the sequence is alive. What the watchdog
    // then measures is **frames not arriving** — a dead tab, a chain that threw — which is what a
    // failsafe is actually for, and which no change to a spring or a duration can ever outgrow.
    let beating = true
    const beat = () => { if (beating && alive) { onProgress?.(); requestAnimationFrame(beat) } }
    requestAnimationFrame(beat)
    void (async () => {
      // **ONE finite motion, fast then slow, ending square-on** — §0c amendment A.
      //
      // The rotation keyframes are `whole turns + the face's own angle`, so the die arrives at
      // `SHOW[value]` because that is where the arithmetic ends. Nothing snaps, nothing re-targets,
      // and there is no second animation in flight when the sequence claims to be over — which is
      // what the three-stage chain before it could never quite promise.
      //
      // **A tween and not a spring, and the reason is unchanged:** a spring's settling time does
      // not depend on how far it travels, so three whole turns on a spring stiff enough to feel
      // crisp is a blur, and one loose enough to read overshoots by a quarter-turn. The curve does
      // the slowing.
      //
      // **The clearance is given back inside the same motion, not after it.** `x`, `y` and `scale`
      // hold their thrown values until `GIVE_BACK_AT` and then arrive — one call, so there is still
      // exactly one animation on this element from the first frame to the last. The earlier build
      // ran the arrival as its own spring and measured 27.7 px of cube-on-cube intersection when it
      // overlapped the rock; here the die is turning slowly and is already nearly square-on by the
      // time it grows.
      const hold = { duration: t.ms / 1000, ease: DECELERATE, times: [0, GIVE_BACK_AT, 1] }
      await animate(
        scope.current,
        {
          rotateX: [0, TX], rotateY: [0, TY], rotateZ: [0, t.turnz],
          x: [t.hold, t.hold, 0],
          y: [FLY_Y, FLY_Y, 0],
          scale: [FLY_SCALE, FLY_SCALE, 1],
        },
        {
          duration: t.ms / 1000,
          ease: DECELERATE,
          x: hold, y: hold, scale: hold,
        },
      )
      if (!alive) return
      const stillAt = await stillness(scope.current)
      beating = false
      if (alive) onLanded?.(stillAt)
    })()
    return () => { alive = false; beating = false }
    // Mount-only: the round's dice are fixed before this component exists, so a re-run would be a
    // second throw of the same result.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="die" data-part="die" data-value={value} aria-hidden="true">
      <m.div
        ref={scope}
        className="cube"
        // **`initial` and not the effect, and the difference is one painted frame.** `useAnimate`
        // runs in an effect, which is after the browser has painted — so without this the die is
        // drawn once at its RESTING place and only then jumps into its spinning posture. Measured
        // on the fly-in build: the first sampled frame reported the landed hull exactly. A frame is
        // 16 ms and nobody would name it, but it is the answer's own position shown before the
        // roll, and `RV-15` asks what the first painted frame contains.
        //
        // **Since the in-place ruling this carries the whole starting posture** — held apart,
        // lifted and small — because there is no longer a travel keyframe to establish it. The
        // three values are the same ones the settle gives back, written once here and once there.
        initial={reduce ? false : { x: t.hold, y: FLY_Y, scale: FLY_SCALE }}
        style={{ ['--tx' as string]: `${x}deg`, ['--ty' as string]: `${y}deg` }}
      >
        {SIDES.map((side) => {
          const v = VALUE_ON[side]
          return (
            <div key={side} className="face" data-die-side={side} data-face={v}>
              {Array.from({ length: 9 }, (_, i) => i + 1).map((cell) => (
                <span key={cell} className="dieCell">
                  {PIPS[v].includes(cell) && (
                    <i className="pip" data-red={RED.has(v) ? 'yes' : 'no'} />
                  )}
                </span>
              ))}
            </div>
          )
        })}
      </m.div>
    </div>
  )
}
