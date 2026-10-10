import { auth, type Device } from './device'
import { must, send } from './http'

/**
 * A24 — self-serve circles: the data layer `Create`, `Join` and `InvitePanel` are built on.
 *
 * The structure was ruled at the self-serve sitting (decision-log «Self-serve sitting ①» and
 * «② and ③», owner 「1」「1」) and the endpoint shapes are fixed in
 * `doc/issues/A24-self-serve-circles.md` (`4970884`). Presentation — layout, component shape, copy
 * tone — is the evaluator's axis and is not decided here.
 *
 * **All three calls return a secret the server prints once and stores only the hash of.** Nothing
 * in this file logs one, returns one twice, or puts one anywhere but `localStorage` through
 * `remember`.
 */

/** What `POST /circles` hands back. `key` is the creator's device secret: stored through
 *  `remember` and never rendered — no member screen shows a key since the owner's 2026-09-16
 *  ruling. */
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
 * **The refusal's words come from the API, and that is a rule rather than laziness here** (the
 * table's `show_detail`; `lib/http.ts` decides, `must` raises it).
 *
 * `round.ts`'s `verify` and `preferences.ts`'s `said` answer **401 and 404 in the surface's own
 * words** because those are about the credential the person just pasted, and keep the API's
 * sentence for everything else. A24's refusals — 409 the circle is full, 410 the ticket is no
 * longer usable, 429 the daily ceiling — are not about a credential at all: they are states of the
 * circle and the ticket, so they keep the server's sentence.
 *
 * **410 has TWO reasons since the owner ruled expiry on 2026-09-13** (「最多 1 小時就過期」): the
 * ticket was re-issued, or it is simply older than an hour. **Rendering `detail` is what makes that
 * cost nothing here** — the two cases are different sentences from the server and the same code
 * path in this file. A client that had mapped 410 to its own 「這個連結換過了」 would now be
 * telling a person their link was replaced when it had merely gone stale, which is a wrong
 * explanation of a correct refusal.
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

/** Ruling ②: a stranger creates a circle and gets one link to paste into the group chat. 429 is
 *  the proxy's daily ceiling on **creation** — never on joining, because five friends at one table
 *  share one address and a per-IP join cap would refuse the fourth friend at dinner. */
export async function createCircle(name: string, nickname: string): Promise<Created> {
  const r = must(await send('POST', '/api/circles', {
    /* **Both fields are required**, and the second one is here because the endpoint was driven
       rather than read. A24 documented `{name}` alone until 2026-09-13; the live endpoint answered
       422 `{"loc": ["body","nickname"], "msg": "Field required"}`, so a client built from the page
       would have failed at runtime. The code was right and its description was not — the creator
       gets a seat and a seat has a nickname. **The ticket now says `{name, nickname}`** (backend,
       `96873f8`), so this note records why the field is trusted, not a discrepancy to go looking
       for: there is none left. */
    json: { name, nickname },
  }), '開不了圈子')
  const body = await r.json<{ circle_id: unknown; member_id: number; key: string; join_link: string }>()
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
  const r = must(await send('POST', `/api/circles/${encodeURIComponent(circleId)}/join`, {
    json: { ticket, nickname },
  }), '進不去')
  const body = await r.json<{ member_id: number; key: string }>()
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
  const r = must(await send('POST', `/api/circles/${encodeURIComponent(d.circle)}/join-ticket`, {
    headers: auth(d),
  }), '換不了連結')
  return (await r.json<{ join_link: string }>()).join_link
}

/**
 * **Whose seat is this, and — for the creator — is the link they sent still alive.** One read,
 * `GET /circles/{id}/join-ticket` (`59f55c6`), which **mints nothing and revokes nothing**, so
 * asking costs the shared link nothing.
 *
 * Evaluator-ruled 2026-09-13 (Addendum 4): `200` → the creator's re-issue control; `403` → the
 * member line; **anything else, or no answer, → the control as today**, because the server's own
 * 403 on `POST` stays the backstop. The fallback leans toward showing the control on purpose: a
 * creator who cannot find re-issue has a link that dies in an hour and no way to make another, and
 * a member who sees the control in that rare case is refused in words, which is today's behaviour.
 *
 * **The `200` body is the link's status, and the owner ruled it shown** (「顯示」, 2026-09-13): the
 * creator's `/circle` states whether the link they sent is live and until when. Same read, no
 * second request. **`status` is present only on `creator`** — a member's `403` carries no status,
 * and its `detail` is deliberately not rendered: the member line says the same thing before
 * anything is pressed.
 *
 * **Three states, not two, and backend kept them apart on purpose** (`circles.py`): no live ticket
 * (`active` and `expired` both false, `expires_at` null) is not the same as a ticket that ran out.
 */
export type LinkStatus = { active: boolean; expired: boolean; expiresAt: Date | null }

export type InviteRole =
  | { role: 'creator'; status: LinkStatus | null }
  | { role: 'member' }
  | { role: 'unknown' }

export async function readInviteRole(d: Device): Promise<InviteRole> {
  const r = await send('GET', `/api/circles/${encodeURIComponent(d.circle)}/join-ticket`, {
    headers: auth(d),
    cache: 'no-store',
  })
  // The seat is gone: forget it and let the screen say so (`SeatGone`), never `unknown`.
  if (r.action === 'forget_seat') must(r, '')
  // The table's one refusal on this read is the member's 403 (`show_detail`).
  if (r.action === 'show_detail') return { role: 'member' }
  if (r.action !== 'success') return { role: 'unknown' }
  /* **A 200 whose body will not parse is still the creator.** The role is the table's answer;
     the status line is extra, so a malformed body loses the line and keeps the control. */
  const body = await r.json<{ active?: boolean; expired?: boolean; expires_at?: string | null } | null>()
  if (!body || Object.keys(body).length === 0) return { role: 'creator', status: null }
  const at = body.expires_at ? new Date(body.expires_at) : null
  return {
    role: 'creator',
    status: {
      active: !!body.active,
      expired: !!body.expired,
      expiresAt: at && !Number.isNaN(at.getTime()) ? at : null,
    },
  }
}

/**
 * §2c's seat list — `GET /circles/{id}/members` → `{members: [{nickname}], seats, cap}`.
 *
 * Built by backend on 2026-09-13 after I raised that the spec asked for a seat list no endpoint
 * could supply. Three things about its shape are decisions rather than conveniences:
 *
 * - **`{nickname}` and nothing else.** No `member_id` — §3.0 and H3: an identifier a screen never
 *   needs is a correlation somebody else might. The same shape `rolls[]` already sets.
 * - **Any member of the circle may read it, not the operator alone**, because everyone at the table
 *   can see who is at the table. It still takes a credential: a circle's membership is not public
 *   and a bare id must not enumerate one.
 * - **Duplicates come back exactly as the server holds them** and **the order is join order**, so
 *   the creator is first and the list is stable across a re-issue — which is what `SS-7` compares
 *   against and what makes `SS-8` measurable at all.
 *
 * **`cap` is read from the payload and never written in the markup.** It is `issue.SEAT_CAP`, it
 * has moved once already, and a client that hard-codes ten is a client that will one day disagree
 * with the server about D110.
 */
export type Members = {
  /** `is_host` per row (backend, 2026-10-09): which seat carries the 房主 tag. Never an id. */
  name: string | null; members: { nickname: string; isHost: boolean }[]; seats: number; cap: number
  /** The seat that opened the circle, by nickname — the same `creator_nickname` /join/preview
   *  returns (agreed with backend 2026-10-08). `null` when that seat has left, for a CLI circle,
   *  or from an API that does not send it yet. */
  creatorNickname: string | null
  /** The reader's own seat, by nickname (`your_nickname`, backend 6c6cb2f): so 「開這個圈子的是 小明」
   *  no longer leaves a reader asking 「我是不是小明？」 (the evaluator, 2026-10-08). */
  yourNickname: string | null
  /** Whether the reader is the host (`you_are_host`): the invite link follows the host. */
  youAreHost: boolean
}

export async function fetchMembers(d: Device): Promise<Members> {
  const r = must(await send('GET', `/api/circles/${encodeURIComponent(d.circle)}/members`, {
    headers: auth(d),
    cache: 'no-store',
  }), '看不到座位')
  const body = await r.json<Record<string, unknown>>()
  // `name` is the circle's own name, asked of backend on 2026-10-08 for the member's home (the
  // evaluator's item-1 red: the home never said which circle you are in). Absent until that lands,
  // and the home then says 這個圈子 with the nicknames alone.
  return {
    name: typeof body.name === 'string' && body.name ? body.name : null,
    members: ((body.members ?? []) as { nickname: string; is_host?: boolean }[])
      .map((m) => ({ nickname: m.nickname, isHost: m.is_host === true })),
    seats: body.seats as number, cap: body.cap as number,
    creatorNickname: typeof body.creator_nickname === 'string' && body.creator_nickname ? body.creator_nickname : null,
    yourNickname: typeof body.your_nickname === 'string' && body.your_nickname ? body.your_nickname : null,
    youAreHost: body.you_are_host === true,
  }
}

/** **The host asks a seat that won't come back to leave** (owner, 2026-10-09). The effect is that
 *  seat leaving: the round stops waiting for it and may close on the spot. Refused for anyone but
 *  the host, for the host's own seat, and for a seat that has already submitted; the sentences are
 *  the API's. */
export async function removeSeat(d: Device, memberId: number): Promise<void> {
  must(await send('DELETE', `/api/circles/${encodeURIComponent(d.circle)}/members/${memberId}`, {
    headers: auth(d),
  }), '請不走')
}

/**
 * What `/join` may say before anyone types — `POST /circles/{id}/join/preview` (backend 9e7d48e),
 * on frontend's terms (`doc/decision-log.md`, 2026-10-07 «/join names the circle»).
 *
 * **The ticket travels in the body, never the URL**, and the call carries no credential: a joiner
 * has none yet. Three outcomes and no more:
 * - `live` — the circle's name and its creator's nickname (`null` when that seat is gone);
 * - `dead` — every dead case answers one byte-identical 404, so the screen cannot tell expired
 *   from replaced from mistyped and does not try: it shows the server's one sentence;
 * - `unknown` — the read itself failed (network, 5xx). The screen then behaves as it did before
 *   the preview existed — the form, and join's own answer — rather than calling a link dead that
 *   may be fine.
 */
export type JoinPreview =
  | { kind: 'live'; circleName: string; creator: string | null }
  | { kind: 'dead'; message: string }
  | { kind: 'unknown' }

export async function previewJoin(circleId: string, ticket: string): Promise<JoinPreview> {
  const r = await send('POST', `/api/circles/${encodeURIComponent(circleId)}/join/preview`, {
    json: { ticket },
    cache: 'no-store',
  })
  if (r.action === 'success') {
    const body = await r.json<{ circle_name?: unknown; creator_nickname?: string | null }>()
    if (typeof body.circle_name === 'string') {
      return { kind: 'live', circleName: body.circle_name, creator: body.creator_nickname ?? null }
    }
    return { kind: 'unknown' }
  }
  // **An api without the preview answers its framework's own 404, `{"detail": "Not Found"}`**
  // (FastAPI's unknown route), and that must not read as a dead link: every invite would open
  // dead and nobody could join (the reviewer's catch, 2026-10-08 — production's candidate 24
  // has no preview). The table's dead-link row is matched by its exact sentence, so the framework's
  // 404 falls through to `retry_later`, which is `unknown`: the old form keeps working.
  if (r.action === 'show_detail' && r.sentence) return { kind: 'dead', message: r.sentence }
  return { kind: 'unknown' }
}

/**
 * Give back the seat this device is leaving — `POST /circles/{id}/leave` (backend 81f1c63), on
 * the shape agreed 2026-10-08: the OLD key as bearer, no body, 204 in every case. The seat stops
 * counting toward the cap and leaves the member list; the old key stops working in that circle
 * only (a principal seated elsewhere keeps those seats). Nothing is deleted.
 *
 * **Called only after the new seat exists and is remembered**, so a failed join never costs the
 * old seat. **`keepalive`**, because `/join` navigates away the moment it has its key and a plain
 * fetch would be cancelled with the page. Every outcome is ignored: a failure, or an api without
 * the route (production before 81f1c63), leaves the old seat exactly as it was before this
 * existed — the one-circle notice's claim degrades to 「留在原圈子」, which was true until now.
 */
export function leaveCircle(old: Device): void {
  // `send` never throws and applies no side effect: a 401 here must not forget the NEW seat that
  // was just remembered.
  void send('POST', `/api/circles/${encodeURIComponent(old.circle)}/leave`, {
    headers: auth(old),
    keepalive: true,
  })
}
