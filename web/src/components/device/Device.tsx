import { useCallback, useEffect, useState } from 'react'
import { device, doorHref, remember, verify, type Device } from '@/lib/round'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

/**
 * A4 — the device screen. The one place a person types, and the only place they may.
 *
 * **D38's *choices are picked from a fixed list, never typed* does not reach here, and the reason
 * is worth stating so nobody "fixes" it.** D38 governs *preferences* — the things a model would
 * otherwise have to interpret. A device secret is a credential: it has exactly one correct value,
 * the operator issued it, and there is nothing to interpret. A closed list of secrets is not a
 * thing.
 *
 * **The key is never shown back and never logged.** It goes to `localStorage` because that is what
 * makes the browser a seat in the circle across visits, and it leaves this component in an
 * `Authorization` header and nowhere else.
 */
export default function DeviceScreen() {
  const existing = device()
  const [token, setToken] = useState('')
  const [circle, setCircle] = useState(existing?.circle ?? '')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  /**
   * **The one path a credential takes into this browser.** Two ways in reach this screen now — the
   * pasted pair below and A20's invite fragment — and they share this function rather than each
   * carrying their own copy of the three steps.
   *
   * **That sharing is the requirement, not a tidiness preference.** A20's `Done =` says the link
   * must store *exactly* what the form would have stored and nothing more; two call sites written
   * separately are how one of them quietly grows a fourth step, or drops the check, and the two
   * ways of arriving start disagreeing about whether a key was ever tested. The rejected shape was
   * a second `verify`/`remember` pair inside the effect, which reads fine on the day it is written
   * and diverges on the day one of them is amended.
   */
  const join = useCallback(async (d: Device) => {
    // **Verified before it is stored.** Storing first and discovering later would leave the
    // browser holding a key that does not work, and every screen after this one would fail in
    // its own words instead of in this one's — which is where the person can actually act.
    await verify(d)
    remember(d)
    /* **Forward, not home** (`spec-conditional-routing.md` §1). Landing back on the home after a
       successful paste made the person press the same act again to learn where they were being
       sent; the key check has just answered that question, so the screen answers it.

       `remember` has already cleared the stamp if this key is for a different circle, so
       `doorHref()` reads the post-paste truth: `/preferences` on a circle this device has not
       been through, `/round` on one it has.

       **`replace`, not `href`** — the back arrow must not return to a device screen that would
       bounce a now-keyed person straight out again (§1's closing rule, D107's back affordance). */
    window.location.replace(doorHref())
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await join({ token: token.trim(), circle: circle.trim() })
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  /**
   * A20 — the invite link. `<origin>/device#c=<circle_id>&k=<token>`, one tap instead of reading a
   * key out loud across a table.
   *
   * **The credential rides in the fragment, and the fragment is the entire reason the ticket
   * exists.** It is the one part of a URL a browser never puts on the wire — not in the request
   * line, not in `Referer` — so it reaches neither the proxy's access log nor the api's. A query
   * string (`?k=`, `?token=`) would have been marginally easier to read here and is refused
   * outright: it writes the secret into two logs and the history entry before this component has
   * rendered its first frame, and no amount of clearing afterwards takes it back out of a log.
   *
   * **In an effect, never during render** — the same rule the preference screen's door check
   * states. This writes `localStorage`, rewrites history and then navigates; StrictMode
   * double-invokes render, so a render-phase version would do all three twice.
   *
   * **The fragment is dropped FIRST, before `verify` is even asked.** The rejected order is the
   * ticket's own phrasing — store, then replace — which leaves the secret sitting in the address
   * bar for the whole round-trip of the check, and leaves it there permanently when the key is
   * bad, which is precisely the case where the person turns the screen round to show someone.
   * Dropping it first is also what makes StrictMode's second invoke harmless: by then there is no
   * fragment left to read, so the key is checked once rather than twice.
   *
   * **A fragment that is not both `c` and `k` is an ordinary visit, not an error.** Junk, half a
   * link, a bare `#` — the parse is wrapped, nothing is stored, nothing is said, and the empty
   * form below renders with the behaviour and the message it always had. A key that parses but
   * does not work falls into the same `catch` the paste path uses, so a rejection reads
   * identically whichever way the person arrived.
   */
  useEffect(() => {
    let invited: Device | null = null
    try {
      /* `URLSearchParams` on the hash minus its `#`, never a hand-rolled split: the fragment
         carries an operator-issued token, and percent-encoding, empty values and repeated keys are
         exactly the cases a hand-rolled parser gets wrong on the one input that matters. */
      const fragment = new URLSearchParams(window.location.hash.replace(/^#/, ''))
      const c = (fragment.get('c') ?? '').trim()
      const k = (fragment.get('k') ?? '').trim()
      if (c && k) invited = { token: k, circle: c }
    } catch {
      /* A hostile or undecodable fragment must not take the screen down — a blank screen is the
         one outcome A20 names as unacceptable. There is nothing to recover and nothing worth
         telling the person: they get the form, which is where this visit was heading anyway. */
      invited = null
    }
    if (!invited) return

    /* Path and query kept exactly as they are; only the fragment goes. `replaceState`, not
       `pushState`: the link's own entry is the one that has to be overwritten, because a back
       arrow that could walk onto a URL still carrying the key would put the secret back in the
       address bar after we had taken it out. */
    window.history.replaceState(null, '', window.location.pathname + window.location.search)

    /* Held in a `const` because the narrowing above does not survive into the closure, and because
       nothing from here on may read the fragment again — it is gone. The pair never reaches state,
       so the key is not rendered back into the password field and cannot appear in a screen share
       for the same reason the field is `type="password"`. */
    const d = invited
    setBusy(true)
    setError('')
    void (async () => {
      try {
        await join(d)
      } catch (err) {
        setError((err as Error).message)
        setBusy(false)
      }
    })()
  }, [join])

  return (
    <main className="device" data-screen="device">
      {/* 丙・只動排版 (`spec-device-typeset.md`, owner-ruled 2026-08-26 from the rendered
          three-way). **Nothing is added that was not already on the screen** — the eyebrow is the
          one new element and it carries one word. The parts are set the way the home sets its own,
          so the two doors read as one building. */}
      <p className="eyebrow"><em>★</em>入座</p>
      {/* **Two lines, and the second is the sentence the note used to end with** (§3's copy
          accounting: every clause of the old note survives somewhere). Serif 900 — the display
          face, the same one the home's headline uses. */}
      <h1 className="deviceTitle">
        <span>貼上鑰匙</span><span className="lit">這台裝置就是你的座位</span>
      </h1>
      <p className="deviceLead">鑰匙由開圈子的人給你。</p>

      <form className="deviceForm" onSubmit={(e) => void submit(e)}>
        <label className="deviceField">
          <span>圈子編號</span>
          <Input
            data-part="circle-field"
            value={circle}
            onChange={(e) => setCircle(e.target.value)}
            inputMode="numeric"
            autoComplete="off"
            required
          />
        </label>

        <label className="deviceField">
          <span>鑰匙</span>
          {/* `type="password"` so a key pasted in a room with other people is not readable over a
              shoulder or in a screen share — this screen exists to be used in front of the circle. */}
          <Input
            data-part="token-field"
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            autoComplete="off"
            required
          />
        </label>

        {error && <p className="deviceErr" data-part="device-error">{error}</p>}

        <Button type="submit" data-part="device-submit" disabled={busy}>
          {busy ? '確認中…' : '確認'}
        </Button>
      </form>

      {/* The other two clauses of the old note, plus two statements D74 already makes: the token
          is printed once by `python -m upto.issue` and never stored, and re-pasting replaces the
          key (the seated note below has always said so). No advising word — D20. */}
      <p className="deviceFacts">
        <span className="eyebrow">一支裝置一把</span>
        <span className="eyebrow">只顯示一次</span>
        <span className="eyebrow">再貼一次就換鑰匙</span>
      </p>

      {existing && (
        <p className="deviceNote" data-part="device-seated">
          這台裝置目前已經坐在第 {existing.circle} 號圈子裡。再貼一次會換成新的鑰匙。
        </p>
      )}
    </main>
  )
}
