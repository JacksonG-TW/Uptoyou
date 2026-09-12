import type { CSSProperties } from 'react'
/**
 * `motion`, kept small on purpose — D104 amendment (`115ad08`), approved on a stated size budget.
 *
 * **`domAnimation`, not `domMax`.** The minimal feature set carries animations, variants and the
 * basic gestures; it does **not** carry layout animation or drag, and this surface wants neither.
 * `domMax` is roughly a third larger for two features nothing here uses.
 *
 * **`strict` is the part that makes the budget real rather than remembered.** Under `strict`, a
 * `motion.div` anywhere in the tree throws at render instead of quietly pulling the full feature
 * bundle in beside the lazy one. So the promise 「we only ship the small half」 is enforced by the
 * build, not by everyone remembering to type `m.` — which is exactly the kind of rule that decays.
 *
 * **Statically imported, never fetched.** `LazyMotion` also accepts `() => import(...)`, which
 * would split the features into a chunk the browser asks for at runtime. §6's dead-wifi rule is
 * about external assets, but a screen that needs a second request before it can animate is a screen
 * that behaves differently on a slow connection, and the whole point of A7 is what a person sees in
 * the first two seconds. One bundle, one request, no second act.
 */
export { LazyMotion, domAnimation, m, useReducedMotion, useAnimate } from 'motion/react'

/**
 * 乙's arrival — `spec-motion-arrival-2026-09-11.md` §1a, owner 「1」 after 「動態感太少」.
 *
 * **The arrival is CSS, not `motion`, and that is the whole reason this helper is three lines.**
 * §1a rule 1 is *once per mount, and a state change inside the screen never re-fires it*. A CSS
 * animation on an element does exactly that for free: it runs when the element mounts and a
 * re-render does not restart it. Expressed through `motion` it would be a variant plus an
 * `initial`/`animate` pair on every block, and every one of them a place for a re-render to
 * re-trigger it — the rule would then hold by everyone remembering, which is the kind of rule
 * `motion.ts` already says decays.
 *
 * **All this returns is the block's position in the stagger.** The duration (`--t-flood`), the
 * easing, the 90 ms step, the reduced-motion opt-out and the zero-shift guarantee are all in
 * `index.css`'s `.arrive` rule, in one place, so `YI-4`, `YI-5` and `YI-10` each have exactly one
 * thing to read. **The 90 ms appears once in the stylesheets and nowhere in the TypeScript** —
 * `YI-10` greps for a seventh loose duration and must not find one here.
 *
 * The cast is React's own gap: `CSSProperties` has no index signature for custom properties, and
 * a `style` object is still the only way to pass a per-element value to CSS.
 */
export function arrive(step: number): CSSProperties {
  return { '--arrive-step': step } as CSSProperties
}
