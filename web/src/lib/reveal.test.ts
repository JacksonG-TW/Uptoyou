import { describe, expect, it } from 'vitest'
import { faceOf, markOf, type Places } from './reveal'

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
