import { useEffect, useRef, useState } from 'react'

/**
 * A secret rendered so a person can actually keep it: **a label, the value as selectable text, and
 * a copy control beside it** — `spec-self-serve-2026-09-13.md` §2b and §2c.
 *
 * **The rendered text is the guarantee; the button is the convenience.** `navigator.clipboard` is
 * undefined on an insecure origin and in some embedded browsers, and a copy button is then the only
 * path to a secret that may never be shown again. So the value is always a real text node, and a
 * failed copy leaves it untouched and says nothing alarming — an error there would tell a person
 * their key was lost while it is in front of them.
 *
 * Used for the join link (§2c and §5). It once served the key too, on the key screen that left
 * with the 2026-09-16 ruling; no member screen renders a key now.
 */
export default function CopyRow({
  label,
  value,
  part,
}: {
  label: string
  value: string
  /** `data-part` prefix. The gate reads `${part}-text` for the value and `${part}-copy` for the
   *  control, so the creator's key, the joiner's key and the join link are each addressable while
   *  sharing one structure. */
  part: string
}) {
  const [copied, setCopied] = useState(false)
  const timer = useRef<number | null>(null)

  /* The acknowledgement is the only thing here on a clock and it clears itself. It changes nothing
     the person depends on — the value is on screen either way — but it is cleared on unmount
     regardless, because a timer that outlives its screen is how a stray state change reaches the
     next one. */
  useEffect(() => () => { if (timer.current !== null) window.clearTimeout(timer.current) }, [])

  const copy = async () => {
    try {
      /* Optional chaining rather than a feature test: on an insecure origin `navigator.clipboard`
         is undefined, and this whole path is the convenience half. */
      await navigator.clipboard?.writeText(value)
      setCopied(true)
      if (timer.current !== null) window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* Deliberately silent — see the class comment. */
    }
  }

  return (
    <div className="copyRow" data-part={part}>
      <p className="copyLabel">{label}</p>
      {/* **A real text node with `user-select: all`, not an `<input readonly>`.** An input renders
          a *value*: a screen reader announces it as editable and a password manager offers to fill
          it, neither of which is true of a secret being handed over once. `SS-3` reads this as
          text. */}
      <p className="copyValue" data-part={`${part}-text`}>{value}</p>
      <button type="button" className="copyBtn" data-part={`${part}-copy`} onClick={() => void copy()}>
        {copied ? '已複製' : '複製'}
      </button>
    </div>
  )
}
