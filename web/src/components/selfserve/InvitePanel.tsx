import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchMembers, readInviteRole, reissueJoinLink, type InviteRole, type Members } from '@/lib/selfserve'
import type { Device } from '@/lib/round'
import CopyRow from './CopyRow'
import { LINK_EXPIRED, LINK_LIFE, MEMBER_INVITE, linkLive } from './copy'

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
  creator = false,
}: {
  device: Device
  /** The current join link, or `''` when this screen cannot read one — see `Circle`. Passed in
   *  rather than fetched here, because the create flow already holds it from the `201` and must not
   *  ask for it again. */
  link: string
  /** Called with a fresh link after a re-issue, so whichever screen owns it stays in step. */
  onLink: (next: string) => void
  /** `true` only from the create flow, which renders solely for the person who just made the
   *  circle — so it skips the role read and draws the control at once, exactly as before
   *  (Addendum 4, point 4: the create flow is unchanged). `/circle` leaves it `false` and asks. */
  creator?: boolean
}) {
  const [seats, setSeats] = useState<Members | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  /* **`null` until the read answers, and the slot draws nothing while it is `null`** (Addendum 4,
     point 3). Drawing the control first and removing it on a 403 would flash a button at exactly
     the reader it was ruled away from. */
  const [role, setRole] = useState<InviteRole | null>(creator ? { role: 'creator', status: null } : null)

  /* **One read decides the role and, for the creator, carries the link's status** (Addendum 5). It
     runs on mount, on the person looking again, and after a successful re-issue — never on a timer.
     **The create flow never reads**: it renders only for the person who just made the circle, and
     it has no status line.

     **An in-flight guard, because one return fires two events.** Coming back to a tab raises
     `visibilitychange` and then `focus`; without the guard that is two `GET`s for one look, and
     SS-19 counts exactly one. The previous answer stays on screen while a re-read is out, so the
     slot never blanks on focus. */
  const mounted = useRef(true)
  const reading = useRef(false)
  const again = useRef(false)
  /* `fresh` is for the re-issue: its answer must reflect the NEW ticket, so a read already out
     (started before the re-issue) is followed by one more rather than trusted. A focus return
     never passes it, which is what keeps one look at one request. */
  const readRole = useCallback(async (fresh = false) => {
    if (creator) return
    if (reading.current) { if (fresh) again.current = true; return }
    reading.current = true
    try {
      do {
        again.current = false
        const next = await readInviteRole(device)
        if (mounted.current && !again.current) setRole(next)
      } while (again.current && mounted.current)
    } finally {
      reading.current = false
    }
  }, [creator, device])

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  /* **The line must not lie while the creator looks at it.** One `setTimeout` at `expires_at − now`
     flips `live` to `expired` locally, with no request; there is no interval (the ruling against
     polling stands). **Every re-read sets a new `role` object, so this effect's cleanup clears the
     old timeout on each re-read**, and on unmount. The delay is at most an hour, far inside
     `setTimeout`'s 24.8-day ceiling. */
  useEffect(() => {
    if (role?.role !== 'creator' || !role.status?.active || !role.status.expiresAt) return
    const at = role.status.expiresAt
    const id = window.setTimeout(() => {
      setRole({ role: 'creator', status: { active: false, expired: true, expiresAt: at } })
    }, Math.max(0, at.getTime() - Date.now()))
    return () => window.clearTimeout(id)
  }, [role])

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
    void readRole()
    /* `focus` and `visibilitychange` both, because they catch different returns: `focus` is another
       window coming forward, `visibilitychange` is a tab or a phone screen coming back. Either is
       the person looking again, which is the moment the ruling puts the read on. The guard keeps a
       hidden tab from reading when `focus` fires without the page being visible. */
    const look = () => { if (!document.hidden) { void readSeats(); void readRole() } }
    window.addEventListener('focus', look)
    document.addEventListener('visibilitychange', look)
    return () => {
      window.removeEventListener('focus', look)
      document.removeEventListener('visibilitychange', look)
    }
  }, [readSeats, readRole])

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
      /* A re-issue gives a new `expires_at`, so the status line is re-read with the seats. */
      void readRole(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* **A link box only when a link is genuinely in hand**, which is the create flow (the `201`
          carried it) and after a re-issue. **On `/circle` it is permanently absent and that is the
          design, not a shortfall** — `join_ticket` stores only `token_sha256`, so no endpoint can
          return a link and none ever will; `GET …/join-ticket` answers the link's *status*. The
          only route that yields a link MINTS one and revokes the current one, so fetching on
          arrival would kill the link the creator had already shared by the act of looking at it.
          A remembered link would be worse again: quietly an hour dead, on the one screen whose
          whole job is the link. */}
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
      {/* **A seat that is not the creator's sees one line instead** (Addendum 4, on the owner's
          `91d146b`: re-issue is the creator's seat only). The control used to render for everyone
          and refuse most of them 250 px away; this states the rule and the remedy before anything
          is pressed. `unknown` keeps the control — the server's 403 is the backstop. */}
      {/* **The creator's status line, directly above the control it explains** (Addendum 5). No
          line when there is no ticket (a circle made with `upto.issue`), for a member, for an
          unknown answer, or before the read has answered. Ink, never the hot colour, in both
          states — nothing is wrong with what the creator did. */}
      {role?.role === 'creator' && role.status?.active && role.status.expiresAt && (
        <p className="ssStatus" data-part="link-status" data-state="live">{linkLive(role.status.expiresAt)}</p>
      )}
      {role?.role === 'creator' && role.status?.expired && (
        <p className="ssStatus" data-part="link-status" data-state="expired">{LINK_EXPIRED}</p>
      )}
      {role?.role === 'member' && (
        <p className="ssNote" data-part="reissue-member">{MEMBER_INVITE}</p>
      )}
      {(role?.role === 'creator' || role?.role === 'unknown') && (
        <>
          <button type="button" className="ssMinor" data-part="reissue" onClick={() => void reissue()} disabled={busy}>
            換一條新的連結
          </button>
          <p className="ssNote">舊的連結就不能用了，已經進來的人不受影響。</p>
        </>
      )}

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
