import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { joinCircle } from '@/lib/selfserve'
import { remember } from '@/lib/round'
import SecretOnce from './SecretOnce'
import { KEY_NOTICE } from './copy'

/**
 * §4 — joining by the shared link, `/join#c=<circle_id>&t=<ticket>`.
 *
 * **The circle id and the ticket arrive as props, already read and already erased from the address
 * bar.** `readJoinFragment()` runs once in `main.tsx`'s `route()`, at module scope — the same place
 * and for the same reason the home's fall-through `replaceState` lives there rather than in an
 * effect. So this component never touches `window.location`, and there is no render in which the
 * ticket is still in the URL (`SS-9`).
 *
 * **Two steps, one component, no route between them** — the same reasoning as `Create`: a refresh
 * after the `201` loses a key the server cannot print again, and there is no recovery path until
 * tier 2 identity lands.
 *
 * **Nothing is created until the person names themself** (§4.1). A tap on a link is not consent to
 * join under a blank name, so `POST /join` is not sent on arrival — it waits for a nickname and an
 * explicit control.
 */
type Step = 'name' | 'key'

export default function Join({ circle, ticket }: { circle: string; ticket: string }) {
  const [step, setStep] = useState<Step>('name')
  const [nickname, setNickname] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [key, setKey] = useState('')

  const join = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const j = await joinCircle(circle, ticket, nickname.trim())
      /* Seated before the screen moves, exactly as `Create` does — a person who closes the tab on
         the key screen still has a working seat. */
      remember({ token: j.key, circle })
      setKey(j.key)
      setStep('key')
    } catch (e) {
      /* **The server's own sentence, immediately, with no arrival** (`SS-6`): 409 the circle is
         full, 410 the ticket was replaced, 404 no such ticket, 429 the daily ceiling. The words are
         backend's, in `server_copy.py`, and reach here as the response's `detail`.

         **No client-side seat cap anywhere** (§7): D110's cap is the server's and arrives as that
         409. A screen that counted seats and greyed out joining at ten would one day predict the
         rule wrongly and refuse a legal join. */
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="selfserve" data-screen="join" data-step={step}>
      {step === 'name' && (
        <>
          {/* **§4.1 asks the screen to NAME the circle, and it cannot: no payload carries a
              circle's name.** The name exists server-side in `issue.py` alone; A24's three
              endpoints return ids and secrets, and the only human-readable circle text any client
              ever receives is round-scoped. Rendering the id would be naming a number at somebody
              who was handed a link by a friend, and inventing a name would be worse. So the screen
              says what it can stand behind — that this link seats you — and the circle's name slots
              in here when a payload carries one. Raised with backend beside the seat-list gap. */}
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
      )}

      {step === 'key' && (
        /* §4.2 — **the identical §2b treatment**, which is why it is the same component rather than
           a second one that looks like it. The trap is the same trap one step removed: this key is
           this person's seat, and it is printed once. */
        <>
          <p className="eyebrow"><em>★</em>入座</p>
          <h1 className="ssTitle"><span>你進來了</span></h1>
          <SecretOnce
            part="joiner-key"
            label="你的鑰匙"
            secret={key}
            notice={KEY_NOTICE}
            continueLabel="繼續"
            onContinue={() => { window.location.href = '/round' }}
          />
        </>
      )}

      {error && <p className="ssErr" data-part="selfserve-error">{error}</p>}
    </main>
  )
}
