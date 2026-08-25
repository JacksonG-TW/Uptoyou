import { useCallback, useEffect, useState } from 'react'
import {
  BANDS, BAND_LABEL, CATEGORIES, INGREDIENTS,
  device, fetchPreferences, postPreference, pct, taipeiMonth,
  type Band, type Device, type Kind, type Preferences as InForce,
} from '@/lib/preferences'
/* **The stamp helpers live in `lib/round.ts` and are imported, never re-implemented here.**
   `spec-conditional-routing.md` §3 makes one key answer one question for the whole surface; a
   second copy of the comparison is how the door and the screen start disagreeing about what
   "seen" means. (`lib/preferences.ts` already carries its own duplicate `device()` — that one is
   flagged, not multiplied.) */
import { markPrefSeen, prefSeen } from '@/lib/round'

/**
 * A2 — the private preference screen. Built to `idea & img/evaluator/spec-preference-screen.md`
 * §3 A · B · B-bis · C · D · F and §4's coverage sentences.
 *
 * **What is deliberately absent, and none of it is unfinished work:**
 *
 * - **No pinned `BAR`, no back control, no screen name in a masthead.** That is the frame, and the
 *   frame is `[OPEN-2]` — with `nav.tabs` gone at `42fb6c8` the React build has no navigation at
 *   all, so where this screen is reached from is the owner's ruling, not a default to be filled in
 *   here. Adding a bar now would also spend the screen's one filled control (§4's grammar) on a
 *   control nobody has ruled the destination of.
 * - **No delete, no clear, no reset** (§3 D). Un-avoiding appends `allow`; erasure is D14's
 *   separate machinery and does not appear on a screen.
 * - **No text input in any state** (D38). Every control here is a closed list.
 * - **No link from the home screen.** Home is under A0c's fidelity gate — a pixel diff against the
 *   owner-approved page — so a nav affordance added there would fail that gate before the frame
 *   has been ruled. The route exists; nothing points at it yet.
 *
 * **The one filled control is the chosen budget band.** Everything else on this screen marks state
 * with a square marker and a rule, never with an ink ground.
 */

/** The three states a row's single control can be in. **The control's meaning is the state**, which
 *  is why there is exactly one control per row rather than a toggle plus a confirm: a second
 *  control on the row would be a second way to act on one fact, and §3 D refuses that shape for
 *  the budget for the same reason. */
type RowState = 'off' | 'on' | 'asking'

/** Which avoided ingredients this device has affirmed, and in which Taipei month.
 *
 * **This is device state on purpose and it is not a cache of the server.** The carry rule for an
 * ingredient is the strictest of the three: *never carried in silently — on a new month or a new
 * device it is shown filled and asks for the tap, every time.* A new browser context has no entry,
 * so it asks; a new month does not match, so it asks. The server holds the avoidance; this holds
 * only whether this device has been shown it this month.
 *
 * **It is not the contribute-gate and must not be read as one.** Whether an unaffirmed ingredient
 * reaches the engine is a server question, and today it reaches nothing at all because no place
 * carries ingredient data — which is exactly why the gate splits the render half from the
 * contribute half and records the second `n/a` rather than passing it.
 */
const ACK_KEY = 'upto_pref_ingredient_ack'

function readAck(): Record<string, string> {
  try {
    const raw = localStorage.getItem(ACK_KEY)
    const parsed: unknown = raw ? JSON.parse(raw) : {}
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, string>) : {}
  } catch {
    // A corrupt or unreadable entry means "this device has not affirmed anything", which is the
    // safe direction: it asks again. Throwing here would take the screen down over a stored string.
    return {}
  }
}

function writeAck(value: string, month: string): void {
  const next = { ...readAck(), [value]: month }
  try {
    localStorage.setItem(ACK_KEY, JSON.stringify(next))
  } catch {
    // Storage full or blocked: the row simply asks again next time. Nothing is lost server-side.
  }
}

export default function Preferences() {
  const [dev] = useState<Device | null>(device)
  const [inForce, setInForce] = useState<InForce | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  /* **Read once, at mount, and never re-read.** The act stamps and then navigates; a live read
     would flip this sentence out from under the person in the frame between the two, which is a
     screen rearranging itself as a reward for pressing something. The lazy initialiser also keeps
     it off StrictMode's second render. */
  const [firstVisit] = useState(() => !prefSeen())
  const month = taipeiMonth()

  const load = useCallback(async (d: Device) => {
    try {
      setInForce(await fetchPreferences(d))
      setError('')
    } catch (e) {
      setInForce(null)
      setError((e as Error).message || '讀取失敗')
    }
  }, [])

  useEffect(() => { if (dev) void load(dev) }, [dev, load])

  /**
   * Every act is the same act: append a row, then re-read what is in force.
   *
   * **The re-read is not laziness about local state — it is the D25 rule the client is not allowed
   * to reimplement.** "In force" is the latest row per key, resolved server-side; patching the
   * local object after a write would be this browser applying latest-wins, which is the one thing
   * the endpoint exists to keep out of the client. It also means `breadth` and the coverage figures
   * re-derive against the new set rather than drifting from it.
   */
  const write = useCallback(
    async (key: string, body: { kind: Kind; value: string; persist: boolean; stance?: 'avoid' | 'allow' }) => {
      if (!dev || busy) return
      setBusy(key)
      try {
        await postPreference(dev, body)
        await load(dev)
      } catch (e) {
        setError((e as Error).message || '寫入失敗')
      } finally {
        setBusy('')
      }
    },
    [dev, busy, load],
  )

  /* **The door check — `spec-conditional-routing.md` §1 and §6's G6.** A typed `/preferences`
     with no key used to end at a true, useless sentence: the person needs the device screen and
     the screen already knew it. Now it sends them, with `replace` so the back arrow does not
     return to a screen that bounces again.

     **In an effect, not during render**, for the same reason the round screen gives: a navigation
     started mid-render is a render-phase side effect, and StrictMode's double invoke fires it
     twice. One blank frame is the price. */
  useEffect(() => {
    if (!dev) window.location.replace('/device')
  }, [dev])

  if (!dev) return <main className="prefs" data-screen="preferences" />

  const budget = inForce?.budget ?? null
  const avoidedCategories = new Set((inForce?.avoid_categories ?? []).map((a) => a.value))
  /**
   * **A2-G8-always: every stance states what it zeroes, count and share, whatever the size.**
   *
   * The owner ruled two mechanisms where the evaluator proposed one, and this is the half that
   * does the work. A threshold alone would have left **nine of the ten categories silent forever**
   * — only 其他 clears 10% — so the asymmetry a person is actually creating stayed invisible
   * everywhere it was small.
   *
   * **And the zeroes are the most important thing on this screen.** An ingredient avoidance reports
   * `0 家` today, because nothing in the data carries ingredient information (D103). A member who
   * has just tapped 花生 and is shown nothing would reasonably conclude they are now protected from
   * it. **They are not, and silence is what would tell them they were.**
   */
  const stat = (list: { value: string; zeroed: number; share: number }[] | undefined) =>
    new Map((list ?? []).map((a) => [a.value, a]))
  const catStat = stat(inForce?.avoid_categories)
  const ingStat = stat(inForce?.avoid_ingredients)
  /**
   * The statement itself. **抽不到, never 拿掉／少掉／移除** (`A2-G8-verb`): the place keeps its
   * seat, stays proposable and still appears in the round and in the table at `0/36`. What changed
   * is that no roll reaches it. `D37` stands beside this — nothing is hidden from the typeahead on
   * a preference.
   *
   * **The second sentence is the evaluator's, and the reason is parallelism rather than accuracy.**
   * My draft ended 「這個選擇目前不會生效」 — true, and a different frame from every other row.
   * Four rows should read as four of the same thing; 「不會生效」 costs the reader a translation
   * step (*what does that mean for me?*) **on the row where a translation step is most expensive**.
   * 「沒有任何店家會因此抽不到」 lands in the vocabulary the screen already uses, so the comparison
   * against 480 家 and 8,664 家 is immediate rather than inferred. D20 still holds: it states the
   * consequence and advises nothing.
   *
   * **`A2-G8-zero`: where the KIND has no coverage, the row states why there is no number instead
   * of stating zero.** The first build printed 「0 家抽不到（0.0%）」 for an ingredient, and the
   * evaluator was right that this is worse than silence: **a count of zero reads as a result —
   * *we looked and nothing needed excluding*. What is true is that we hold no ingredient data at
   * all, so the choice does not act.** Those are opposite meanings and the false one is the
   * reassuring one, on the single kind the owner ruled about because 「過敏是會致死的」.
   *
   * **It keys on the kind's COVERAGE and never on `zeroed === 0`**, and the distinction is the
   * whole rule. A category avoidance that genuinely zeroes nothing at 42.6% coverage HAS been
   * measured, and 「0 家」 is then the true answer. Zero-because-measured and
   * no-measurement-exists must not render the same way, which is exactly the absent-subject
   * failure we have found all day — arriving here in the one place it costs more than a wrong
   * verdict.
   */
  const zeroLine = (a: { zeroed: number; share: number } | undefined, coverage: number) => {
    if (!a) return null
    if (!(coverage > 0)) return '店家資料還沒有這一項。目前沒有任何店家會因此抽不到。'
    return `${a.zeroed.toLocaleString('en-US')} 家抽不到（${pct(a.share)}）`
  }
  const keptCategories = new Set(
    (inForce?.avoid_categories ?? []).filter((a) => a.persist).map((a) => a.value),
  )
  const ack = readAck()
  const ingredientState = new Map<string, RowState>(
    (inForce?.avoid_ingredients ?? []).map((a) => [
      a.value,
      ack[a.value] === month ? 'on' : 'asking',
    ]),
  )
  const keptIngredients = new Set(
    (inForce?.avoid_ingredients ?? []).filter((a) => a.persist).map((a) => a.value),
  )

  return (
    <main className="prefs" data-screen="preferences">
      {/* Provisional heading — the screen's NAME is part of `[OPEN-2]`'s frame. A page with no
          h1 is worse than one whose wording may change, so it carries the plainest description
          of what is on it and no branding. */}
      <h1 className="prefsTitle">我的偏好</h1>
      {/* **The first visit says what the order is** (`spec-conditional-routing.md` §4). This screen
          is now 首次必經 — a person arrives here on the way to somewhere else and is owed the shape
          of the trip. It states the order and D17's default (nothing persists unless a keep-toggle
          is flipped) and advises nothing, which is D20's register.

          **Only on the first visit.** A returning person came here on purpose; repeating the
          orientation would tell them the surface has not noticed they have been.

          Rejected: a welcome line (the surface states, it does not greet) and any line naming
          「訪客」 — the word is the owner's and the person never chose it. */}
      {firstVisit && (
        <p className="prefsNote" data-part="pref-first">
          先選這一餐要避開的，再進去提店。這台裝置沒有存下任何東西。
        </p>
      )}
      <p className="prefsNote">只有你看得到，也只有這台裝置寫得動。</p>

      {error && <p className="prefsErr" data-part="pref-error">{error}</p>}

      {/* ── A · Budget ────────────────────────────────────────────────────────────
          Three states, and G9 requires all three to be distinguishable without reading the text
          twice: UNSET is two plain ghosts; IN FORCE fills the chosen one with ink; EXPIRED drops
          the ground and dashes the border — the same vocabulary design.md gives a control that is
          present but not acting, so nothing new is invented for it.
          **The expired state carries exactly one control, and it is the chooser itself.** Tapping
          your own band again IS the re-affirmation. There is no dismiss, no clear and no second
          button, because either of those would be an edit of a table that only appends. */}
      <section className="prefsBlock" data-part="pref-budget">
        <h2 className="prefsH">這個月的預算</h2>
        <div className="bandRow">
          {BANDS.map((b: Band) => {
            const chosen = budget?.value === b
            const expired = chosen && budget.expired
            return (
              <button
                key={b}
                type="button"
                className="band"
                data-chosen={chosen ? 'yes' : 'no'}
                data-expired={expired ? 'yes' : 'no'}
                aria-pressed={chosen}
                disabled={busy !== ''}
                onClick={() => void write(`budget:${b}`, {
                  kind: 'budget', value: b, persist: budget?.persist ?? false,
                })}
              >
                {BAND_LABEL[b]}
              </button>
            )
          })}
        </div>

        {budget?.expired && (
          <p className="prefsNote" data-part="pref-budget-expired">
            這是 {budget.valid_from.slice(0, 7)} 的選擇，已經過期，這個月還沒有算進去。點一下同一個選項就沿用。
          </p>
        )}

        {/* C · the keep choice, per preference. It appears once there is a preference to keep, and
            renders NOT KEPT until an explicit act — D17's default is expressed by the payload, not
            by this markup. Keeping re-posts the same band with `persist: true`, which appends a new
            row; there is no field to edit. */}
        {budget && (
          <button
            type="button"
            className="keep"
            data-part="pref-budget-keep"
            data-kept={budget.persist ? 'yes' : 'no'}
            aria-pressed={budget.persist}
            disabled={busy !== ''}
            onClick={() => void write('budget:keep', {
              kind: 'budget', value: budget.value, persist: !budget.persist,
            })}
          >
            <span className="mark" aria-hidden="true" />
            下個月也留著這個選擇
          </button>
        )}
      </section>

      {/* ── B · Categories ─────────────────────────────────────────────────────── */}
      <section className="prefsBlock" data-part="pref-categories">
        <h2 className="prefsH">不想吃的類型</h2>
        <ul className="rows">
          {CATEGORIES.map((c) => {
            const on = avoidedCategories.has(c)
            return (
              <li key={c} className="row" data-part="pref-category" data-on={on ? 'yes' : 'no'}>
                <button
                  type="button"
                  className="rowTap"
                  aria-pressed={on}
                  disabled={busy !== ''}
                  onClick={() => void write(`cat:${c}`, {
                    kind: 'avoid_category', value: c,
                    stance: on ? 'allow' : 'avoid',
                    persist: keptCategories.has(c),
                  })}
                >
                  <span className="mark" aria-hidden="true" />
                  <span className="rowName">{c}</span>
                  {on && <span className="rowState">避開</span>}
                  {on && (
                    <span className="rowStat" data-part="pref-stance-stat" data-shape={(inForce?.category_coverage.share ?? 0) > 0 ? 'count' : 'why'}>
                      {zeroLine(catStat.get(c), inForce?.category_coverage.share ?? 0)}
                    </span>
                  )}
                </button>
                {on && (
                  <button
                    type="button"
                    className="keep keepInline"
                    data-kept={keptCategories.has(c) ? 'yes' : 'no'}
                    aria-pressed={keptCategories.has(c)}
                    aria-label={`下個月也留著避開${c}`}
                    disabled={busy !== ''}
                    onClick={() => void write(`cat:keep:${c}`, {
                      kind: 'avoid_category', value: c, stance: 'avoid',
                      persist: !keptCategories.has(c),
                    })}
                  >
                    <span className="mark" aria-hidden="true" />
                    留著
                  </button>
                )}
              </li>
            )
          })}
        </ul>

        {/* §4's honesty requirement. The number is the payload's and is never written here — today's
            figure moved from about 6% to nearly 13% in one day, and a constant would have been
            false by the afternoon while still rendering. It STATES what the data covers; it does
            not tell anyone to wait, to choose differently, or that a choice is pointless (D20). */}
        {inForce && (
          <p className="prefsNote" data-part="pref-category-coverage">
            全市 {inForce.category_coverage.reference_rows.toLocaleString('en-US')} 家登記店家裡，
            目前有 {(inForce.category_coverage.with_category ?? 0).toLocaleString('en-US')} 家帶有分類
            （{pct(inForce.category_coverage.share)}）。沒有分類的店，避開讀不到。
          </p>
        )}

        {/* D22's breadth. **Stated, never called "crossed"** — the payload's `threshold` is null
            because D22 names no line, and a screen that invented one would be warning against a
            number nobody ruled. So while the threshold is null this renders as a plain statement of
            the share WITH the denominator the API named, and no warning renders at all.
            The denominator is NAMED in the sentence, not left to the reader: 「這個圈子提得出來
            的」 is the API's own `denominator` field said in the screen's language — the same set,
            not a second definition. Rendering the payload's English string here would put an
            untranslated sentence on a Chinese screen; restating it as a different set would be
            the unstated denominator the gate refuses. */}
        {/* **「抽不到」 and never 「排掉」** — backend's phrase, taken because it is right rather
            than because it was offered. 「排掉」 says the places are excluded, and they are not:
            an avoided place keeps its seat in the pool and can still be proposed. What changes is
            that it holds no cells on the dice table, so no roll reaches it. **The old wording
            carried exactly the error the old field name did**, which is why fixing one without the
            other would have left the screen still saying the wrong thing in the reader's language
            while the payload said the right thing in ours.

            **擲不到 → 抽不到, corrected the same day.** I took backend's phrase before the verb was
            gated, and A2-G8-verb then named 抽不到／不會中. Both are true and that was the problem:
            **the per-stance statements said 抽不到 and this line said 擲不到, two vocabularies for
            one object on one screen** — VB-2's exact shape, introduced by me, four lines apart. */}
        {/* **A2-G8b — the combined warning, and it is the ONLY thing on this screen that reads as
            a caution.** The owner's reasoning is why it is combined rather than per-stance: an
            allergy exclusion must never be discouraged, so a single legitimate stance — even 其他
            at 17.5% — must not trip anything. What deserves a word is someone who has quietly
            narrowed themselves to half the city across many stances.

            **`crossed` is read, never computed.** The server decides with `>`, so a member exactly
            on half is not warned; a surface that computed it could compute it wrong, and this one
            decides whether a person is told they have narrowed themselves.

            **It cannot fire today and that is expected, not a bug.** `breadth.share` is capped by
            categorised coverage — an uncategorised place can never be zeroed by a category
            avoidance — and coverage is 42.62%, so 0.5 is unreachable until the classifier passes
            half. **Its never-rendering is not evidence that it works**, and no fixture here fakes
            coverage to make it appear.

            **A2-G8c: this is private and it stays on this screen.** How much someone has excluded
            is a fact about their taste, and in a circle of five that is one guess from a name
            (§3.0). It is never written, never streamed, and appears in no shared payload. */}
        {inForce?.breadth.crossed && (
          <p className="prefsWarn" data-part="pref-breadth-warning">
            你目前的選擇，讓這個圈子提得出來的
            {' '}{inForce.breadth.proposable.toLocaleString('en-US')} 家裡，
            超過一半抽不到。
          </p>
        )}

        {inForce && inForce.breadth.zeroed > 0 && (
          <p className="prefsNote" data-part="pref-breadth">
            這些選擇目前讓 {inForce.breadth.zeroed.toLocaleString('en-US')} 家抽不到，
            範圍是這個圈子提得出來的 {inForce.breadth.proposable.toLocaleString('en-US')} 家
            （{pct(inForce.breadth.share)}）。
          </p>
        )}
      </section>

      {/* ── B-bis · Ingredients ─────────────────────────────────────────────────
          The same closed-list control, labelled 「不吃 …」. **The copy on this block, in every
          state including this comment's neighbours, names no medical reason of any kind.** What is
          recorded is a dietary choice; the wording is what keeps that true, and it is a PDPA
          boundary rather than a matter of tone. */}
      <section className="prefsBlock" data-part="pref-ingredients">
        <h2 className="prefsH">不吃的食材</h2>
        <ul className="rows">
          {INGREDIENTS.map((g) => {
            const state: RowState = ingredientState.get(g) ?? 'off'
            const next = state === 'off' ? 'avoid' : state === 'asking' ? 'avoid' : 'allow'
            return (
              <li key={g} className="row" data-part="pref-ingredient" data-on={state}>
                <button
                  type="button"
                  className="rowTap"
                  aria-pressed={state !== 'off'}
                  disabled={busy !== ''}
                  onClick={() => {
                    // An `asking` row affirms rather than toggles: the carry rule asks for the tap
                    // every new month and on every new device, and a tap that flipped it off
                    // instead would make the asking state a trap.
                    //
                    // **The ack is written whenever the tap results in `avoid` — including the
                    // first time.** Recording it only on the affirming tap left a just-set
                    // exclusion rendering 「點一下沿用」 the instant it was set, which asks a
                    // person to re-affirm a choice they are still looking at. The carry rule is
                    // about arriving on a NEW device or in a NEW month, not about the tap that
                    // created the row.
                    if (next === 'avoid') writeAck(g, month)
                    void write(`ing:${g}`, {
                      kind: 'avoid_ingredient', value: g,
                      stance: next, persist: keptIngredients.has(g),
                    })
                  }}
                >
                  <span className="mark" aria-hidden="true" />
                  <span className="rowName">不吃 {g}</span>
                  {state === 'on' && <span className="rowState">避開</span>}
                  {state === 'asking' && <span className="rowState asking">點一下沿用</span>}
                  {/* **This row states why there is no number, not a number.** Ingredient coverage
                      is 0.0 — nothing in the data carries it (D103) — so there is no measurement to
                      report, and printing 「0 家」 would claim one. It becomes a count on its own
                      the day the data does; no code here has to remember. */}
                  {state !== 'off' && (
                    <span className="rowStat" data-part="pref-stance-stat" data-shape={(inForce?.ingredient_coverage.share ?? 0) > 0 ? 'count' : 'why'}>
                      {zeroLine(ingStat.get(g), inForce?.ingredient_coverage.share ?? 0)}
                    </span>
                  )}
                </button>
                {state !== 'off' && (
                  <button
                    type="button"
                    className="keep keepInline"
                    data-kept={keptIngredients.has(g) ? 'yes' : 'no'}
                    aria-pressed={keptIngredients.has(g)}
                    aria-label={`下個月也留著不吃${g}`}
                    disabled={busy !== ''}
                    onClick={() => void write(`ing:keep:${g}`, {
                      kind: 'avoid_ingredient', value: g, stance: 'avoid',
                      persist: !keptIngredients.has(g),
                    })}
                  >
                    <span className="mark" aria-hidden="true" />
                    留著
                  </button>
                )}
              </li>
            )
          })}
        </ul>

        {/* §4's harder case, and the sentence carries the defence rather than hiding it: on day one
            nothing acts on these at all. The figure comes from the payload for the same reason the
            category one does — the day a source arrives, a zero in the markup keeps reading zero. */}
        {inForce && (inForce.ingredient_coverage.with_ingredient ?? 0) === 0 && (
          <p className="prefsNote" data-part="pref-ingredient-coverage">
            目前沒有任何店家帶有食材資料，所以這裡的選擇還不會影響任何一輪。
            先記下來，是為了資料到位的那天不用再問一次。
          </p>
        )}
      </section>

      {/* **The way forward** (`spec-conditional-routing.md` §4). One command, the ruled `.act`
          recipe — hot ground, ink text, ink SINK — label 這一餐.

          **It submits nothing.** Every value on this screen was already written the moment it was
          tapped (A1: one 204 per press, no "save"), so this act only stamps the routing fact and
          leaves. Calling it 送出 would claim work it does not do.

          **Always present, not only on the first visit.** The screen is 首次必經，之後隨時可回, and
          a person who came back on purpose also wants a door out that is not the switcher.

          **A `<button>`, not the home's `<a>`.** The home's act is pure navigation and belongs in
          an `href`; this one writes local state first, and a middle-click on a link would open a
          tab that never got the stamp and bounced straight back here. `assign`, not `replace`:
          this screen IS somewhere to come back to now, so it keeps its history entry. */}
      <div className="act-row">
        <button
          type="button"
          className="act"
          data-part="pref-done"
          onClick={() => { markPrefSeen(dev.circle); window.location.assign('/round') }}
        >
          這一餐
        </button>
      </div>
    </main>
  )
}
