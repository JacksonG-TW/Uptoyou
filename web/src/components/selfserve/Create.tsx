import { useState } from 'react'
import { Input } from '@/components/ui/input'
import { createCircle, type Created } from '@/lib/selfserve'
import { remember } from '@/lib/round'
import InvitePanel from './InvitePanel'
import { NO_ACCOUNT } from './copy'

/**
 * §2 — creating a circle. **Three steps, and the order is the design**
 * (`spec-self-serve-2026-09-13.md`).
 *
 * **One component with internal steps, NOT three routes, and this protects a server guarantee with
 * a client decision.** A route change means a refresh is possible between the steps, and a refresh
 * after the `201` loses a key the server genuinely cannot print again — there is no recovery path
 * until tier 2 identity lands, so that key is gone and the seat with it. Steps in state cannot be
 * refreshed away by a tap on 返回 or a stray reload of an address that changed.
 *
 * **§3's rule — the key and the join link are NEVER on one screen — is now kept by there being no
 * key screen at all** (owner-ruled 2026-09-16, «the key leaves the member surface»; the evaluator's
 * `spec-key-off-the-member-surface-2026-09-16.md` §1). The danger it was written for is unchanged:
 * the key **is them**, the link **makes someone else a member**, they look alike, and the first
 * person to paste their own key into the group chat has given away their seat, which a re-issue
 * cannot undo. Showing the key was what created the chance to paste it; the creator never needs to
 * read it, because the device stores it.
 *
 * **The `201`'s secret is still written to this device the moment it arrives**, exactly as before —
 * A24's guarantee is untouched: the key is in `localStorage` and nowhere else, and no screen in this
 * flow renders it. What went is the step that showed it, and `SS-2`'s 「the key screen carries no
 * ticket」 becomes 「no member screen carries a key」.
 */
type Step = 'name' | 'circle'

export default function Create() {
  const [step, setStep] = useState<Step>('name')
  const [circleName, setCircleName] = useState('')
  const [nickname, setNickname] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [made, setMade] = useState<Created | null>(null)
  /** §5's re-issue replaces the link in place. Held separately from `made` so the original is not
   *  mutated — the person is looking at a link, and it changing under them is the one moment they
   *  need to be sure which one they now hold. */
  const [link, setLink] = useState('')

  const create = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const c = await createCircle(circleName.trim(), nickname.trim())
      /* **Seated before the screen moves**, and since the key step went this is the only place the
         secret is handled at all: a person who closes the tab still has a working seat on this
         device, and no second device can be seated. */
      remember({ token: c.key, circle: c.circleId })
      setMade(c)
      setLink(c.joinLink)
      /* Straight to the invite step: the link is already in hand from the `201`, and the key it also
         carried is on the device rather than on the screen. */
      setStep('circle')
    } catch (e) {
      /* §1's refused state: the server's sentence, immediately, below the control, **with no
         arrival** — 乙 §1a rule 5, a refusal that fades in has not refused anything yet. */
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="selfserve" data-screen="create" data-step={step}>
      {step === 'name' && (
        <>
          <p className="eyebrow"><em>★</em>開一個圈子</p>
          <h1 className="ssTitle"><span>取個名字</span><span className="lit">就可以開始</span></h1>
          <p className="ssLead">{NO_ACCOUNT}</p>

          {/* §2a — two fields and nothing else on the screen. */}
          <form
            className="ssForm"
            onSubmit={(e) => { e.preventDefault(); void create() }}
          >
            <label className="ssField">
              <span className="ssLabel">圈子的名字</span>
              <Input
                data-part="circle-name"
                value={circleName}
                onChange={(e) => setCircleName(e.target.value)}
                autoComplete="off"
              />
            </label>
            <label className="ssField">
              <span className="ssLabel">你的暱稱</span>
              {/* **No uniqueness check, here or anywhere** (§7). Two friends both typing 小明 is
                  legal and the server allows it; refusing a name because someone took it is the
                  administration the owner rejected. */}
              <Input
                data-part="creator-nickname"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                autoComplete="off"
              />
            </label>

            {/* **Un-pressable in place while building, and the layout does not move** (§1's
                states) — `disabled` on the control that is already there, never a swap for a
                spinner that occupies a different box. */}
            <button
              type="submit"
              className="act"
              data-part="create-submit"
              disabled={busy || !circleName.trim() || !nickname.trim()}
            >
              建立
            </button>
          </form>
        </>
      )}

      {step === 'circle' && made && (
        /* §2c. **No key is rendered anywhere in this branch** — the other half of `SS-2`. */
        <>
          <p className="eyebrow"><em>★</em>{circleName.trim()}</p>
          <h1 className="ssTitle"><span>找人進來</span></h1>

          {/* **Step 3 is one component, shared with the durable `/circle` route** (`SS-13`).
              The link is passed in because the `201` already handed it over — this flow must not
              ask for one, since asking mints a new ticket and revokes the one just shown. */}
          <InvitePanel
            device={{ token: made.key, circle: made.circleId }}
            link={link}
            onLink={setLink}
            creator
          />

          <a className="act" data-part="into-circle" href="/round">進去看看</a>
        </>
      )}

      {/* **One error region for every step, rendered where the control is.** No arrival, and it is
          never cleared by a timer: a refusal stays until the person does something else. */}
      {error && <p className="ssErr" data-part="selfserve-error">{error}</p>}
    </main>
  )
}
