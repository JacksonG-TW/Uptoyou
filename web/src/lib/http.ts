/**
 * The one HTTP mapper. Every fetch helper in `lib/` sends through `send` and judges the reply
 * through `must` (or reads `reply.action`), so what a status MEANS is decided in one place: the
 * table in `statuses.json`, which the backend generates from `upto/statuses.py` and a commit hook
 * keeps from drifting. No helper reads a raw status to guess a meaning (`spec-http-mapper-2026-10-10`).
 *
 * Matching, in order: the exact (method, router template, status) row; among rows that share all
 * three, the one whose `detail` equals the reply's, else a row with no detail (it stands for any
 * sentence); then the wildcard rows (`*`, `*`, status). A status the table does not list is
 * `retry_later`, and a unit test asserts the table leaves none unlisted for the routes the client
 * calls. Status 0 is the network.
 */

import table from './statuses.json'
import { forget } from './device'
import { detailOr } from './detail'

export type Action = 'success' | 'show_detail' | 'reread' | 'retry_later' | 'forget_seat' | 'void'

type Row = {
  method: string
  path: string
  status: number
  meaning: string
  detail: string | null
  client_action: string
}
const ROWS = table.statuses as Row[]

/** 「這台裝置在這個圈子的座位已經不能用了。」 — the one line every screen shows when the key no
 *  longer holds a seat, whatever English the API sent with the 401. */
export const SEAT_GONE = '這台裝置在這個圈子的座位已經不能用了。'

/* ---- URL -> router template ------------------------------------------------------------- */

const TEMPLATES: { template: string; re: RegExp }[] = [...new Set(
  ROWS.filter((r) => r.path !== '*').map((r) => r.path),
)].map((template) => ({
  template,
  re: new RegExp('^' + template.split('/').map((s) => (/^\{.+\}$/.test(s) ? '[^/]+' : s.replace(/[.*+?^$()|[\]\\]/g, '\\$&'))).join('/') + '$'),
}))

/** `/rounds/123/submit` -> `/rounds/{round_id}/submit`. Accepts the browser URL (`/api` prefix and
 *  query allowed). `null` when no route in the table has that shape. */
export function templateOf(url: string): string | null {
  const path = url.replace(/[?#].*$/, '').replace(/^\/api(?=\/)/, '')
  return TEMPLATES.find((t) => t.re.test(path))?.template ?? null
}

/* ---- the classifier ---------------------------------------------------------------------- */

export type Verdict = { action: Action; sentence: string }

export function classify(method: string, path: string, status: number, detail: unknown): Verdict {
  const template = templateOf(path)
  const m = method.toUpperCase()
  const text = typeof detail === 'string' && detail ? detail : ''
  const here = template === null ? [] : ROWS.filter((r) => r.method === m && r.path === template && r.status === status)
  const row = here.find((r) => r.detail !== null && r.detail === text)
    ?? here.find((r) => r.detail === null)
    ?? ROWS.find((r) => r.method === '*' && r.path === '*' && r.status === status)
  const action = (row?.client_action ?? 'retry_later') as Action
  switch (action) {
    case 'forget_seat': return { action, sentence: SEAT_GONE }
    // The API's own sentence (D112's member-readable copy); a list or an object is not a sentence.
    case 'show_detail':
    case 'void':
    case 'reread': return { action, sentence: text || (action === 'void' && row && row.detail ? row.detail : '') }
    default: return { action, sentence: '' }
  }
}

/* ---- sending ------------------------------------------------------------------------------ */

export type Reply = {
  method: string
  url: string
  status: number
  action: Action
  /** The API's sentence for show_detail / void / reread; `SEAT_GONE` for forget_seat; else ''. */
  sentence: string
  /** The reply's parsed JSON body, `{}` when it had none. Read for every non-success reply; for a
   *  success it is parsed on demand by `json()`. */
  body: { detail?: unknown } & Record<string, unknown>
  /** The raw response, for a stream. `null` on a network failure. */
  res: Response | null
  /** The device key this request carried (its `Authorization: Bearer`), or `null`. A refusal
   *  forgets this key only, never a newer one another tab stored meanwhile. */
  token: string | null
  json: <T = unknown>() => Promise<T>
}

type Init = {
  headers?: HeadersInit
  /** Sent as the JSON body, with the content type set. */
  json?: unknown
  cache?: RequestCache
  keepalive?: boolean
  signal?: AbortSignal
}

/** Send and classify. **Never throws** (a dropped network is status 0) and **applies no side
 *  effect**, so a call that must ignore its outcome (`leaveCircle`) can. `must` applies them. */
export async function send(method: string, url: string, init: Init = {}): Promise<Reply> {
  const headers = new Headers(init.headers)
  if (init.json !== undefined) headers.set('content-type', 'application/json')
  let res: Response | null = null
  try {
    res = await fetch(url, {
      method,
      headers,
      body: init.json === undefined ? undefined : JSON.stringify(init.json),
      cache: init.cache,
      keepalive: init.keepalive,
      signal: init.signal,
    })
  } catch {
    res = null
  }
  const status = res ? res.status : 0
  const ok = status >= 200 && status < 300
  let body: Reply['body'] = {}
  if (res && !ok) body = await res.json().catch(() => ({}))
  const { action, sentence } = classify(method, url, status, body?.detail)
  const bearer = headers.get('authorization')
  const token = bearer && /^Bearer /i.test(bearer) ? bearer.slice(7) : null
  const reply: Reply = {
    method, url, status, action, sentence, body, res, token,
    json: async <T>() => (res ? await res.json().catch(() => ({})) : {}) as T,
  }
  return reply
}

/* ---- the typed outcomes --------------------------------------------------------------------- */

export class HttpError extends Error {
  readonly action: Action
  readonly status: number
  constructor(message: string, action: Action, status: number) {
    super(message)
    this.action = action
    this.status = status
  }
}
/** The key holds no seat here. The device is already forgotten when this is thrown; the screen
 *  shows `SEAT_GONE` and goes home. */
export class SeatGone extends HttpError {
  constructor(status = 401) { super(SEAT_GONE, 'forget_seat', status) }
}
/** The round was voided (everyone it was waiting for left). The message is the API's sentence. */
export class RoundVoid extends HttpError {
  constructor(message: string, status = 410) { super(message, 'void', status) }
}
/** The state moved under the caller: fetch it again and render it, with no error line. */
export class Reread extends HttpError {
  constructor(message: string, status = 409) { super(message, 'reread', status) }
}

/** `forget_seat`'s side effect: drop `upto_token` and `upto_circle` (and the last-round pointer).
 *  Exported so the screens that learn it another way (the stream) apply the same act. */
export function forgetSeat(token?: string | null): void {
  forget(token)
}

/**
 * The reply if it succeeded, else the typed error for its action. `fallback` is the helper's own
 * generic words for a failure the API gave no sentence for (「讀取失敗」 family, with the status).
 * `keepSeat` is for a key that has not been remembered yet (the device screen's paste check),
 * where a 401 must not drop whatever key the device already holds.
 */
export function must(reply: Reply, fallback: string, opts: { keepSeat?: boolean } = {}): Reply {
  switch (reply.action) {
    case 'success': return reply
    case 'forget_seat':
      if (!opts.keepSeat) forgetSeat(reply.token)
      throw new SeatGone(reply.status)
    case 'void': throw new RoundVoid(reply.sentence, reply.status)
    case 'reread': throw new Reread(reply.sentence, reply.status)
    case 'show_detail':
      throw new HttpError(reply.sentence || detailOr(reply.body, fallback, reply.status), 'show_detail', reply.status)
    default:
      throw new HttpError(reply.status === 0 ? fallback : `${fallback}（${reply.status}）`, 'retry_later', reply.status)
  }
}
