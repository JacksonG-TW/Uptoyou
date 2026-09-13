import { useCallback, useEffect, useState } from 'react'
import { fetchMembers, reissueJoinLink, type Members } from '@/lib/selfserve'
import type { Device } from '@/lib/round'
import CopyRow from './CopyRow'
import { LINK_LIFE } from './copy'

/**
 * The package's **step 3** — the invite screen: the link, the seat list, re-issue. **Never the
 * key.**
 *
 * **One component used by two screens, and that is the point of extracting it.** It renders inside
 * the create flow (`Create`'s 2c, where the link is already in hand from the `201`) and as the
 * durable `/circle` route a creator can return to. Two copies of this panel would be two things to
 * keep identical, and `SS-2`'s 「the invite screen carries no key」 would have to hold twice; one
 * component holds it once. Same reasoning as `SecretOnce` for the two key screens.
 *
 * **Why the durable route exists — `SS-13`, and it is a defect fix rather than a new screen.** Step
 * 3 lived only in the create flow's memory: `/create` showed step 1 again and nothing else reached
 * the link or the re-issue control. **The ruled hour is what made that urgent** — the ticket dies
 * in an hour, the remedy is re-issue, and re-issue was reachable only in the minutes right after
 * creation. So: *your link expires and you cannot make another one.* Backend built re-issue before
 * expiry precisely so a late friend costs nobody anything, and that argument holds only while the
 * control can be found.
 *
 * **This panel never renders `device.token`.** It is handed the credential because the seat list
 * and re-issue both need it, and it is used for `Authorization` and nothing else. The key belongs
 * to `SecretOnce`, once, on a screen this one is never on.
 */

/**
 * **The seat list refreshes, and `SS-8` is why.** It used to be fetched once at mount, so two joins
 * left it reading `1/10` for ever and the duplicate-nickname question was *untestable* rather than
 * failing. A screen whose subject is 「who has arrived」 cannot answer it from a single read taken
 * before anyone had.
 *
 * **Reading rather than subscribing, and that is a considered trade the evaluator ruled on.** The
 * SSE stream is circle-scoped but round-shaped — `snapshot` · `round_opened` · `pooled` · `closed`
 * — and **a seat joining is none of those**. Using it would mean either a new event type on
 * backend's wire or a client that re-fetches on unrelated traffic and misses the event it actually
 * cares about.
 *
 * **On mount and on window focus — NOT a timer** (evaluator-ruled 2026-09-13). My first build used
 * a five-second interval; the ruling is that **the creator looks at this screen when they come back
 * to it, not continuously**, so the read belongs on the moment of looking. A timer would poll a
 * phone in a pocket for an hour to answer a question nobody is asking, and the one moment it exists
 * to catch — coming back to see who arrived — is exactly when `focus` fires.
 */

export default function InvitePanel({
  device,
  link,
  onLink,
}: {
  device: Device
  /** The current join link, or `''` when this screen cannot read one — see `Circle`. Passed in
   *  rather than fetched here, because the create flow already holds it from the `201` and must not
   *  ask for it again. */
  link: string
  /** Called with a fresh link after a re-issue, so whichever screen owns it stays in step. */
  onLink: (next: string) => void
}) {
  const [seats, setSeats] = useState<Members | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const readSeats = useCallback(async () => {
    try {
      setSeats(await fetchMembers(device))
    } catch {
      /* **A seat list that fails to load renders nothing rather than an error.** The act of this
         screen is the link; the list is who is here so far. A refusal banner over a working invite
         would make a person think the link was broken. And on a poll it would flash. */
    }
  }, [device])

  useEffect(() => {
    void readSeats()
    /* `focus` and `visibilitychange` both, because they catch different returns: `focus` is another
       window coming forward, `visibilitychange` is a tab or a phone screen coming back. Either is
       the person looking again, which is the moment the ruling puts the read on. The guard keeps a
       hidden tab from reading when `focus` fires without the page being visible. */
    const look = () => { if (!document.hidden) void readSeats() }
    window.addEventListener('focus', look)
    document.addEventListener('visibilitychange', look)
    return () => {
      window.removeEventListener('focus', look)
      document.removeEventListener('visibilitychange', look)
    }
  }, [readSeats])

  const reissue = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      onLink(await reissueJoinLink(device))
      /* **Re-read rather than assume.** §5 says re-issuing ejects nobody and `SS-7` checks the
         count is unchanged — a screen that skipped this would assert the rule instead of showing
         it, and would keep a stale list if the rule ever broke. */
      void readSeats()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* **No link box when there is no link to show, rather than an empty one.** There is no GET
          that returns the current ticket — the only route that yields one MINTS one and revokes the
          current one, so a screen that fetched a link on arrival would kill the link the creator
          had already shared, by the act of looking at it. Raised with backend; until it lands this
          screen offers the remedy without pretending to show the thing. A remembered link would be
          worse: it would quietly be an hour dead on the one screen whose job is the link. */}
      {link && (
        <>
          <CopyRow part="join-link" label="邀請連結" value={link} />
          <p className="ssLead">把這條連結貼給朋友，誰點誰就有座位。</p>
          {/* Under the link, above the re-issue control — the life of the link stated where the
              link is, and the fix the next thing the eye reaches. */}
          <p className="ssNote" data-part="link-life">{LINK_LIFE}</p>
        </>
      )}

      {/* §5 — **one control, never two.** There is no standalone revoke: revoking alone leaves a
          circle nobody can join, and that is a state a worried person reaches by accident — they
          press the frightening button to shut a stranger out and their real friend's link dies with
          it. Whatever they press must leave them a link to share, so the action is
          「換一條新的連結」 and the consequence is stated beside it.

          **It ejects nobody and the copy does not imply that it does.** A sentence reading like
          removal gets pressed for the wrong reason, and then the stranger is still there. Since the
          ruled hour it is also **the fix for a friend who tapped late**, which will be the common
          case — another reason the wording is an action rather than a removal. */}
      <button type="button" className="ssMinor" data-part="reissue" onClick={() => void reissue()} disabled={busy}>
        換一條新的連結
      </button>
      <p className="ssNote">舊的連結就不能用了，已經進來的人不受影響。</p>

      {/* The seat list. **Every row comes from the server and none from any screen's own state** —
          when the spec asked for this list no endpoint could supply it, and the tempting fix was to
          render the creator's row from the nickname they had just typed: it would have looked
          right, never updated, and made `SS-8` unmeasurable **while appearing to pass**.

          **`cap` comes from the payload, never from the markup** — it is `issue.SEAT_CAP` and it has
          moved once already. **No client-side cap** (§7): this counts, it does not gate.

          **Duplicates render as the server has them** (`SS-8`): no marker, no 「(2)」. The React key
          is the index for exactly that reason — the nickname is not unique and must not be treated
          as an identity. */}
      {seats && (
        <div className="ssSeats" data-part="seat-list">
          <p className="copyLabel">
            這個圈子裡的人 <span className="ssCount" data-part="seat-count">{seats.seats}/{seats.cap}</span>
          </p>
          <ul>
            {seats.members.map((m, i) => (
              <li key={i} data-part="seat-row">{m.nickname}</li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="ssErr" data-part="selfserve-error">{error}</p>}
    </>
  )
}
