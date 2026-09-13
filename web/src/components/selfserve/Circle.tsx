import { useState } from 'react'
import InvitePanel from './InvitePanel'
import type { Device } from '@/lib/round'

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
   * **Empty until backend can answer 「what is the current link?」.**
   *
   * The only route that yields a join link is `POST …/join-ticket`, which **mints one and revokes
   * the current one** — so fetching a link on arrival would destroy the link the creator had
   * already shared, by the act of opening the screen to look at it. That is §5's 「a worried person
   * presses the frightening button and their friend's link dies with it」, reached with nobody
   * pressing anything.
   *
   * So this screen starts with no link and the panel shows none. **Pressing re-issue is what fills
   * it**, which is honest: that button really does hand you a link that works. When
   * `GET …/join-ticket` lands it is read here and passed down, and nothing else changes.
   */
  const [link, setLink] = useState('')

  return (
    <main className="selfserve" data-screen="circle">
      <p className="eyebrow"><em>★</em>這個圈子</p>
      <h1 className="ssTitle"><span>找人進來</span></h1>
      <InvitePanel device={device} link={link} onLink={setLink} />
    </main>
  )
}
