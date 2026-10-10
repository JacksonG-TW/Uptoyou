import { send } from './http'

/**
 * How many shops the source lists today — `GET /api/places/count` (agreed with backend
 * 2026-10-08; `spec-nav-labels-home-2026-10-08.md`, last section).
 *
 * The number is `place_rows` of the newest 食藥署 publication, and `as_of` is the **publisher's own
 * date** (the day 食藥署 cut the file), so the home can say «N shops, as of that day» as the
 * source's fact rather than ours. The brand brief requires the figure to match the live count
 * wherever it is quoted, which is why it is read, never written into the page.
 *
 * **Any failure is `null`** — a 503 before the first ingest, a network error, or an api without the
 * route (production before backend lands it). The caller then drops the number and keeps the
 * source's name: a missing number is true, a stale one is not.
 */
export type PlaceCount = { count: number; asOf: string }

export async function fetchPlaceCount(): Promise<PlaceCount | null> {
  try {
    const r = await send('GET', '/api/places/count')
    if (r.action !== 'success') return null
    const body = await r.json<{ count?: unknown; as_of?: unknown }>()
    if (typeof body.count !== 'number' || typeof body.as_of !== 'string') return null
    return { count: body.count, asOf: body.as_of }
  } catch {
    return null
  }
}
