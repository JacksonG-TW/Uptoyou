import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { joinCircle } from '@/lib/selfserve'
import { remember } from '@/lib/round'

/**
 * §4 — joining by the shared link, `/join#c=<circle_id>&t=<ticket>`.
 *
 * **The circle id and the ticket arrive as props, already read and already erased from the address
 * bar.** `readJoinFragment()` runs once in `main.tsx`'s `route()`, at module scope — the same place
 * and for the same reason the home's fall-through `replaceState` lives there rather than in an
 * effect. So this component never touches `window.location`, and there is no render in which the
 * ticket is still in the URL (`SS-9`).
 *
 * **One step since 2026-09-16** (owner-ruled, «the key leaves the member surface», e0ff214; the
 * evaluator's `spec-key-off-the-member-surface-2026-09-16.md` §4). The screen after 加入 showed this
 * seat's own key, printed once, exactly as the creator's did — and it is gone for the same reason:
 * the key and the join link look alike, they get pasted into different places, and **a person who
 * pastes their own key into the group chat has given away their seat**, which nothing can undo. The
 * seat is stored on the `201` and the friend lands on 這一餐. No member screen shows a key anywhere,
 * which is the whole ruling and what `SK-3` proves.
 *
 * **A24's localStorage guarantee is unchanged**: the secret is written to this device and to nothing
 * else, and it is never rendered.
 *
 * **Nothing is created until the person names themself** (§4.1). A tap on a link is not consent to
 * join under a blank name, so `POST /join` is not sent on arrival — it waits for a nickname and an
 * explicit control.
 */
export default function Join({ circle, ticket }: { circle: string; ticket: string }) {
  const [nickname, setNickname] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const join = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const j = await joinCircle(circle, ticket, nickname.trim())
      /* Seated before the screen moves, exactly as `Create` does. **A full navigation rather than a
         step**, because the seat this person now holds belongs to 這一餐 and there is no longer a
         screen of our own between the two. */
      remember({ token: j.key, circle })
      window.location.href = '/round'
    } catch (e) {
      /* **The server's own sentence, immediately, with no arrival** (`SS-6`): 409 the circle is
         full, 410 the ticket is no longer usable, 404 no such ticket, 429 the daily ceiling. The
         words are backend's and reach here as the response's `detail`.

         **410 covers two facts since the owner ruled expiry** (2026-09-13, 「最多 1 小時就過期」):
         re-issued, or older than an hour. This screen does not distinguish them and must not try —
         it renders what the server said. The creator's fix for a friend who was late is the
         re-issue control that already exists.

         **No client-side seat cap anywhere** (§7): D110's cap is the server's and arrives as that
         409. A screen that counted seats and greyed out joining at ten would one day predict the
         rule wrongly and refuse a legal join. */
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="selfserve" data-screen="join" data-step="name">
      <>
          {/* **The screen does NOT name the circle, and that is settled rather than pending.**
              §4.1 originally asked it to. I reported that no payload carries a circle's name — it
              exists server-side in `issue.py` alone — and **the evaluator withdrew the requirement
              on a better reason than mine** (2026-09-13): resolving a ticket to a name would make a
              small oracle, so **a leaked ticket would yield the circle's name without joining**.
              The name is user-typed and authenticates nothing, and this screen already says what
              will happen.

              **So this is not a hole waiting for an endpoint.** My first note here said the name
              「slots in when a payload carries one」, which would have invited exactly the endpoint
              the withdrawal exists to prevent — and whoever built it would have met my half of the
              reasoning and not the evaluator's. */}
          <p className="eyebrow"><em>★</em>入座</p>
          <h1 className="ssTitle"><span>有人邀你</span><span className="lit">一起吃飯</span></h1>
          <p className="ssLead">用這條連結進來，你會有自己的座位。</p>

          <form className="ssForm" onSubmit={(e) => { e.preventDefault(); void join() }}>
            <label className="ssField">
              <span className="ssLabel">你的暱稱</span>
              {/* **No uniqueness check** (§7): two friends both typing 小明 is legal, the server
                  allows it, and the screen adds no marker and no 「(2)」. */}
              <Input
                data-part="joiner-nickname"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                autoComplete="off"
              />
            </label>
            <button
              type="submit"
              className="act"
              data-part="join-submit"
              disabled={busy || !nickname.trim()}
            >
              加入
            </button>
          </form>
      </>

      {error && <p className="ssErr" data-part="selfserve-error">{error}</p>}
    </main>
  )
}
