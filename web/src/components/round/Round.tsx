import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import {
  openRound, propose, submit, unsubmit, searchPlaces, materialise, subscribe,
  type Candidate, type OpenRound, type Pooled, type Roll,
} from '@/lib/round'
import { device, forget, noteLastRound, type Device } from '@/lib/device'
import { fetchReveal } from '@/lib/reveal'
import { removeSeat } from '@/lib/selfserve'
import { Coffee, Ellipsis, Soup } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { arrive } from '@/lib/motion'
import {
  CATEGORIES, fetchPreferences, postPreference,
  type Preferences,
} from '@/lib/preferences'

/**
 * The menu's three section marks — 密度一, ruled by the owner 2026-09-03
 * (`spec-round-menu-2026-09-03.md` sec. 2, over 密度〇 and 密度二).
 *
 * **This grouping is authored by us and nothing may read it.** D38 has no notion of a section:
 * the API's closed list is thirteen flat values, and these three groups plus their two invented
 * headings exist on this screen and nowhere else. They were on the page the owner ruled from, so
 * they are ruled as rendered — but they are presentation. Not a payload field, not a sort key, not
 * a filter, and no module outside this file learns they exist. That is why the table lives here
 * beside the markup rather than in `lib/preferences.ts` with `CATEGORIES`, which is mirrored from
 * a migration and may only hold what the database holds.
 *
 * **One icon per section and none on a row** (ruling 2). `design.md` rule 6's parenthesis — the
 * surface uses almost no icons, keep it that way rather than decorating — is why this is three and
 * not sixteen. `Ellipsis`, not the deprecated `MoreHorizontal` alias.
 *
 * **The last section takes the remainder rather than a hand-written list, and that is a guard, not
 * a shortcut.** A fourteenth category would otherwise land in no section and vanish from a screen
 * that is supposed to state the whole closed list. Placing it by hand is still correct and still
 * the intent — this only decides where it sits until someone does, and a row under 其他 is a
 * recoverable wrong answer where a missing row is a silent one. Order inside every section is
 * `CATEGORIES`' own, because each list is a filter of it and never a re-sort: the API's order is
 * the reading order and 其他 is last by rule.
 */
const HOT = ['麵食', '飯食', '小吃', '火鍋', '燒烤', '日式', '西式', '台菜', '素食']
const LIGHT = ['早餐', '咖啡飲料', '便利商店']

const MENU_SECTIONS = [
  { heading: '主食與熱食', Icon: Soup, values: CATEGORIES.filter((c) => HOT.includes(c)) },
  { heading: '輕食與飲品', Icon: Coffee, values: CATEGORIES.filter((c) => LIGHT.includes(c)) },
  {
    heading: '其他',
    Icon: Ellipsis,
    values: CATEGORIES.filter((c) => !HOT.includes(c) && !LIGHT.includes(c)),
  },
]

/**
 * 乙's stagger step per chip row — `spec-motion-arrival-2026-09-11.md` §2.
 *
 * **Reading order across the whole menu, capped at six steps.** Past six the stagger outruns §1a
 * rule 4's one beat, so rows seven and after share the sixth step: the thirteen rows finish at
 * 450 + 5 × 90 = 900 ms rather than at 450 + 12 × 90 = 1,530, which would be two beats and a
 * loading spinner wearing a costume.
 *
 * **Computed from `MENU_SECTIONS`, not typed**, so adding a category or moving one between
 * sections cannot leave a hand-kept step list disagreeing with the order on screen — the same
 * argument the engine's contributor register makes one directory over. The index runs across
 * sections because a reader reads across them; each section restarting at 0 would make three
 * groups arrive in parallel and read as three screens.
 */
const ARRIVE_CAP = 5
const CHIP_STEP: Record<string, number> = Object.fromEntries(
  MENU_SECTIONS.flatMap(({ values }) => values).map((c, i) => [c, Math.min(i, ARRIVE_CAP)]),
)

/**
 * A4 — the round screen: open, propose, roll.
 *
 * **The pool is fed by the stream, not by the response to the write.** D56 makes the snapshot the
 * stream's first event, so a screen that has connected already knows the state, and a `pooled`
 * event arrives the same way whether this device proposed or another one did. Appending locally on
 * a successful POST would be a second source of truth that agrees today and drifts the first time
 * two people propose at once.
 *
 * **Nothing here names who proposed what** (§3.0, D14). The `pooled` event carries a place and no
 * member, the snapshot's pool carries names and no authorship, and there is no column behind
 * either by the time the round closes. So the absence is structural rather than a field this
 * component declines to render — but it is still asserted, because the payload could grow one.
 *
 * **The roll does not navigate on its own response.** It waits for the `closed` event, so every
 * device in the circle moves to the reveal on the same signal at the same moment — which is the
 * whole point of the stream, and the difference between a shared moment and five separate ones.
 */
export default function Round() {
  const [dev] = useState<Device | null>(device)
  const [roundId, setRoundId] = useState<number | null>(null)
  const [pool, setPool] = useState<Pooled[]>([])
  /** D108's seats, read from the snapshot so they are on the first painted frame rather than
   *  arriving. */
  const [rolls, setRolls] = useState<Roll[]>([])
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<Candidate[]>([])
  /** The query the server has actually answered, or `null` if nothing has come back for what is in
   *  the box right now. **Not a boolean**: it holds the string, so a stale answer for an older
   *  query can never be read as an answer for this one. */
  const [answered, setAnswered] = useState<string | null>(null)
  /** The query whose request came back with no answer at all. Same shape and same guard as
   *  `answered` for the same reason — **a late-arriving failure for an old query must not smear the
   *  current one**, which is the stale-response hazard the sequence number already handles on the
   *  success path, met on the third path. */
  const [failed, setFailed] = useState<string | null>(null)
  const [error, setError] = useState('')
  /** The stream's own state, apart from `error`: a reconnect clears this line and must not clear
   *  a refused proposal's sentence that happens to be showing beside it. */
  const [streamDown, setStreamDown] = useState<string | null>(null)
  /** UX batch U7 — the last closed round, for 「上一餐」. The snapshot names it (`last_result`);
   *  its name comes from the same read the reveal uses (`GET …/result`), so this line and the
   *  reveal can never name two different places. Names nobody: not who rolled, not who proposed. */
  const [lastMeal, setLastMeal] = useState<{ round: number; name: string } | null>(null)
  const lastAsked = useRef<number | null>(null)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)
  /** The open round as the stream last said, readable inside the subscription without
   *  re-subscribing on every change. */
  const openId = useRef<number | null>(null)

  /** **「這次不吃」's state is the server's, read once on mount** (`spec-preference-split.md` §2).
   *  `null` until the GET answers, which is why the row renders its chips off rather than not at
   *  all — ten controls appearing a beat late would move the search box under the reader's thumb. */
  const [prefs, setPrefs] = useState<Preferences | null>(null)
  /** The taps this device has made that the server has not confirmed yet, `value → intended on`.
   *
   *  **Optimistic for the CHIP, server-owned for the NUMBERS.** A tap has to answer instantly or
   *  the row reads as broken, but the count under it (`481 家會比較少中`) is the API's and may not
   *  be guessed — so the chip flips here and the sentence waits for the re-read. On a non-204 the
   *  entry is dropped and the chip snaps back to what the server last said, which is the only
   *  state this screen is allowed to assert. */
  const [pending, setPending] = useState<Record<string, boolean>>({})
  /** Whether 「這次不想吃的類別」 is open. **Not remembered** — it starts closed on every visit
   *  (`spec-round-diet-circle-2026-10-08.md` A1): most rounds never touch it. */
  const [tonightOpen, setTonightOpen] = useState(false)

  /** **The round whose pool swept to nothing, or `null`.** A round id rather than a boolean, and
   *  that is what makes the clear rule correct: the line clears on the next `pooled` **for that
   *  round**, so a late event for a round this device has moved on from cannot clear a line that
   *  belongs to the current one. Never cleared on a timer — the state is true until the pool
   *  changes, and a sentence that disappears by itself would say the table's sum had changed when
   *  nothing had. */
  const [swept, setSwept] = useState<number | null>(null)
  /** A refused roll, **kept with the round it was refused on rather than merged into `error`**.
   *
   *  The refusal reaches this device twice for the swept-pool case — as its own 409 `detail` and as
   *  the `pool_swept` every seat receives — and §2 says the roller reads one line. Suppression is
   *  therefore a **derived** question, not something the catch can answer: the two arrive over
   *  different transports and either can be first. Holding the message and deciding at render is
   *  what makes the order stop mattering; a check inside the catch would have shown two lines
   *  whenever the event was a beat late, which is the timing a fast local stack never produces and
   *  a phone on a train does. */
  const [rollError, setRollError] = useState<{ round: number; message: string } | null>(null)
  /** **The waiting room** (`spec-round-waiting-room-2026-10-09.md`). Who this device is and who the
   *  host is, from the snapshot (backend, 2026-10-09); a ref beside `me` so the stream's handler,
   *  set up once, can tell an event about this seat from one about another. */
  const [me, setMe] = useState<number | null>(null)
  const meRef = useRef<number | null>(null)
  const [host, setHost] = useState<number | null>(null)
  /** The host's 請人離開 screen, and the seat chosen on it — nothing chosen when it opens. */
  const [leaving, setLeaving] = useState(false)
  const [chosen, setChosen] = useState<number | null>(null)
  /** This seat is gone: `removed` when the host asked it to leave (the event), `dead` when the key no
   *  longer opens the circle (a device that was away when it happened reconnects to a 401). Either
   *  way the circle is forgotten, one line shows, then home. */
  const [removed, setRemoved] = useState<null | 'removed' | 'dead'>(null)
  /** **Whether the list column fits the window** (the evaluator's round 2 on 40350e9). While it fits,
   *  the whole column sticks and the names stay readable at any scroll; once it is taller than the
   *  room under the bars (about ten seats), only the 名單 sticks and the seats scroll beneath it. */
  const listRef = useRef<HTMLDivElement>(null)
  const [listFits, setListFits] = useState(true)

  /** Forget the circle, say one line, go home (spec §The device that was asked to leave). */
  const goneOnce = useRef(false)
  const gone = (why: 'removed' | 'dead') => {
    // **Once.** The server ends a removed seat's stream right after `seat_removed`, the stream
    // reconnects a second later and meets a 401, and without this guard that second path replaced
    // 「房主請你離開了這個圈子。」 with the neutral line mid-message (the reviewer, on 2241d86).
    if (goneOnce.current) return
    goneOnce.current = true
    forget()
    setRemoved(why)
    window.setTimeout(() => { window.location.href = '/' }, 2500)
  }

  useEffect(() => {
    if (!dev) return
    return subscribe(dev, (e) => {
      // One reader for both, because a snapshot and a `round_opened` carry the same object and
      // reading them in two places is how the two come to disagree after an edit to one.
      const take = (r: OpenRound | null | undefined) => {
        openId.current = r?.round_id ?? null
        setRoundId(r?.round_id ?? null)
        setPool(r?.pool ?? [])
        setRolls(r?.rolls ?? [])
        // A new round, or a reconnect: the sweep belonged to the round that is being replaced.
        // **The snapshot does not carry the state and must not be made to** — it is the answer to
        // a roll, not a property of the round, so a reconnecting device is told by the next roll
        // rather than shown a sentence about an attempt it did not see.
        setSwept(null)
        setRollError(null)
      }
      if (e.type === 'snapshot') {
        meRef.current = e.me ?? null
        setMe(e.me ?? null)
        setHost(e.host ?? null)
        const last = e.last_result?.round_id ?? null
        // Only the newest snapshot's answer may land: two snapshots close together (a reconnect)
        // start two reads, and the older one must not overwrite the newer (reviewer 2026-10-08).
        lastAsked.current = last
        if (last !== null) {
          /* **The bar's 上一餐結果 follows the server, not this device's history** (the reviewer's
             should on 3b0921d). It read `upto_last_round`, which only the reveal wrote — so a
             member who missed the last rounds was sent to an older meal under a label that says
             «last». The snapshot names the circle's latest closed round; it is recorded here. */
          noteLastRound(last)
          fetchReveal(dev, last)
            .then((r) => {
              if (lastAsked.current !== last) return
              const name = r.winning_place_id !== null
                ? (r.winner_headline ?? r.places[String(r.winning_place_id)])
                : null
              setLastMeal(name ? { round: last, name } : null)
            })
            .catch(() => { if (lastAsked.current === last) setLastMeal(null) })
        } else {
          setLastMeal(null)
        }
        // **A reconnect can land after the round it was watching has closed** — the `closed` event
        // went out while this device was not listening. The snapshot then has no open round and
        // the result's id is the one we were in, so we go where `closed` would have sent us.
        if (!e.open_round && openId.current !== null && e.last_result?.round_id === openId.current) {
          window.location.href = `/reveal?round=${openId.current}`
          return
        }
        take(e.open_round)
      } else if (e.type === 'round_opened') {
        take(e.round)
      } else if (e.type === 'pooled') {
        // Keyed by place, because D70 lets the same place be proposed twice and the second time
        // must change nothing a person can see.
        setPool((p) => (p.some((x) => x.place_id === e.place.place_id) ? p : [...p, e.place]))
        // **The sum changed, so the sentence about the sum stops being true.** Scoped to the same
        // round: `pooled` for another round says nothing about this one's pool. A repeat proposal
        // (D70) still arrives as `pooled` and still clears — the line's claim is 「every place is
        // vetoed」, and a device that cannot tell a new place from a repeat must not keep asserting
        // it; the next roll re-emits `pool_swept` if it is still true. Wrong for a moment beats
        // wrong until someone presses something.
        setSwept((r) => (r === e.round_id ? null : r))
        // **And the held refusal goes with it.** Without this the roller's 409 would reappear the
        // moment the sweep cleared — the sentence is suppressed *while* the sweep explains it, and
        // once the pool changes the refusal is about a state that no longer exists.
        setRollError((r) => (r && r.round === e.round_id ? null : r))
      } else if (e.type === 'pool_swept') {
        // **Every seat, including the one that rolled.** The owner's ruling is that the table is
        // told, not the presser: 「反饋訊息給所有玩家」. Idempotent — a second roll on an unchanged
        // pool emits it again and the state is already this.
        setSwept(e.round_id)
      } else if (e.type === 'closed') {
        window.location.href = `/reveal?round=${e.result.round_id}`
      } else if (e.type === 'submitted') {
        // Who has submitted, out of the seats the round waits for. Names only ever move between the
        // two groups; nobody's proposals travel with them (owner: submitted / not only).
        if (e.round_id !== openId.current) return
        const done = new Set(e.submitted)
        setRolls((rs) => rs.map((r) => ({ ...r, submitted: done.has(r.member_id) })))
      } else if (e.type === 'voided') {
        // Everyone who was there at the open has left: no reveal follows, the screen has no round.
        if (e.round_id === openId.current) take(null)
      } else if (e.type === 'seat_left' || e.type === 'seat_removed') {
        if (e.type === 'seat_removed' && e.member_id === meRef.current) {
          gone('removed')
          return
        }
        setRolls((rs) => rs.map((r) => (r.member_id === e.member_id ? { ...r, left: true } : r)))
      } else if (e.type === 'host_changed') {
        setHost(e.member_id)
      }
    }, setStreamDown, () => gone('dead'))
  }, [dev])

  // The typeahead. Every keystroke carries a sequence number and a late response for an older
  // query is dropped — without it, a slow request for 「牛」 lands after a fast one for 「牛肉麵」
  // and the list silently reverts to the broader search.
  useEffect(() => {
    const query = q.trim()
    if (!dev || query.length === 0) { setHits([]); setAnswered(null); setFailed(null); return }
    const mine = ++seq.current
    // **Cleared on every keystroke, so "answered" can never describe an older query.** This is the
    // whole mechanism behind the zero-result line: `hits.length === 0` is true while a request is
    // in flight AND when it came back with nothing, and those are different facts to a person.
    setAnswered(null)
    setFailed(null)
    const t = window.setTimeout(() => {
      void searchPlaces(dev, query)
        .then((r) => {
          if (mine !== seq.current) return
          setHits(r)
          setAnswered(query)
        })
        // **A request that got no answer is its own state, not an empty result.** Before this it
        // was an unhandled rejection and the screen simply stayed blank — the same ambiguity the
        // zero-result line was built to close, surviving on the branch nobody drove. `hits` is
        // emptied too, so a failure cannot leave the previous query's rows on screen under a
        // sentence saying the search did not answer.
        .catch(() => {
          if (mine !== seq.current) return
          setHits([])
          setFailed(query)
        })
    }, 180)
    return () => window.clearTimeout(t)
  }, [dev, q])

  const add = useCallback(async (c: Candidate) => {
    if (!dev || busy) return
    setBusy(true)
    try {
      const id = c.place_id ?? (c.registry_no ? await materialise(dev, c.registry_no) : null)
      if (id === null) throw new Error('這一筆沒有可用的編號。')
      let r = roundId
      // Proposing with nothing open opens one first — the person's intent is to put this place
      // forward, and making them press 「開一輪」 first is a step the product invented for itself.
      if (r === null) { r = (await openRound(dev)).roundId; setRoundId(r) }
      await propose(dev, r, id)
      setQ('')
      setHits([])
      setError('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }, [dev, roundId, busy])

  /* **The door check — `spec-conditional-routing.md` §1.** A typed `/round` used to end at a
     sentence with nowhere to go: true, and useless, because the thing the person needs is the
     device screen and the screen knew it. Now the screen sends them.

     Two facts, in order: no key → `/device`; key but this circle's preferences never seen →
     **One check, not two, since 2026-08-30.** This also sent a keyed device that had never seen
     偏好 to `/preferences`; that screen was removed (`spec-return-choice.md` §2) and the routing
     lost its middle step, so a key is the only question left. `replace`, never `href`, so the back
     arrow does not return to a screen that immediately bounces again.

     **In an effect, not during render.** A navigation started while React is rendering is a side
     effect in the render phase; under StrictMode's double invoke it fires twice, and it can run
     before the tree it belongs to is committed. One blank frame is the price and it is the right
     one — the alternative is a screen that flashes content the person is not entitled to. */
  useEffect(() => {
    if (dev) return
    /* **Home, never `/device`** (UX batch U1). The key screen is the operator's back door since
       2026-09-16; a person with no seat needs to hear that this device has no circle and where
       circles come from, and home is where both doors are. The flag is one-shot: home reads it
       once and clears it, so the sentence answers this bounce and no later visit. */
    try { sessionStorage.setItem('upto_no_seat', '1') } catch { /* storage off: home just shows no line */ }
    window.location.replace('/')
  }, [dev])

  /** **The row's state comes from the GET, never from what this device just tapped** (PS-4). A
   *  reload has to show the same chips, and the only thing that knows what is in force is the
   *  server (D25) — so this runs on mount and again after every accepted write. It is deliberately
   *  NOT on the stream: a preference emits no SSE event by design (§3.0), because in a circle of
   *  five the timing of an event is one guess from a name. */
  const readPrefs = useCallback(async (d: Device) => {
    try {
      setPrefs(await fetchPreferences(d))
    } catch (e) {
      setError((e as Error).message || '讀取失敗')
    }
  }, [])

  useEffect(() => { if (dev) void readPrefs(dev) }, [dev, readPrefs])

  /**
   * One tap on a type. **Turning one ON is always `persist: false`, with no toggle to change it**
   * — a type is short-term by ruling (owner 2026-08-28: 「這次不想吃甚麼例如火鍋，這是短期的」), so it lapses at
   * the nightly erasure like every other unkept row (D17 · H22). There is no new `kind` and no
   * per-round expiry; the wire is exactly what the preferences page was already sending.
   *
   * **Off posts `allow`, it does not delete.** Nothing in this product is deleted — an `allow` is
   * an appended row that ends the avoidance (`lib/preferences`'s own note). That is also the whole
   * migration for a category someone KEPT under the old page: it still shows on, and tapping it
   * off ends it (PS-8).
   *
   * **The `allow` that ends a row carries THAT ROW'S `persist`, not `false`** — spec amended
   * 2026-08-28 at the gate, where PS-7 caught it with a real kept 火鍋. An `allow` written
   * `persist: false` is itself deleted by the 05:00 erasure, and the kept `avoid` underneath it
   * survives the night — so the category is in force again by morning and the chip comes back on
   * its own. **A row that ends a kept row has to live as long as the row it ends.** The old page
   * did exactly this (`persist: keptCategories.has(c)`) and the shape was lost in the move here.
   *
   * `keptPersist` is READ from the GET's `persist` for the in-force row, never inferred: the
   * payload carries it per row, so there is nothing to compute and nothing to get wrong.
   */
  const tapCategory = useCallback(async (value: string, on: boolean, keptPersist: boolean) => {
    if (!dev) return
    setPending((p) => ({ ...p, [value]: !on }))
    try {
      await postPreference(dev, {
        kind: 'avoid_category', value,
        stance: on ? 'allow' : 'avoid',
        persist: on ? keptPersist : false,
      })
      await readPrefs(dev)
    } catch (e) {
      setError((e as Error).message || '寫入失敗')
    } finally {
      setPending((p) => { const { [value]: _drop, ...rest } = p; return rest })
    }
  }, [dev, readPrefs])

  useEffect(() => {
    const el = listRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const check = () => {
      // The content's own height (first child's top to last child's bottom), not the column's: the
      // column is stretched to the grid area while it does not fit, and would never shrink back.
      const kids = Array.from(el.children) as HTMLElement[]
      if (kids.length === 0) return
      const h = kids[kids.length - 1].getBoundingClientRect().bottom - kids[0].getBoundingClientRect().top
      const stuck = el.classList.contains('listFits') ? el : kids[0]
      const top = parseFloat(getComputedStyle(stuck).top) || 0
      setListFits(h <= window.innerHeight - top)
    }
    const ro = new ResizeObserver(check)
    ro.observe(el)
    for (const k of Array.from(el.children)) ro.observe(k)
    window.addEventListener('resize', check)
    check()
    return () => { ro.disconnect(); window.removeEventListener('resize', check) }
  }, [pool.length, rolls])

  if (!dev) return <main className="round" data-screen="round" />

  /** In force per the server, then this device's unconfirmed taps on top. */
  const avoided = new Set((prefs?.avoid_categories ?? []).map((a) => a.value))
  const chipOn = (c: string) => pending[c] ?? avoided.has(c)
  const catStat = new Map((prefs?.avoid_categories ?? []).map((a) => [a.value, a]))
  const anyOn = CATEGORIES.some(chipOn)
  /** The ticked count for the button's label. Server state plus this device's unconfirmed taps,
   *  the same source the chips draw from, so the label and the chips cannot disagree. */
  const anyCount = CATEGORIES.filter(chipOn).length

  /* **The waiting room** (spec): this seat, the two groups, and whether the host control shows. A
     seat that has left is in neither group — the round does not wait for it. */
  const mine = rolls.find((r) => r.member_id === me)
  const submitted = !!mine?.submitted && !mine.left
  const doneSeats = rolls.filter((r) => r.submitted && !r.left)
  const waitingSeats = rolls.filter((r) => !r.submitted && !r.left)
  const isHost = me !== null && me === host
  /** The seats the host may ask to leave: not yet submitted, and never the host's own. */
  const leavable = isHost ? waitingSeats.filter((r) => r.member_id !== me) : []
  const seatName = (r: Roll, i: number) => r.nickname || `座位 ${i + 1}`
  /** One seat row, in either group. Its index is its place in the round's seats, so a seat keeps
   *  the number it had when it moves from 還沒提交 to 已提交. */
  const seatRow = (r: Roll) => {
    const i = rolls.indexOf(r)
    return (
      <li key={r.member_id} className="seat" data-roll-seat={i + 1}
        data-roll-state={r.submitted ? 'submitted' : 'waiting'} data-counts={r.counts ? 'yes' : 'no'}>
        <span className="seatName" data-user-content>{seatName(r, i)}</span>
        {r.member_id === host && <span className="hostTag" data-part="host-tag">房主</span>}
      </li>
    )
  }

  if (removed) {
    return (
      <main className="round roundSingle" data-screen="round">
        {/* **Two lines, because a 401 cannot say why** (the reviewer's should on 4a54d82): the event
            knows the host asked; a dead key on reconnect could be that or anything else that ended
            the seat, so its line states only what is true in every case. */}
        {removed === 'removed'
          ? <p className="waitSlot" data-part="removed">房主請你離開了這個圈子。</p>
          : <p className="waitSlot" data-part="removed">這台裝置在這個圈子的座位已經不能用了。</p>}
      </main>
    )
  }

  if (leaving) {
    const target = leavable.find((r) => r.member_id === chosen) ?? null
    return (
      <main className="round roundSingle" data-screen="round">
        {/* **One screen: choose, then a primary that names the person** (spec §Host). Nothing is
            chosen when it opens, so one tap can never remove someone the host did not pick; the
            effect is stated (D20), because removing the last waiting seat starts everyone's reveal. */}
        <div className="confirmCard" data-part="leave-confirm">
          <h1 className="roundTitle dSerif">請誰離開這個圈子？</h1>
          <div className="choices" role="radiogroup" aria-label="請誰離開" data-part="leave-choices">
            {leavable.map((r) => (
              <label key={r.member_id} className="choice" data-user-content>
                <input type="radio" name="leave-who" checked={chosen === r.member_id}
                  onChange={() => setChosen(r.member_id)} />
                <span>{seatName(r, rolls.indexOf(r))}</span>
              </label>
            ))}
          </div>
          <p className="roundNote" data-part="leave-explain">離開後，這一輪不再等這個人；其他人都提交了，就會開獎。</p>
          {error && <p className="roundErr" data-part="round-error" role="alert">{error}</p>}
          <div className="confirmRow">
            {/* 取消 first: the primary's label grows from 請人離開 to 請{nickname}離開 when a seat is
                chosen, and on its left 取消 would have moved with it (the evaluator, on b802c64). */}
            <button type="button" className="secondary" data-part="leave-cancel"
              onClick={() => { setLeaving(false); setChosen(null); setError('') }}>取消</button>
            <button type="button" className="act" data-part="leave-go" data-primary
              disabled={target === null || busy}
              onClick={() => {
                if (!dev || target === null) return
                setBusy(true)
                void removeSeat(dev, target.member_id)
                  .then(() => { setLeaving(false); setChosen(null); setError('') })
                  .catch((x: Error) => setError(x.message))
                  .finally(() => setBusy(false))
              }}
            >
              {target ? `請${seatName(target, rolls.indexOf(target))}離開` : '請人離開'}
            </button>
          </div>
        </div>
      </main>
    )
  }


  return (
    <main className="round" data-screen="round">
      {/* **Two columns from 900 wide** (`spec-round-two-column-2026-10-09.md`, owner 「左邊輸入右邊顯示
          清單」, 49ade4e, built per the v7b preview, 44ac714). It reverses A1's one column, and A1's
          reason is answered rather than ignored: the right column is not an empty 600 px any more,
          it holds the list this round is made of. Three wrappers in the one-column order (input,
          list, tonight menu); the grid puts the first and the last on the left. */}
      <div className="roundInput" data-part="round-input">
      {lastMeal && (
        <p className="roundNote lastMeal" data-part="last-meal">
          上一餐：<span data-user-content>{lastMeal.name}</span> · <a href={`/reveal?round=${lastMeal.round}`}>看開獎 →</a>
        </p>
      )}
      <h1 className="roundTitle dSerif">這一餐</h1>
      {/* **「一人提一家」 was false and D110 made it checkably so** — the cap is three per person,
          stated on the home page and enforced at propose, and this line said one. Corrected to the
          ruled number rather than to a vaguer phrasing: a screen that softens a limit into 「幾家」
          cannot be compared against the home page's sentence.

          **「就擲」 is left alone and raised rather than changed.** D108 rules that the dice are
          *revealed* and not thrown — the seed is drawn at open and every pair derives from it — so
          「擲」 credits an action with producing a number that already existed, and so does the
          bar's 「擲骰」. The difference from the line above: D110 supplies the exact number, so that
          fix is determined; D108 forbids a phrasing without supplying the replacement, and which
          word replaces 擲 is a wording choice the evaluator gates. */}
      {/* **One rule line, not two** (`spec-round-diet-circle-2026-10-08.md` A2): the first view is
          budgeted to six pieces of our own text, and the cap and the pool rule are one fact about
          proposing. The cap stays ruled at three (D110, stated on the home page too); the second
          half is D70's pool rule — a place is one entry however many people proposed it, and a
          repeat proposal succeeds quietly, so without it the quiet 200 reads as "it counted again".
          It states the mechanism and stops (D20) — 「請不要重複提」 was rejected for advising.
          The cap's old separate line (A5's walkthrough asserted it by text) is folded in here, so
          that assert reads this part now. */}
      {/* **After submitting, the rule and the search give way to one line** set in their place, so
          the act button below keeps its position (owner: 「取消提交跟提交為何不用同一個位置就好」). The
          list is locked until the seat takes its submission back. */}
      {submitted ? (
        <p className="waitSlot" data-part="wait-line">你已經提交了。大家都提交就開獎。</p>
      ) : (<>
      <p className="roundNote" data-part="round-pool-rule">
        每人最多提三家。同一家不管幾個人提，都只算一份。
      </p>

      {/* **No visible 找一家店 label** (`spec-round-diet-circle-2026-10-08.md` A3): the placeholder
          names the act and says what to type, so a label above it was a second piece of text
          saying the same. The accessible name stays, as `aria-label`. */}
      <label className="roundSearch">
        <Input
          data-part="place-search"
          aria-label="找一家店"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="找一家店：打店名的一部分"
          autoComplete="off"
        />
      </label>
      </>)}

      {/* **The refusal sits directly under the control that was refused, above the results.**
          Driven on 2026-08-19 with the error below the list: a four-place proposal answered 409,
          and the sentence explaining it rendered at y 786 under a pinned bar whose top edge is 824
          — **half of the one thing the person needed to read, behind a bar, below ten search
          results they had just been told they could not use.** The list stays open on purpose (a
          refusal is not a reason to throw away a search), so the message cannot live after it.

          It is not cleared on the next keystroke either, and that is deliberate: the reason a
          proposal was refused is still true while the person types the next query, and a message
          that vanishes the moment they touch the keyboard is one they will meet again by trying
          the same thing. It clears when a proposal succeeds. */}
      {/* **The roll's refusal is suppressed exactly while `pool_swept` is explaining it** — one
          line for the roller (§2), and the API's own sentence whenever the event did not arrive,
          so a refusal is never silent. Every other error is untouched. */}
      {(error || (rollError && rollError.round !== swept ? rollError.message : null)) && (
        <p className="roundErr" data-part="round-error" role="alert">
          {error || rollError?.message}
        </p>
      )}
      {streamDown && (
        <p className="roundErr" data-part="stream-error" role="status">{streamDown}</p>
      )}

      {/* **A zero result says so; silence is only allowed while the question is still open.**
          Evaluator-ruled 2026-08-20 from the data-experience remit: typing 星巴克 rendered nothing
          at all, and a member could not tell *no match* from *broken* from *still loading*.

          **The three states are separated by `answered`, not by `hits.length`.** An empty box says
          nothing; a query whose request is in flight says nothing, which is correct — silence while
          the question is open is honest, and silence after it has been answered is the defect. Only
          a query the server has come back on, with nothing, gets the line.

          **D20: it states and never advises.** No 「試試別的關鍵字」, no suggested spelling, no
          next step — those are the screen telling a person what to do, which is the one thing this
          surface may not do. It reports what happened and stops.

          `data-shape` so the gate keys on structure rather than on the sentence, the same reasoning
          as `A2-G8-zero`: copy is ruled and re-ruled, and a test that greps for wording fails on a
          rewording that changed nothing about the shape. */}
      {/* **A search that got no answer is a fault, and is drawn as one.** Evaluator-ruled
          2026-08-20. `hot-ink` rather than muted, because a zero result is a normal outcome and a
          request that never came back is not — drawing the second in the calm register would
          misreport it exactly the way the silence did. Three facts, three shapes:
          zero-measured, zero-because-unanswered, zero-because-no-data.

          **One sentence, and no retry advice.** The typeahead retries on the next keystroke, so
          the recovery path is the member's very next natural act; writing it down would be the
          screen telling them what to do, which D20 forbids. */}
      {failed !== null && (
        <p className="roundFail" data-part="search-error" data-shape="error">
          搜尋沒有回應。
        </p>
      )}

      {answered !== null && answered.length > 0 && hits.length === 0 && (
        <p className="roundEmpty" data-part="search-empty" data-shape="empty">
          沒有店家對上「{answered}」。
        </p>
      )}

      {hits.length > 0 && (
        <ul className="hits" data-part="typeahead">
          {hits.map((c) => (
            <li key={c.registry_no ?? c.place_id} className="hit">
              <button type="button" disabled={busy} onClick={() => void add(c)}>
                {/* D92's composed name — sign, then address-derived, then registered. The API
                    composes it; nothing here re-derives a name, which is what keeps the format
                    the provenance. */}
                <span className="hitName" data-user-content>{c.name}</span>
                {c.district && <span className="hitWhere">{c.district}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* UX batch U5b — the search answers at most ten (`live.py`, `limit 10`), so a full list
          says so rather than letting ten read as all there is. A fact, not a hint (D20). */}
      {hits.length >= 10 && (
        <p className="roundNote" data-part="search-cap">只列出前 10 家。</p>
      )}

      {/* **The roll sits ABOVE the list since item 3** (frontend, 2026-10-08,
          `spec-round-diet-circle-2026-10-08.md`). Under the list, a ten-shop pool pushed it below
          the first view at both widths (`g_multi_device` MD-6: 0 primary on every device), so the
          one act of the screen was the one thing a full table could not see. Above, it is at the
          same place whatever the pool's length: the list's heading names what it rolls. */}
      {/* **The act, inline — owner-ruled 2026-08-20, option 乙.** The pinned BAR is retired. It sits
          directly under the pool it acts on: *these are the places · roll them*.

          **It moved above 這一輪的人 and the seed line on 2026-09-16** (the evaluator's amendment to
          `spec-round-two-columns-2026-09-16.md`, closing RA-5). Those two are status — who has
          looked, and the commitment that fixes the result — and status reads after the act. With six
          places pooled they had pushed 擲骰's top to 1071, past the fold the two-column ruling exists
          to keep it above.

          **The disabled state survives here and only here.** §4's rule that a disabled control is
          never filled still applies pre-pool: with fewer than two places there is nothing to roll,
          and a filled control would invite a press that does nothing. The old bar expressed this
          as a dashed top rule; with no bar there is no rule to dash, and §5 rule 1 now names the
          dashed box as an offender, so it is a bordered paper block instead. */}
      <div className="act-row">
        {/* **One button, one place, two states** (owner, spec §after). 提交 and its take-back are the
            same element with the same box; only the colours change, so the submitted state reads as
            done rather than as a second red call. No navigation on either response: `closed` moves
            every device to the reveal at once, and `submitted` moves names between the groups. */}
        <button
          type="button"
          className={submitted ? 'act actDone' : 'act'}
          data-part={submitted ? 'unsubmit' : 'submit'}
          data-primary
          disabled={submitted ? busy : roundId === null || pool.length < 2 || busy}
          onClick={() => {
            if (!dev || roundId === null) return
            setBusy(true)
            if (submitted) {
              void unsubmit(dev, roundId)
                .then(() => setError(''))
                .catch((x: Error) => setError(x.message))
                .finally(() => setBusy(false))
              return
            }
            /* **The submitter sees one line, not two** (spec §2, carried over from the roll). When
               the last submission finds every weight at zero, the refusal arrives as this device's
               409 and as `pool_swept` to every seat; the 409's text is held and suppressed while
               the event explains it, so one sentence has one owner. */
            void submit(dev, roundId)
              .then(() => setQ(''))
              .catch((x: Error) => setRollError({ round: roundId, message: x.message }))
              .finally(() => setBusy(false))
          }}
        >
          {submitted ? (<>
            <svg className="tick" viewBox="0 0 22 22" aria-hidden="true">
              <circle cx="11" cy="11" r="11" />
              <path d="M6 11.5l3.2 3.2L16 8" fill="none" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            已提交（按這裡收回）
          </>) : '提交'}
        </button>

      </div>


      </div>

      {/* The list column: what this round is made of. Sticky beside the input column, so it stays in
          view while a long search result list scrolls past on the left. */}
      <div ref={listRef} className={listFits ? 'roundList listFits' : 'roundList'} data-part="round-list">
        {/* 乙 §2 — **the pool arrives as ONE block, never per row.** A fifty-row list staggered per
            row is a loading spinner wearing a costume (the spec's words). It takes the step after
            the menu's cap, because it is the last thing on the screen in reading order. */}
        <section className="poolBlock arrive" style={arrive(ARRIVE_CAP)} data-part="pool">
          <h2 className="roundH dSerif">這一輪的名單</h2>
          {/* **The whole table is told, and the sentence names nobody** — owner-ruled 2026-08-30
              (「反饋訊息給所有玩家，直接說目前的所有人的偏好導致所有店家皆無法選中，請使用者提出更多店家」).
              「大家」 and 「加起來」 are the ruling's own shape: the veto is the sum of the table, not
              one person's, and at five people a sentence that narrowed it would be one guess from a
              name (§3.0).

              D20: the first sentence states what happened, the second states the condition for the
              next roll — 「請使用者提出更多店家」 said as a fact rather than as an instruction.

              **Browser copy, one owner.** The event carries a type and a round id and no text, so
              `tools/server_copy.py` has nothing new to cover and `test_web_surface`'s word list is
              this string's gate.

              At the top of the pool block, so it is read before the list it is about; 擲骰 stays
              enabled, because the fix is proposing another place and the act is not what is
              broken. */}
          {swept !== null && swept === roundId && (
            <p className="roundWarn" data-part="pool-vetoed">
              大家目前的偏好加起來，池子裡每一家都抽不到。要多幾家才擲得成。
            </p>
          )}
          {pool.length === 0 ? (
            <p className="roundNote">還沒有人提。</p>
          ) : pool.length === 1 ? (
            // **The reason lives beside the list, not behind a press.** The API refuses a one-place
            // roll with 「一家店不是決定，是通知。」 and that sentence teaches something; but a
            // control that is pressable only to be refused teaches it by wasting a tap. So the bar
            // disables below two and the arithmetic is stated here, where a person reading the list
            // is already looking. States, never advises (D20) — it says what the round needs, not
            // what anyone should do about it.
            <>
              <ul className="rows">
                {pool.map((p) => (
                  <li key={p.place_id} className="row" data-part="pool-row">
                    <span className="rowName" data-user-content>{p.name}</span>
                  </li>
                ))}
              </ul>
              <p className="roundNote" data-part="need-two">
                一輪至少要兩家店。一家店不是決定，是通知。
              </p>
            </>
          ) : (
            <ul className="rows">
              {pool.map((p) => (
                // No proposer, no count, no share — §3.0 and B1. The row is the place and nothing
                // else, and the reveal is where numbers are allowed to exist at all.
                <li key={p.place_id} className="row" data-part="pool-row">
                  <span className="rowName" data-user-content>{p.name}</span>
                </li>
              ))}
            </ul>
          )}
        </section>


        {/* ── D108 · the seats, and who the round is settled on ─────────────────────────────
            **Every seat is painted from the first frame, before anyone has tapped**, and a tap fills
            one rather than adding one. That is the evaluator's `RL-4`/`RL-5` requirement and it is
            also the honest shape: the people in this round are known, the outcome is already fixed,
            and the only thing missing is somebody looking.

            **「翻開」 and never 「擲」.** D108's copy constraint is that the dice are *revealed*, not
            thrown — the seed was drawn at open and every pair derives from it, so a member's tap
            discloses a number that already existed. Wording that credits the tap with producing it
            would be the animation problem in prose. (The decider's own line left /round on
            2026-10-09, when the round came to end in 提交.) */}
        {rolls.length > 0 && (
          <section className="seats" data-part="roll-list">
            {/* **Two groups, each a heading over names** (spec): the list costs two text nodes at any
                size, where a label per seat would cost one per person. Names only, never anyone's
                shops (owner: submitted / not only). The 房主 tag reads the same for every viewer. */}
            {/* The headings are written out, not mapped from an array: the display face is subset from
                the literal copy in elements set in it (`subset_fonts.py`), and an expression hides
                its characters from that derivation. */}
            <div className="seatGroup" data-part="seats-done">
              <h2 className="roundH dSerif">已提交</h2>
              <ul className="seatRows">{doneSeats.map(seatRow)}</ul>
            </div>
            <div className="seatGroup" data-part="seats-waiting">
              <h2 className="roundH dSerif">還沒提交</h2>
              <ul className="seatRows">{waitingSeats.map(seatRow)}</ul>
              {leavable.length > 0 && (
                <button type="button" className="secondary" data-part="ask-leave"
                  onClick={() => { setChosen(null); setError(''); setLeaving(true) }}>請人離開</button>
              )}
            </div>
          </section>
        )}
      </div>

      {/* The tonight menu and its warning: input, so the left column at ≥ 900, but AFTER the list in
          the DOM, which keeps the one-column order below 900 exactly as it was (the list before the
          menu). The grid places it under the input wrapper. */}
      <div className="roundTonight" data-part="round-tonight" hidden={submitted}>
        {/* ── 「這次不吃」 ─────────────────────────────────────────────────────────
            `spec-preference-split.md` §2, owner-ruled 2026-08-28: 「過敏原是長期的。但是，這次不想吃
            甚麼例如火鍋，這是短期的」. The long-term pair (預算, 不吃的食材) stays on 偏好; the ten
            types moved here, **before the search in reading order** — before a person looks for a place
            they say what tonight is not, so the stance is set while it is still cheap. **Since
            2026-09-16 that is expressed by the right column rather than by sitting above the search**
            (owner-ruled axis 1): the thirteen chips were pushing the screen's own act past the fold,
            so they stand beside it instead of before it. **Since 2026-10-08 the whole menu folds behind
            one button below 這一輪的人** (`spec-round-diet-circle-2026-10-08.md` A1): optional, and most
            rounds never touch it. Nothing inside it changed.

            **No keep toggle, and its absence is the ruling rather than an omission.** Every tap sends
            `persist: false`, so a type lapses at the nightly erasure. A member who kept one under the
            old page still sees it on; tapping it off posts `allow` and ends it. That is the whole
            migration — nothing backfills and nothing is deleted.

            **Same wire, same numbers.** No new `kind`, no per-round expiry, no engine change: D103's
            1/N discount reads exactly the row this row writes. Only where a hand lands moved. */}
        <button
          type="button"
          className="tonightToggle"
          data-part="tonight-toggle"
          aria-expanded={tonightOpen}
          aria-controls="tonight-block"
          onClick={() => setTonightOpen((o) => !o)}
        >
          {anyCount > 0 ? `這次不想吃的類別（已勾 ${anyCount}）` : '這次不想吃的類別'}
        </button>
        {/* Always mounted, hidden while closed, so `aria-controls` names an element that exists
            (reviewer, d92b978). The chips render only when open, as before. */}
        <section className="tonightBlock" id="tonight-block" hidden={!tonightOpen}>
        {tonightOpen && (<>
          {/* UX batch U5a — who it binds and what it does, the two questions the walk found a member
              could not answer. True to D103: one member's stance, a discount of that kind's places
              for this round, and never a removal (the place stays proposable and in the pool). */}
          <p className="roundNote" data-part="tonight-explain">
            只算你自己的選擇。勾了的類別，這一輪抽中的機會會變小，店還是留在名單上。
          </p>
          {/* **甲・菜單** (`spec-round-menu-2026-09-03.md` sec. 1, owner-ruled 軸一 over 牌面 and
              帳本): the wrapping row of thirteen buttons becomes a Taiwanese menu — mark · name ·
              leader dots · count, grouped under three section marks (sec. 2, 密度一).

              **The leader dots are the whole signature.** Without them each row is a list item and
              the page is a settings sheet; with them it is a menu, which is the thing this screen
              is pretending to be. They are `aria-hidden` and empty on purpose — a decorative span
              that a screen reader must not read out as anything.

              **Order is `CATEGORIES` and is never re-sorted.** Each section's list is a filter of
              it, so the API's closed order is the reading order and 其他 stays last. **Sorting by
              count would be advice** (D20) and is the one thing a menu of this shape invites. */}
          {MENU_SECTIONS.map(({ heading, Icon, values }) => (
            <Fragment key={heading}>
              {/* The icon is decorative and says nothing the heading beside it does not already say,
                  so it is `aria-hidden` with no label — a labelled one reads the same thing twice.
                  `strokeWidth` is lucide's own prop (1.7); `absoluteStrokeWidth` is deliberately not
                  passed, and the colour is inherited from the heading rather than set here. */}
              <h3 className="menuSection" data-part="tonight-section">
                <Icon size={18} strokeWidth={1.7} aria-hidden="true" />
                {heading}
              </h3>
              <ul className="menu" data-part="tonight-avoid">
                {values.map((c) => {
                  const on = chipOn(c)
                  return (
                    <li key={c}>
                      <button
                        type="button"
                        /* 乙 §2 — the row arrives at its own place in the menu's reading order.
                           **On the row, not on the `<li>`**: the row is what a person sees arrive,
                           and `.chip` is the box whose transform the gate measures. Once per mount,
                           so toggling a chip re-fires nothing (`YI-2`) — and the button answers a
                           press in the first frame, because opacity does not intercept clicks
                           (`YI-6`). */
                        className="chip arrive"
                        style={arrive(CHIP_STEP[c] ?? ARRIVE_CAP)}
                        data-part="tonight-chip"
                        data-on={on ? 'yes' : 'no'}
                        aria-pressed={on}
                        onClick={() => void tapCategory(c, on, catStat.get(c)?.persist ?? false)}
                      >
                        {/* **A second cue that is not colour** — `spec-chip-mark.md`, answering the
                            owner's critique. The on-state was an ink fill plus a 500→700 weight: a
                            fill inversion is a lightness change and survives colour-blindness, but
                            neither is a shape a person can name, and the product already has one —
                            the 偏好 rows' square. The same part, so a row reads as selected in the
                            vocabulary of the sheet the person just left (WCAG 1.4.1, and 1.4.11 for
                            the 3:1). **It is not replaced by an icon and it does not move**: 密度一
                            took the icon off the row, so this square is the row's only mark.

                            `aria-hidden`: `aria-pressed` on the button is the accessible state, and
                            a screen reader announcing a decorative box beside it would say the same
                            thing twice in two vocabularies. */}
                        <span className="mark" aria-hidden="true" />
                        <span className="n" data-part="tonight-chip-name">{c}</span>
                        <span className="lead" aria-hidden="true" />
                        {/* **Nothing follows the dots, and that is the ruling** — the owner
                            2026-09-11: 「有些數據不用特別給使用者，例如店家的數量，這是 SDE 需要知道的
                            資訊，使用者應該專注在產品體驗」 (`spec-weights-picture-2026-09-11.md` §1).
                            So `tonight-stat` is gone — with it the count, the percentage, and the
                            `data-shape` fork that chose between them. **The dots now run to the row's
                            end**, which is what they did before the menu spec folded a number into
                            them; `.lead`'s `flex: 1` needs no change to do it.

                            **What that fork protected is not lost, and this is the one thing to
                            check before reviving anything here.** A category no place carries yet
                            would have printed 「0 家會比較少中（0.0%）」, and a zero count reads as a
                            RESULT — *we looked and nothing needed excluding* — rather than as *we
                            have not measured this yet* (A2-G8-zero). With no count on the row there
                            is no zero to misread, and the honest bound is stated once for the whole
                            menu by `pref-category-coverage` below: 沒有分類的店，避開讀不到。
                            **A count coming back here brings that defect back with it.**

                            The numbers themselves are not deleted from the payload (§5) — they move
                            to the operator's reveal as bars, §3/§3a, which is the second commit. */}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </Fragment>
          ))}

          {/* §4's honesty requirement, moved with the types it describes. The number is the
              payload's and is never written here — it moved from about 6% to nearly 13% in one day,
              and a constant would have been false by the afternoon while still rendering. Shown once
              and only while something is on: with no stance set there is nothing for it to qualify. */}
          {anyOn && (
            <p className="roundNote" data-part="pref-category-coverage">
              沒有分類的店，避開讀不到。
            </p>
          )}

          {/* **A13's sentence, verbatim from the ruling (AD-9).** Everything else here reports
              numbers; this reports what the numbers MEAN, once, and says the part a member would
              otherwise have to infer — that the effect shrinks as the table fills. D20 holds: it
              states, it does not advise. */}
          {anyOn && (
            <p className="roundNote" data-part="pref-category-discount">
              避開的類型不會完全抽不到，只是比較少中；桌上人越多，影響越小。
            </p>
          )}

          {/* **Nothing renders when no chip is on.** No 「目前沒有避開任何類型」 — D20: the surface
              states, it does not reassure, and an empty row already says it. */}
        </>)}
        </section>
        {/* **D22's warning, and it is the only thing on this screen that reads as a caution.**
            `crossed` is READ, never computed: the server decides with `>`, so a member exactly on
            half is not warned, and a surface that computed it could compute it wrong.

            **It cannot fire at today's coverage and that is expected, not a bug** — `breadth.share`
            is capped by categorised coverage, so 0.5 is unreachable until the classifier passes
            half. Its never-rendering is not evidence that it works, and nothing here fakes coverage
            to make it appear (A2-G8b stays n/a).

            **The count left this sentence on 2026-09-11 and the warning did not**
            (`spec-weights-picture-2026-09-11.md` §2). The ruling took the engineering numbers off
            this screen; the evaluator's reading is that the denominator was the number and the
            warning is D22's protection, so the wording drops 「這個圈子提得出來的 N 家裡」 and keeps
            everything that makes it a caution. Same trigger, same `crossed` read, no figure —
            **removing the sentence itself would remove a protection, and that is the owner's word
            to give.** Every character is in the shipped body subset, so no font rebuild.

        **It sits outside the fold on purpose** (`spec-round-diet-circle-2026-10-08.md` A1): a caution
        that is protection must not be hidden by a closed disclosure. */}
        {prefs?.breadth.crossed && (
          <p className="roundWarn" data-part="tonight-breadth">
            你目前的選擇，已經讓超過一半的選項受影響。
          </p>
        )}
      </div>




    </main>
  )
}
