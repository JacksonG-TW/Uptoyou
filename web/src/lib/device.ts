/**
 * The device's own credential, and the one reader for a secret that arrives in a link's fragment.
 *
 * **One copy of each, on purpose** (reviewer baseline 2026-10-07, finding 7). The credential was
 * read in three files and the fragment in two; a second hand-rolled drop is exactly where somebody
 * eventually forgets the `replaceState`, and that drop is the secret's privacy.
 */

/** D74's secret and the circle it opens. Both halves or neither — a token with no circle
 *  addresses no endpoint. */
export type Device = { token: string; circle: string }

export function device(): Device | null {
  const token = localStorage.getItem('upto_token')
  const circle = localStorage.getItem('upto_circle')
  return token && circle ? { token, circle } : null
}

/** One key, one circle: writing a second circle replaces the first (owner ruling (b), cc04fab;
 *  `spec-one-circle-per-device-2026-10-07.md`). The old seat is given back by `leaveCircle`. */
export function remember(d: Device): void {
  // A different circle's last round is not this circle's 上一餐, and the new key cannot read it.
  if (localStorage.getItem('upto_circle') !== d.circle) localStorage.removeItem('upto_last_round')
  localStorage.setItem('upto_token', d.token)
  localStorage.setItem('upto_circle', d.circle)
}

/**
 * The round the bar's 上一餐結果 points at. **Only ever moves forward**: round ids grow, so a
 * smaller id is an older meal — a reveal opened from an old chat link must not pull the label back
 * to it (the reviewer, fd14276). Written by 這一餐 from the snapshot and by every reveal opened.
 */
/** **Forget this device's circle**: its seat is gone (the host asked it to leave, or the server no
 *  longer accepts the key). Without this the home kept opening a circle the seat was no longer in
 *  (the reviewer's should on 4a54d82). */
export function forget(): void {
  localStorage.removeItem('upto_token')
  localStorage.removeItem('upto_circle')
  localStorage.removeItem('upto_last_round')
}

export function noteLastRound(id: number): void {
  try {
    const held = Number(localStorage.getItem('upto_last_round'))
    if (!Number.isFinite(held) || id > held) localStorage.setItem('upto_last_round', String(id))
  } catch { /* storage off: the bar simply has no 上一餐結果 */ }
}

export function auth(d: Device): HeadersInit {
  return { authorization: `Bearer ${d.token}` }
}

/**
 * Read `#c=<circle>&<key>=<secret>` once and **drop the fragment from the address bar before the
 * caller does anything else.** The invite link carries `k` (a device key, D74); the join link
 * carries `t` (a ticket, A20). A fragment reaches no proxy log, no `Referer` and not the API, which
 * is the whole reason a secret can travel in a URL — moving it to the query would undo that
 * silently.
 *
 * 1. **`URLSearchParams` on the hash minus its `#`, never a hand-rolled split** — percent-encoding,
 *    empty values and repeated keys are what a split gets wrong.
 * 2. **`replaceState`, not `pushState`**: the link's own history entry is the one to overwrite, or
 *    a back arrow walks onto the secret again. Path and query are kept as they are.
 * 3. **Dropped whenever there is a fragment, even half a link or junk**, so a malformed link cannot
 *    leave half a secret in the bar for a screenshot. Calling it a second time (StrictMode) finds
 *    nothing and returns `null`.
 * 4. **Anything that is not both halves is an ordinary visit**, never an error: a hostile or
 *    undecodable fragment must not take the screen down (A20).
 */
export function readFragmentSecret(key: 'k' | 't'): { circle: string; secret: string } | null {
  let circle = ''
  let secret = ''
  try {
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    circle = (fragment.get('c') ?? '').trim()
    secret = (fragment.get(key) ?? '').trim()
  } catch {
    circle = ''
    secret = ''
  }
  if (window.location.hash) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return circle && secret ? { circle, secret } : null
}
