import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import table from './statuses.json'
import {
  classify, must, send, templateOf, HttpError, Reread, RoundVoid, SeatGone, SEAT_GONE,
} from './http'

type Row = { method: string; path: string; status: number; detail: string | null; client_action: string }
const ROWS = table.statuses as Row[]

/** A fake `localStorage` (the unit tests run without a DOM). */
function fakeStorage(seed: Record<string, string> = {}) {
  const m = new Map(Object.entries(seed))
  return {
    getItem: (k: string) => m.get(k) ?? null,
    setItem: (k: string, v: string) => void m.set(k, v),
    removeItem: (k: string) => void m.delete(k),
    keys: () => [...m.keys()],
  }
}

/** The fetch stub: answers once with this status and JSON body (`null` status = the network drops). */
function reply(status: number | null, body: unknown = {}) {
  const f = vi.fn(async () => {
    if (status === null) throw new TypeError('Failed to fetch')
    return new Response(status === 204 ? null : JSON.stringify(body), { status })
  })
  vi.stubGlobal('fetch', f)
  return f
}

let store: ReturnType<typeof fakeStorage>
beforeEach(() => {
  store = fakeStorage({ upto_token: 'fake-token', upto_circle: '7', upto_last_round: '3' })
  vi.stubGlobal('localStorage', store)
})
afterEach(() => { vi.unstubAllGlobals() })

/** A concrete URL for a router template. */
const concrete = (template: string) => template.replace(/\{[^}]+\}/g, '42')

describe('the URL matcher — a concrete URL becomes its router template', () => {
  it('maps ids to the template, and drops /api and the query', () => {
    expect(templateOf('/api/rounds/123/submit')).toBe('/rounds/{round_id}/submit')
    expect(templateOf('/rounds/9/result')).toBe('/rounds/{round_id}/result')
    expect(templateOf('/api/circles/abc/places?q=%E7%89%9B')).toBe('/circles/{circle_id}/places')
    expect(templateOf('/api/circles/5/members/8')).toBe('/circles/{circle_id}/members/{member_id}')
  })
  it('keeps neighbours apart: join, join/preview and join-ticket(/check)', () => {
    expect(templateOf('/api/circles/5/join')).toBe('/circles/{circle_id}/join')
    expect(templateOf('/api/circles/5/join/preview')).toBe('/circles/{circle_id}/join/preview')
    expect(templateOf('/api/circles/5/join-ticket')).toBe('/circles/{circle_id}/join-ticket')
    expect(templateOf('/api/circles/5/join-ticket/check')).toBe('/circles/{circle_id}/join-ticket/check')
    expect(templateOf('/api/circles')).toBe('/circles')
    expect(templateOf('/api/places/count')).toBe('/places/count')
  })
  it('answers null for a path the table does not know', () => {
    expect(templateOf('/api/nothing/here')).toBeNull()
    expect(templateOf('/api/rounds/1/submit/extra')).toBeNull()
  })
})

describe('classify — the table decides', () => {
  it('every row of the table classifies to its own action, by method, URL, status and detail', () => {
    for (const r of ROWS) {
      if (r.method === '*') continue
      const got = classify(r.method, `/api${concrete(r.path)}`, r.status, r.detail)
      expect(got.action, `${r.method} ${r.path} ${r.status} ${r.detail}`).toBe(r.client_action)
    }
  })
  it('the wildcard rows answer for any route, and status 0 is the network', () => {
    expect(classify('GET', '/api/nothing/here', 503, null).action).toBe('retry_later')
    expect(classify('GET', '/api/rounds/1/result', 504, null).action).toBe('retry_later')
    expect(classify('POST', '/api/circles/1/places', 0, null).action).toBe('retry_later')
    expect(classify('POST', '/api/circles/1/preferences', 422, [{ loc: ['body'] }]).action).toBe('show_detail')
    // The API's own 429 sentence is shown; a bare 429 (the proxy's, no sentence) is the wildcard.
    expect(classify('POST', '/api/circles', 429, '你今天開的圈子夠多了，明天再來。').action).toBe('show_detail')
    expect(classify('POST', '/api/circles', 429, null).action).toBe('retry_later')
    expect(classify('GET', '/api/rounds/1/result', 429, null).action).toBe('retry_later')
  })
  it('an unlisted status is retry_later', () => {
    expect(classify('GET', '/api/rounds/1/result', 418, null).action).toBe('retry_later')
    expect(classify('GET', '/api/rounds/1/result', 403, 'x').action).toBe('retry_later')
  })
  it('rows that share method, path and status are told apart by detail', () => {
    const room = '/api/circles/1/members/2'
    expect(classify('DELETE', room, 409, '房主不能請自己離開。要離開，請用離開圈子。').action).toBe('show_detail')
    expect(classify('DELETE', room, 409, '這個人已經提交了，不能請對方離開。').action).toBe('reread')
    expect(classify('POST', '/api/circles/1/join', 410, '這個連結換過了，跟開圈子的人要新的。').action).toBe('show_detail')
  })
  it('a row with no detail stands for any sentence (a D68 object, the circle-full line)', () => {
    expect(classify('POST', '/api/circles/1/rounds', 409, { open_round: { round_id: 4 } }).action).toBe('reread')
    expect(classify('POST', '/api/circles/1/join', 409, '這個圈子滿了，最多10個人。').action).toBe('show_detail')
  })
  it('the framework\'s own «Not Found» is not the dead-link sentence', () => {
    expect(classify('POST', '/api/circles/1/join/preview', 404, 'Not Found').action).toBe('retry_later')
  })
  it('the trip: «already signed» 409 is reread, a void round 410 is void', () => {
    expect(classify('POST', '/api/rounds/5/trip', 409, '小明已經在 12:03 記下這一趟了。').action).toBe('reread')
    expect(classify('POST', '/api/rounds/5/trip', 409, '這一輪還沒擲出結果。').action).toBe('reread')
    const v = classify('POST', '/api/rounds/5/trip', 410, '這一輪作廢了：開始時在場的人都離開了。開新的一輪吧。')
    expect(v.action).toBe('void')
    expect(v.sentence).toBe('這一輪作廢了：開始時在場的人都離開了。開新的一輪吧。')
  })
  it('forget_seat carries the shared sentence, never the API\'s English', () => {
    const v = classify('POST', '/api/rounds/5/submit', 401, 'the token does not resolve to a member of this circle')
    expect(v).toEqual({ action: 'forget_seat', sentence: SEAT_GONE })
    expect(SEAT_GONE).toBe('這台裝置在這個圈子的座位已經不能用了。')
  })
})

describe('every route the client calls is in the table', () => {
  // The calls the files in lib/ make, as (method, router template).
  const CALLED: [string, string][] = [
    ['GET', '/circles/{circle_id}/preferences'], ['POST', '/circles/{circle_id}/preferences'],
    ['GET', '/circles/{circle_id}/places'], ['POST', '/circles/{circle_id}/places'],
    ['POST', '/circles/{circle_id}/rounds'], ['POST', '/rounds/{round_id}/proposals'],
    ['POST', '/rounds/{round_id}/submit'], ['DELETE', '/rounds/{round_id}/submit'],
    ['GET', '/circles/{circle_id}/stream'], ['GET', '/rounds/{round_id}/result'],
    ['POST', '/rounds/{round_id}/trip'], ['GET', '/weather'], ['GET', '/places/count'],
    ['POST', '/circles'], ['POST', '/circles/{circle_id}/join'],
    ['POST', '/circles/{circle_id}/join/preview'], ['POST', '/circles/{circle_id}/join-ticket'],
    ['GET', '/circles/{circle_id}/join-ticket'], ['GET', '/circles/{circle_id}/members'],
    ['DELETE', '/circles/{circle_id}/members/{member_id}'], ['POST', '/circles/{circle_id}/leave'],
  ]
  it('each has a success row, and no status the table lists for it falls through to a guess', () => {
    for (const [method, path] of CALLED) {
      const rows = ROWS.filter((r) => r.method === method && r.path === path)
      expect(rows.some((r) => r.client_action === 'success'), `${method} ${path} has no success row`).toBe(true)
      for (const r of rows) {
        expect(classify(method, `/api${concrete(path)}`, r.status, r.detail).action).toBe(r.client_action)
      }
    }
  })
  it('no helper in lib/ reaches fetch except through http.ts, and none reads a status to guess', () => {
    const files = import.meta.glob('./*.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
    for (const [name, src] of Object.entries(files)) {
      if (name.endsWith('.test.ts') || name === './http.ts') continue
      const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      expect(code, `${name} calls fetch directly`).not.toMatch(/\bfetch\(/)
      expect(code, `${name} reads a raw status`).not.toMatch(/\.status\s*(?:[=!]==?|[<>]=?)|\.ok\b|\.status\s*\)\s*(?:\?|\|\|)/)
    }
  })
})

describe('one test per action — send + must', () => {
  it('success: returns the reply and its body', async () => {
    reply(200, { hello: 'x' })
    const r = must(await send('GET', '/api/places/count'), '讀取失敗')
    expect(r.action).toBe('success')
    expect(await r.json()).toEqual({ hello: 'x' })
  })
  it('show_detail: the API\'s sentence', async () => {
    reply(409, { detail: '一個人最多提三家。' })
    const r = await send('POST', '/api/rounds/5/proposals', { json: { place_id: 1 } })
    expect(r.action).toBe('show_detail')
    expect(() => must(r, '提不進去')).toThrow(new HttpError('一個人最多提三家。', 'show_detail', 409))
  })
  it('show_detail on a list detail (422) falls back to the helper\'s words with the status', async () => {
    reply(422, { detail: [{ loc: ['body'], msg: 'field required' }] })
    const r = await send('POST', '/api/circles', { json: {} })
    expect(() => must(r, '開不了圈子')).toThrow('開不了圈子（422）')
  })
  it('reread: a Reread with no error to show, and the body is kept for the caller', async () => {
    reply(409, { detail: { error: 'x', open_round: { round_id: 8 } } })
    const r = await send('POST', '/api/circles/7/rounds', { json: {} })
    expect(r.action).toBe('reread')
    expect(r.body.detail).toEqual({ error: 'x', open_round: { round_id: 8 } })
    expect(() => must(r, '開不了')).toThrow(Reread)
  })
  it('retry_later: the generic words, the status in them, the network without one', async () => {
    reply(503, { detail: 'db down' })
    const down = await send('GET', '/api/rounds/5/result')
    expect(() => must(down, '讀取失敗')).toThrow('讀取失敗（503）')
    reply(null)
    const r = await send('GET', '/api/rounds/5/result')
    expect([r.status, r.action]).toEqual([0, 'retry_later'])
    expect(() => must(r, '讀取失敗')).toThrow(new HttpError('讀取失敗', 'retry_later', 0))
  })
  it('forget_seat: the key and the circle are dropped, and the shared sentence is raised', async () => {
    reply(401, { detail: 'the token does not resolve to a member of this circle' })
    const r = await send('GET', '/api/circles/7/members', { headers: { authorization: 'Bearer fake-token' } })
    expect(r.action).toBe('forget_seat')
    // send itself changes nothing.
    expect(store.keys()).toContain('upto_token')
    let caught: unknown
    try { must(r, '看不到座位') } catch (e) { caught = e }
    expect(caught).toBeInstanceOf(SeatGone)
    expect((caught as Error).message).toBe(SEAT_GONE)
    expect(store.getItem('upto_token')).toBeNull()
    expect(store.getItem('upto_circle')).toBeNull()
    expect(store.getItem('upto_last_round')).toBeNull()
  })
  it('forget_seat with keepSeat (a pasted key not yet remembered) keeps the stored key', async () => {
    reply(401, { detail: 'a bearer token is required (D67)' })
    const r = await send('GET', '/api/circles/7/preferences')
    expect(() => must(r, '連不上', { keepSeat: true })).toThrow(SeatGone)
    expect(store.getItem('upto_token')).toBe('fake-token')
  })
  it('void: a RoundVoid carrying the API\'s sentence', async () => {
    const sentence = '這一輪作廢了：開始時在場的人都離開了。開新的一輪吧。'
    for (const [method, url] of [
      ['POST', '/api/rounds/5/proposals'], ['POST', '/api/rounds/5/submit'],
      ['DELETE', '/api/rounds/5/submit'], ['GET', '/api/rounds/5/result'], ['POST', '/api/rounds/5/trip'],
    ] as const) {
      reply(410, { detail: sentence })
      const r = await send(method, url)
      expect(r.action, `${method} ${url}`).toBe('void')
      let caught: unknown
      try { must(r, 'x') } catch (e) { caught = e }
      expect(caught).toBeInstanceOf(RoundVoid)
      expect((caught as Error).message).toBe(sentence)
    }
  })
})
