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
    <main className="selfserve" data-screen="join" data-step={step}>
      {step === 'name' && (
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
