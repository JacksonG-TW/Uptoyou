import { useCallback, useState } from 'react'
import InvitePanel from './InvitePanel'
import type { Device } from '@/lib/device'
import type { InviteRole, Members } from '@/lib/selfserve'

/**
 * `/circle` — the durable home of the package's step 3, for a member who holds a key.
 *
 * **`SS-13`: without this, step 3 lived only in the create flow's memory.** `/create` showed step 1
 * again and nothing reached the invite link or the re-issue control. **The ruled hour is what made
 * that a defect rather than a rough edge** — the ticket dies in an hour, the remedy is re-issue,
 * and re-issue could only be found in the minutes right after creation, so a link expiring meant
 * *and you cannot make another one*.
 *
 * **A route with nothing in the URL.** The circle and the credential come from `localStorage` via
 * `device()`, exactly as `/round` and `/reveal` already take them — no id in the path, no ticket in
 * a query. The spec's rule holds without this screen doing anything special: **the only secrets on
 * this surface travel in a fragment, and this screen has no fragment.**
 *
 * **A visit without a key falls through to the home**, like `/reveal?round=abc` and a `/join` whose
 * fragment did not parse. It is not an error worth a screen: somebody who has no key has nothing to
 * invite anyone to, and `home()` already rewrites the bar so the address stops describing a screen
 * nobody is on.
 *
 * **This screen never renders the key.** It holds the credential only to read the seat list and to
 * re-issue; `SS-2`'s 「the invite screen carries no key」 is structural here, because there is no
 * code path that puts `device.token` on the page.
 */
export default function Circle({ device }: { device: Device }) {
  /**
   * **Empty on arrival, and PERMANENTLY so — this is not a hole waiting for an endpoint.**
   *
   * `join_ticket` stores `token_sha256` and nothing else: **the server has never held the plaintext
   * after the response that printed it**, exactly as with a device key. So no endpoint can return a
   * link, and the one I asked backend for would have required storing the plaintext — trading away
   * the property that makes a database read, or the nightly dump in the bucket, useless to whoever
   * gets one. `GET …/join-ticket` exists now and answers **`{active, expired, expires_at}`** — the
   * status of the link, never the link.
   *
   * The hazard that started this is real and is why nothing is fetched on arrival: the only route
   * that yields a link is `POST …/join-ticket`, which **mints one and revokes the current one**, so
   * a screen that fetched a link on arrival would destroy the link the creator had already shared
   * **by the act of opening the screen to look at it** — §5's 「a worried person presses the
   * frightening button and their friend's link dies with it」, with nobody pressing anything.
   *
   * **So the only thing that fills this is re-issue**, and that is honest rather than a shortfall:
   * a creator on this screen is here because they no longer have the link, and the button really
   * does hand them one that works. The status read tells them whether the one they sent is still
   * alive — which is the question they actually arrived with.
   */
  const [link, setLink] = useState('')
  /** `null` until the role read answers; then the role and the seat list (null while it loads). */
  const [known, setKnown] = useState<{ role: InviteRole['role']; seats: Members | null } | null>(null)
  /** The key holds no seat here: the panel shows the shared sentence, and the title steps aside. */
  const [gone, setGone] = useState(false)
  const onGone = useCallback(() => setGone(true), [])
  const onRole = useCallback((role: InviteRole['role'], seats: Members | null) => setKnown({ role, seats }), [])

  return (
    <main className="selfserve" data-screen="circle">
      {/* No 「★ 這個圈子」 eyebrow (`spec-round-diet-circle-2026-10-08.md` B): the title already says
          where you are, and the eyebrow was one more piece of text in a first view that is budgeted. */}
      {/* **The title follows what this seat can do here** (the evaluator's red, 2026-10-08: a member
          read 「邀朋友加入」 over a page whose only act was 選這一餐 — 「標題和按鈕的用途對不起來」).
          The creator gets the invite page; a member gets their circle, by its name, in the sans
          because it is somebody's typing. **Until the role read answers the title is empty** (the
          reviewer, 37b16e0): showing 邀朋友加入 first and then the circle's name was the same
          mismatch, briefer, and a heading that changes under a screen reader. */}
      {gone ? null : known === null ? (
        <h1 className="ssTitle" aria-busy="true">{'\u00a0'}</h1>
      ) : known.role === 'member' ? (
        <h1 className="ssInvite" data-part="circle-title">
          <span data-user-content>{known.seats?.name ?? '你的圈子'}</span>
        </h1>
      ) : (
        <h1 className="ssTitle dSerif"><span>邀朋友加入</span></h1>
      )}
      <InvitePanel device={device} link={link} onLink={setLink} onRole={onRole} onGone={onGone} />
    </main>
  )
}
