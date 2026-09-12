/**
 * The reveal's wire shapes — D105's two of them.
 *
 * **There is one type here for the member and one for the operator, and the member's is not the
 * operator's with fields marked optional.** That is the whole ruling expressed in the type system:
 * the member's *response* does not contain the accounting, so there is nothing in the browser to
 * hide, toggle or forget to hide. A single type with `weights?: …` would compile the leak.
 *
 * `for_credential` in `api_common.py` builds the member shape by whitelist — `round_id · status ·
 * dice · sum · winning_place_id · places · trip · winner_headline · winner_qualifier ·
 * ingredient_data · my_reasons` — so a field added to the payload is operator-only
 * until someone names it there. These types mirror that whitelist and nothing else.
 */

/** `place_id` → the name the API composed (D92's three layers). Keys are strings on the wire. */
export type Places = Record<string, string>

/** D106: the trip is named. One per round, and the proposal it beat is still anonymous. */
export type Trip = { nickname: string; signed_at: string } | null

/** D108's seat, as it reaches the reveal. **The member payload carries `rolls[]` and the reveal
 *  does not render it** — the owner ruled 「同一對」 on 2026-08-19: every screen shows the deciding
 *  pair only. A field arriving is not a field being shown, and the static per-member list is a
 *  separate unruled feature. */
export type Roll = {
  member_id: number
  nickname: string
  die1: number | null
  die2: number | null
  counts: boolean
}

export type MemberReveal = {
  round_id: number
  status: string
  dice: [number, number]
  sum: number
  winning_place_id: number | null
  places: Places
  /** A16 / D92's 2026-08-27 amendment — the winner's name shortened for the ONE headline line.
   *  Composed by the API (`upto.headline`), never here: the authored token list belongs in git
   *  behind `tools/server_copy.py`'s gate, and the same place must read the same on every screen.
   *  **`null` is a real state** — a payload that predates A16, or a winner the API could not
   *  compose one for. The headline then falls back to `places[winning_place_id]`; it never renders
   *  empty, and `places` itself is untouched so every list row keeps the composed name. */
  winner_headline: string | null
  /** The bracket D92 composes onto a name that needs one （大安和平東路）, **without its
   *  parentheses**, or `null` when the name has none — owner-ruled 2026-08-28, `design.md` §4b.
   *  It is the address line the member payload otherwise lacks, so the headline can be the short
   *  name and still say WHICH branch. The browser adds no punctuation to it and computes nothing
   *  from it; a parenthesis appearing here is a defect, and so is this string appearing on a list
   *  row, where the composed name already carries the bracket. */
  winner_qualifier: string | null
  /**
   * The 36 outcomes as the server drew them — **`board[die1 − 1][die2 − 1]` is that cell's
   * `place_id`**, row = the first die, column = the second, both 1…6 from the top left. Candidate
   * 17 (`e603936`), `spec-board-2026-09-11.md` §2.
   *
   * **Nested, not flat, and that is the point of the field.** A flat 36 makes the client compute
   * `(die1 − 1) * 6 + (die2 − 1)`, and a client that writes the two the other way round gets a
   * board that renders perfectly and puts the wrong shop under the rolled pair — wrong, plausible,
   * and invisible unless somebody checks a cell against the winner. Nested, the ruling's own
   * sentence IS the access expression.
   *
   * **The cells are plain ints and `places` is keyed by strings**, so a name is
   * `places[String(cell)]` (BD-12 pins the asymmetry so a client does not discover it twice).
   *
   * **`undefined` is a real state and means draw nothing**: a swept pool has no honest draw, so
   * the field is absent rather than an empty array (§5). Never a grey grid in its place — an even
   * grid reads as «everyone had the same chance», which is a false statement (D112).
   */
  board?: number[][]
  /* **`ingredient_data` and `my_reasons` left `MEMBER_KEYS` on 2026-08-30**
   *  (`spec-return-choice.md` §1). The first said `declared`/`unknown` per pooled place and the
   *  second carried this reader's own veto sentences; the ingredient kind is withdrawn, so neither
   *  has anything to describe. The rule the first was built on outlives it and is recorded in
   *  `defences.md`: an absent mark reads as clean, so `unknown` had to be a value rather than a
   *  blank — which is why withdrawing the feature meant removing the column, not emptying it. */
  trip: Trip
  /** D108. `seed_commit` was published at open, before the first place was proposed; `revealed_seed`
   *  is `null` until the round closes and is what makes the commitment checkable. */
  seed_commit: string
  revealed_seed: string | null
  rolls: Roll[]
  deciding_member: { id: number; nickname: string } | null
}

/** One factor the fold actually applied. `reason` is `null` unless D13 lets it travel — a
 *  `represented_member` reason reaches that member alone and nobody else, **including the
 *  operator**, who audits the arithmetic rather than the people. */
export type Factor = {
  channel: string
  contributor: string
  effect: string
  reason: string | null
  /**
   * **Did this contributor actually run** — candidate 16, `spec-weights-picture-2026-09-11.md` §3.
   *
   * The panel carries every known contributor at its D46 position, so the picture has the same
   * rows every round and 「上次去過 showing nothing」 is a fact the payload states rather than one
   * the client infers from an absence (§4's last bullet forbids the inference).
   *
   * **A padded row and a real one that measured no difference both read `effect: "1"`**, so the
   * drawing keys the empty track on THIS field and never on the value. `false` = did not run →
   * empty track and 「—」. `true` at effect 1 = measured, no difference → a full bar. The evaluator
   * measured on 2026-09-11 that no contributor on today's build can store a 1.000 (`weather`
   * returns no record at gap 0 per D43, `last_trip` is always ×0.5, D103's `1 − 1/N` reaches 1 at
   * no finite N), so `effect` would happen to work — which is exactly why it is not what is read.
   */
  fired: boolean
}

/** Operator only. Kept in a separate type so that nothing which renders a member screen can even
 *  name these fields — §8's build order made concrete: member state complete first, because
 *  building the operator state and subtracting is how a field survives in the member payload. */
export type Evidence = {
  weights: Record<string, string>
  allocation: Record<string, number>
  /** `base` is the fold's starting weight (`"1"`) and is **not** a `factors` row: `fold()` begins
   *  at `Decimal("1")` and multiplies, with no `weight_contribution` record behind it, and the one
   *  payload an operator audits against the database must not carry a row no record backs. The
   *  picture draws it as its own first row (§3, corrected by the evaluator 2026-09-11). */
  panel: Record<string, { base: string; factors: Factor[]; clamps: unknown[] }>
}

/**
 * The accounting, or `null` for a member — **read from the response rather than from a role flag**.
 *
 * D105 puts the role on the credential and the shape on the response, so *is this an operator* is
 * answered by asking what arrived, never by asking who is asking. A client that decided this from
 * a stored flag would be one bug away from rendering a table it did not receive, and one bug the
 * other way from hiding one it did — and neither failure would show on a member's screen, which is
 * the only place it would matter.
 */
export function evidenceIn(body: unknown): Evidence | null {
  const b = body as Partial<Evidence>
  if (!b || typeof b !== 'object') return null
  if (!b.allocation || !b.weights || !b.panel) return null
  return { weights: b.weights, allocation: b.allocation, panel: b.panel }
}

/** design.md §1: the four face colours, cycled by **pool seat**. Identity, never quantity — the
 *  colour says which place, never how much of the 36 it holds. */
export const FACES = ['hot', 'cobalt', 'jade', 'sun'] as const
export type Face = (typeof FACES)[number]

/** The seat a place holds in the pool, and therefore its face. Key order is the payload's, which
 *  is the pool's, so the same place keeps the same colour between the round screen and the reveal.
 *  Returns `null` for a place not in the pool rather than defaulting to seat 0 — a wrong colour is
 *  a wrong identity claim, and silence is better than a confident one. */
export function faceOf(places: Places, placeId: number | null): Face | null {
  if (placeId === null) return null
  const seat = Object.keys(places).indexOf(String(placeId))
  return seat < 0 ? null : FACES[seat % FACES.length]
}

export type Device = { token: string; circle: string }

export function device(): Device | null {
  const token = localStorage.getItem('upto_token')
  const circle = localStorage.getItem('upto_circle')
  return token && circle ? { token, circle } : null
}

/**
 * Roll, or re-read a round already rolled.
 *
 * **D69: rolling a closed round answers 200 with the stored result**, so this one call is both
 * "roll it" and "show me what it landed on" — the retry gets what it lost. That is why the reveal
 * needs no second endpoint to read a result, and why a reload after the roll is not a special case.
 */
export async function fetchReveal(d: Device, roundId: number): Promise<MemberReveal> {
  return (await fetchRaw(d, roundId)) as MemberReveal
}

/** The response untouched. The reveal needs both halves of it — the member fields it renders and,
 *  for an operator credential, the accounting that arrived alongside them — and asking twice would
 *  mean two rolls' worth of requests for one screen. */
export async function fetchRaw(d: Device, roundId: number): Promise<unknown> {
  const r = await fetch(`/api/rounds/${roundId}/roll`, {
    method: 'POST',
    headers: { authorization: `Bearer ${d.token}` },
    cache: 'no-store',
  })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || `讀取失敗（${r.status}）`)
  }
  return r.json()
}

/**
 * D106 — sign the trip. **No body**: who signed comes from the credential, and where they went is
 * the round's own stored winner. There is nothing for a client to assert and therefore nothing for
 * it to get wrong.
 *
 * Three outcomes and none of them is an error the screen should shout about: **201** this member
 * signed, **200** the same member tapped twice (D69's idiom — a retry is not a conflict), **409**
 * somebody else already signed.
 *
 * **The two response shapes are different and I got both wrong first time, so they are written
 * down here rather than remembered.** 201 and 200 answer `{"trip": {nickname, signed_at}}` —
 * **nested**, not flat; reading `body.nickname` yields `undefined`, which rendered a signed bar
 * with an empty name and no error anywhere. 409 answers `{"detail": "<name>已經在 <時間>
 * 記下這一趟了。"}` — **a finished sentence for a person, not fields**, so there is nothing to
 * destructure.
 *
 * So the 409 branch **re-reads the reveal** instead of parsing prose. The round's own payload
 * carries `trip`, which is the same object every other member is looking at, and that makes the
 * losing signer's screen identical to the winner's rather than a second rendering of the same
 * fact. D68's shape — the loser gets what it lost — applied to a table that already holds it.
 */
/**
 * **`created` says whether THIS device's press is what signed it**, and 乙 §3 is why it exists.
 *
 * D106 makes 201 and 409 the same success from the member's side — either way the trip is signed
 * and the screen must show it — so this function returned only the trip and the caller could not
 * tell the two apart. The sign act's 450 ms landing may only play on 201: on a 409 someone else
 * signed first, **the trip line is already true and belongs on screen instantly** (§1a rule 5 — a
 * refusal or a fact that fades in has not happened yet). Without this flag the animation would
 * play on both, which is the one case §3 names as proving the rule is not decoration.
 *
 * It answers the reload too, and that is the third case neither status covers: a trip already in
 * the payload was signed before this screen existed, so nothing lands. That path never calls this
 * function, so `created` is simply never set — the default is *do not animate*, which is the safe
 * direction for a rule about things that must not move.
 */
export async function signTrip(
  d: Device, roundId: number,
): Promise<{ trip: Trip; created: boolean }> {
  const r = await fetch(`/api/rounds/${roundId}/trip`, {
    method: 'POST',
    headers: { authorization: `Bearer ${d.token}` },
  })
  if (r.status === 201 || r.status === 200) {
    const body = await r.json().catch(() => ({}))
    return { trip: body.trip ?? null, created: true }
  }
  if (r.status === 409) return { trip: (await fetchReveal(d, roundId)).trip, created: false }
  const body = await r.json().catch(() => ({}))
  throw new Error(body.detail || `簽不上（${r.status}）`)
}
