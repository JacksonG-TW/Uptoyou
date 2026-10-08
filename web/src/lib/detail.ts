/**
 * The API's own sentence, when it sent one — **and only when it is a string.**
 *
 * FastAPI's `detail` is not always a sentence: a 422 sends a list of field errors, and a D68 409
 * sends an object carrying the winning round. `body.detail || fallback` passes either straight into
 * `new Error(...)`, which renders as 「[object Object]」 — measured on 2026-10-08, when ten devices
 * opening one round at once showed it to every loser (reviewer, 13ec776). So every lib call reads
 * `detail` through here, and `test_web_surface` asserts no `body.detail ||` is left.
 *
 * The fallback carries the status: it renders only when the API sent no sentence, which is a defect
 * rather than a state, and a status code is what makes such a report actionable.
 */
export function detailOr(body: unknown, fallback: string, status: number): string {
  const d = (body as { detail?: unknown } | null)?.detail
  return typeof d === 'string' && d ? d : `${fallback}（${status}）`
}
