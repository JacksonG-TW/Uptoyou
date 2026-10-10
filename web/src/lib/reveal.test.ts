import { afterEach, describe, expect, it, vi } from 'vitest'
import { faceOf, fetchRaw, markOf, RoundStillOpen, signTrip, type Places } from './reveal'
import { RoundVoid, SEAT_GONE } from './http'

const places: Places = { '448': 'shop C', '356': 'shop B', '3332': 'shop D', '7': 'shop A', '8': 'shop E' }

describe('the board mapping — a cell names its shop by pool seat', () => {
  // **Ascending place id, not the payload's order.** `places` is keyed by integer-like strings, and
  // JavaScript orders such keys numerically whatever order the JSON sent them in. Every screen reads
  // `Object.keys(places)`, so the board, the list and the chip still agree with each other.
  it('numbers shops 1…N by ascending place id', () => {
    expect([7, 8, 356, 448, 3332].map((id) => markOf(places, id))).toEqual([1, 2, 3, 4, 5])
  })
  it('cycles the four faces and repeats from the fifth shop, so the number carries identity', () => {
    expect([7, 8, 356, 448, 3332].map((id) => faceOf(places, id))).toEqual(['hot', 'cobalt', 'jade', 'sun', 'hot'])
  })
  it('names no shop for a place outside the pool, rather than defaulting to the first', () => {
    expect(markOf(places, 999)).toBeNull()
    expect(faceOf(places, 999)).toBeNull()
    expect(markOf(places, null)).toBeNull()
  })
})

describe('signTrip and fetchRaw — the table decides, not the status', () => {
  const dev = { token: 'fake-token', circle: '7' }
  const answer = (...rs: [number, unknown][]) => {
    const f = vi.fn()
    for (const [st, body] of rs) f.mockResolvedValueOnce(new Response(JSON.stringify(body), { status: st }))
    vi.stubGlobal('fetch', f)
    return f
  }
  afterEach(() => { vi.unstubAllGlobals() })

  it('a signed 201 is created, and the body is nested', async () => {
    answer([201, { trip: { nickname: '小明', signed_at: 't' } }])
    expect(await signTrip(dev, 5)).toEqual({ trip: { nickname: '小明', signed_at: 't' }, created: true })
  })
  it('the «already signed» 409 is reread: the reveal is read again and nothing is created', async () => {
    const f = answer([409, { detail: '小明已經在 12:03 記下這一趟了。' }],
      [200, { round_id: 5, trip: { nickname: '小明', signed_at: 't' } }])
    expect(await signTrip(dev, 5)).toEqual({ trip: { nickname: '小明', signed_at: 't' }, created: false })
    expect(f).toHaveBeenCalledTimes(2)
  })
  it('a void round\'s 410 is RoundVoid with the API\'s sentence, never «already signed»', async () => {
    const sentence = '這一輪作廢了：開始時在場的人都離開了。開新的一輪吧。'
    answer([410, { detail: sentence }])
    await expect(signTrip(dev, 5)).rejects.toMatchObject({ action: 'void', message: sentence })
    answer([410, { detail: sentence }])
    await expect(signTrip(dev, 5)).rejects.toBeInstanceOf(RoundVoid)
  })
  it('an open round\'s result is RoundStillOpen (a Reread); a void one is RoundVoid', async () => {
    answer([409, { detail: '這一輪還沒擲出結果。' }])
    await expect(fetchRaw(dev, 5)).rejects.toBeInstanceOf(RoundStillOpen)
    answer([410, { detail: '這一輪作廢了：開始時在場的人都離開了。開新的一輪吧。' }])
    await expect(fetchRaw(dev, 5)).rejects.toBeInstanceOf(RoundVoid)
  })
  it('a 401 on the reveal forgets the seat and says the shared sentence, not the English', async () => {
    const store = new Map([['upto_token', 'fake-token'], ['upto_circle', '7']])
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    })
    answer([401, { detail: 'the token does not resolve to a member of this circle' }])
    await expect(fetchRaw(dev, 5)).rejects.toMatchObject({ message: SEAT_GONE })
    expect(store.size).toBe(0)
  })
})
