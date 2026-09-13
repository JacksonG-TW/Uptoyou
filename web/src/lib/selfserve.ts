import type { Device } from './round'

/**
 * A24 — self-serve circles. **The data layer only**; no screen is built against it yet.
 *
 * The structure was ruled at the self-serve sitting (decision-log «Self-serve sitting ①» and
 * «② and ③», owner 「1」「1」) and the endpoint shapes are fixed in
 * `doc/issues/A24-self-serve-circles.md` (`4970884`). Presentation — layout, component shape, copy
 * tone, where the key's copy control sits — is the evaluator's axis and is not decided here.
 *
 * **All three calls return a secret the server prints once and stores only the hash of.** Nothing
 * in this file logs one, returns one twice, or puts one anywhere but `localStorage` through
 * `remember`.
 */

/** What `POST /circles` hands back. `key` is the creator's device secret, shown once (ruling ①:
 *  a copy control and one line of notice, **no forced block** — the forced copy-before-continue
 *  was explicitly rejected, so nothing here should grow one). */
export type Created = {
  circleId: string
  memberId: number
  key: string
  joinLink: string
}

/** What `POST /circles/{id}/join` hands back — a seat and its own device secret, same once-only
 *  rule as the creator's. */
export type Joined = {
  memberId: number
  key: string
}

/**
 * **The refusal's words come from the API, and that is a rule rather than laziness here.**
 *
 * `round.ts`'s `verify` and `preferences.ts`'s `said` answer **401 and 404 in the surface's own
 * words** because those are about the credential the person just pasted, and keep the API's
 * sentence for everything else. A24's refusals — 409 the circle is full, 410 the ticket was
 * replaced, 429 the daily ceiling — are not about a credential at all: they are states of the
 * circle and the ticket, so they keep the server's sentence.
 *
 * **And backend owns those sentences deliberately: they live in `tools/server_copy.py`.** The font
 * gate derives its charset from that file, so a sentence invented in a client module can ship as
 * blank gaps on a machine with no CJK fallback — 或 and 趟 did exactly that once, past a green
 * gate. If a screen needs a sentence backend has not written, it goes to them, not into this file.
 *
 * The fallback is deliberately bare and carries the status: it is what renders only if the API
 * sent no `detail` at all, which is a defect rather than a state, and a status code is the thing
 * that makes such a report actionable.
 */
async function refusal(r: Response, fallback: string): Promise<Error> {
  const body = await r.json().catch(() => ({}))
  return new Error((body as { detail?: string }).detail || `${fallback}（${r.status}）`)
}

/** Ruling ②: a stranger creates a circle and gets one link to paste into the group chat. 429 is
 *  the proxy's daily ceiling on **creation** — never on joining, because five friends at one table
 *  share one address and a per-IP join cap would refuse the fourth friend at dinner. */
export async function createCircle(name: string): Promise<Created> {
  const r = await fetch('/api/circles', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  if (r.status !== 201) throw await refusal(r, '開不了圈子')
  const body = await r.json()
  return {
    circleId: String(body.circle_id),
    memberId: body.member_id,
    key: body.key,
    joinLink: body.join_link,
  }
}

/** Ruling ②: whoever taps the shared link grows their own seat and types their own nickname.
 *
 *  **No uniqueness check, here or anywhere.** Two friends both typing 小明 is legal and the server
 *  allows it; refusing a name because someone else took it is the administration the owner
 *  rejected. If it ever reads badly the fix is in the display, not a refusal. */
export async function joinCircle(
  circleId: string, ticket: string, nickname: string,
): Promise<Joined> {
  const r = await fetch(`/api/circles/${encodeURIComponent(circleId)}/join`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ ticket, nickname }),
  })
  if (r.status !== 201) throw await refusal(r, '進不去')
  const body = await r.json()
  return { memberId: body.member_id, key: body.key }
}

/**
 * **One button, not two, and the naming is the ruling.** There is no standalone revoke: revoking
 * alone leaves a circle nobody can join, and that is a state a worried person reaches by accident
 * — they press the scary button to shut a stranger out and their real friend's link dies with it.
 * The operation is «get a new link; the old one stops working», so whatever they press always
 * leaves them something to share. **Copy must be worded that way rather than as a revocation.**
 *
 * **It ejects nobody.** Re-issuing stops a stranger inviting others; it does not remove one who
 * has already joined. Eject is its own sitting. A screen implying otherwise gets pressed for the
 * wrong reason, which is worse than the button not existing.
 */
export async function reissueJoinLink(d: Device): Promise<string> {
  const r = await fetch(`/api/circles/${encodeURIComponent(d.circle)}/join-ticket`, {
    method: 'POST',
    headers: { authorization: `Bearer ${d.token}` },
  })
  if (r.status !== 201) throw await refusal(r, '換不了連結')
  const body = await r.json()
  return body.join_link
}

/**
 * The join link's fragment — `<origin>/join#c=<circle_id>&t=<ticket>` — read once and **dropped
 * from the address bar before anything else happens.**
 *
 * **A20, and the fragment is the entire reason the ticket can travel in a URL at all**: a fragment
 * reaches no proxy log, no `Referer` and not this API, which is what keeps «printed once, stored
 * nowhere» true. Moving `t` to the query would undo that silently and everything else would keep
 * working.
 *
 * Three things copied deliberately from `Device.tsx`'s invite reader, because each is a case a
 * simpler version gets wrong on the one input that matters:
 *
 * 1. **`URLSearchParams` on the hash minus its `#`, never a hand-rolled split** — percent-encoding,
 *    empty values and repeated keys are exactly what a split gets wrong.
 * 2. **The fragment is dropped with `replaceState`, not `pushState`.** The link's own history entry
 *    is the one that has to be overwritten: a back arrow onto a URL still carrying the ticket would
 *    put the secret back in the address bar after it had been taken out. Path and query are kept
 *    exactly as they are; only the fragment goes.
 * 3. **A fragment that is not both `c` and `t` is an ordinary visit, not an error**, and a hostile
 *    or undecodable one must not take the screen down — a blank screen is the one outcome A20 names
 *    as unacceptable. Both return `null` and the caller shows whatever an uninvited visit shows.
 *
 * **The drop happens even when only one half parsed**, so a malformed link cannot leave half a
 * secret sitting in the address bar for a screenshot to catch.
 *
 * `Device.tsx` carries its own copy of this for `#c=&k=`. They are not shared yet: consolidating
 * them means editing a live, gated screen, which is not this commit's scope — but a second
 * hand-rolled drop is exactly where somebody eventually forgets the `replaceState`, so it is
 * flagged rather than left to be discovered.
 */
export function readJoinFragment(): { circle: string; ticket: string } | null {
  let circle = ''
  let ticket = ''
  try {
    const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''))
    circle = (fragment.get('c') ?? '').trim()
    ticket = (fragment.get('t') ?? '').trim()
  } catch {
    circle = ''
    ticket = ''
  }
  if (window.location.hash) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
  }
  return circle && ticket ? { circle, ticket } : null
}
