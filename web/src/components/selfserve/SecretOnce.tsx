import CopyRow from './CopyRow'

/**
 * §2b's treatment for a secret the server prints once — `spec-self-serve-2026-09-13.md`.
 *
 * **One component, used by the creator's key AND the joiner's key, and that is the point.** §4.2
 * asks for 「the identical §2b treatment」 on the joiner's screen, because it is the same trap one
 * step removed and a spec protecting only the creator would miss half the people who meet it. Two
 * copies of a treatment are two things to keep identical; one component is identical by
 * construction, and `SS-3` and `SS-5` read the same parts on both screens.
 *
 * **What the owner ruled, and what this spends instead.** The evaluator recommended refusing to
 * continue until the key had been copied; **the owner ruled no block** — recovery arrives with
 * tier 2 identity, so it is a block for a case the next tier removes. Not re-argued here. The
 * licence he *did* leave — a copy control and one line of notice — is spent on the shape most
 * likely to keep the key:
 *
 * 1. **Visible, selectable text rather than only a button's payload** — `CopyRow`'s job, and its
 *    reasoning lives there.
 * 2. **The notice sits ABOVE the continue control**, not after it (`SS-3` asserts the order).
 * 3. **Continue is explicit and live from the first frame**, and **nothing else dismisses this
 *    screen**: no auto-advance, no dismiss-on-outside-tap, no timer. *Not showing it twice is the
 *    ruling; throwing it away on a stray tap is not.*
 *
 * **No arrival animation** (乙 §1a rule 5): this screen renders in response to a `201`, so it
 * answers what just happened, and a thing that fades in has not happened yet.
 *
 * **It holds no member-facing sentence of its own.** `notice` is passed in because §2b says the
 * words are `server_copy.py`'s — the one line that decides whether a person keeps their seat is
 * not a string to invent in markup.
 */
export default function SecretOnce({
  label,
  secret,
  notice,
  continueLabel,
  onContinue,
  part,
}: {
  label: string
  secret: string
  notice: string
  continueLabel: string
  onContinue: () => void
  /** `data-part` prefix, so the gate can tell the creator's key from the joiner's while reading
   *  the same structure on both. */
  part: string
}) {
  return (
    <section className="secretOnce" data-part={part}>
      <CopyRow label={label} value={secret} part={`${part}-secret`} />

      {/* §2b item 2 — **above** the continue control, and it states what is lost rather than what
          to do. Backend's sentence. */}
      <p className="secretNotice" data-part={`${part}-notice`}>{notice}</p>

      {/* Ruling ①: live from the first frame, no block, and the only thing that leaves this
          screen. */}
      <button type="button" className="act" data-part={`${part}-continue`} onClick={onContinue}>
        {continueLabel}
      </button>
    </section>
  )
}
