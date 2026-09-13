import { useCallback, useEffect, useState } from 'react'
import { Input } from '@/components/ui/input'
import { createCircle, fetchMembers, reissueJoinLink, type Created, type Members } from '@/lib/selfserve'
import { remember } from '@/lib/round'
import CopyRow from './CopyRow'
import SecretOnce from './SecretOnce'
import { KEY_NOTICE, LINK_LIFE, NO_ACCOUNT } from './copy'

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
 * **§3 — the load-bearing rule this file exists to enforce: the key and the join link are NEVER on
 * one screen.** The key **is them**; the link **makes someone else a member**; they look alike and
 * get pasted into different places, and **the first person who pastes their own key into the group
 * chat has given away their seat** — which a re-issue cannot undo, because re-issuing a ticket does
 * not un-give a key. So `step === 'key'` renders the key and no link, `step === 'circle'` renders
 * the link and no key. **A union-typed step rather than two booleans**: two booleans have a state
 * where both are true, and that state is the failure `SS-2` exists to catch.
 */
type Step = 'name' | 'key' | 'circle'

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
  /** §2c's seat list. `null` until it has been read once — **not an empty list**, because an empty
   *  list is a claim (「nobody is here」) and a missing one is not, and at this moment the creator
   *  is definitely in it (D112). */
  const [seats, setSeats] = useState<Members | null>(null)

  const readSeats = useCallback(async (c: Created) => {
    try {
      setSeats(await fetchMembers({ token: c.key, circle: c.circleId }))
    } catch {
      /* **A seat list that fails to load renders nothing rather than an error.** The act of this
         screen is the join link; the list is who is here so far. A refusal banner over a working
         invite would make a person think the link was broken. */
      setSeats(null)
    }
  }, [])

  /* Read on arrival at §2c and again after a re-issue — `SS-7` asserts the count did NOT move
     across that call, so the screen has to actually re-read rather than assume. */
  useEffect(() => {
    if (step === 'circle' && made) void readSeats(made)
  }, [step, made, readSeats])

  const create = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const c = await createCircle(circleName.trim(), nickname.trim())
      /* **Seated before the screen moves.** The key is written to this device the moment it
         arrives, so a person who closes the tab on the key screen still has a working seat — the
         thing they lose is the ability to seat a SECOND device, which is what the notice says. */
      remember({ token: c.key, circle: c.circleId })
      setMade(c)
      setLink(c.joinLink)
      setStep('key')
    } catch (e) {
      /* §1's refused state: the server's sentence, immediately, below the control, **with no
         arrival** — 乙 §1a rule 5, a refusal that fades in has not refused anything yet. */
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const reissue = async () => {
    if (busy || !made) return
    setBusy(true)
    setError('')
    try {
      setLink(await reissueJoinLink({ token: made.key, circle: made.circleId }))
      /* **Re-read rather than assume.** §5 says re-issuing ejects nobody and `SS-7` checks the
         count is unchanged — a screen that skipped this would be asserting the rule instead of
         showing it, and would keep showing a stale list if the rule ever broke. */
      void readSeats(made)
    } catch (e) {
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

      {step === 'key' && made && (
        /* §2b. **No join link is rendered anywhere in this branch** — that is half of `SS-2`, and
           it is why `made.joinLink` is not read here even though it is in hand. */
        <>
          <p className="eyebrow"><em>★</em>{made.circleId}</p>
          <h1 className="ssTitle"><span>圈子開好了</span></h1>
          <SecretOnce
            part="creator-key"
            label="你的鑰匙"
            secret={made.key}
            notice={KEY_NOTICE}
            continueLabel="繼續"
            onContinue={() => setStep('circle')}
          />
        </>
      )}

      {step === 'circle' && made && (
        /* §2c. **No key is rendered anywhere in this branch** — the other half of `SS-2`. */
        <>
          <p className="eyebrow"><em>★</em>{circleName.trim()}</p>
          <h1 className="ssTitle"><span>找人進來</span></h1>

          <CopyRow part="join-link" label="邀請連結" value={link} />
          <p className="ssLead">把這條連結貼給朋友，誰點誰就有座位。</p>
          {/* **Under the link, above the re-issue control** — the life of the link stated where the
              link is, and the fix the next thing the eye reaches. The control below is literally
              what the sentence's second half describes. */}
          <p className="ssNote" data-part="link-life">{LINK_LIFE}</p>

          {/* §5 — **one control, never two.** There is no standalone revoke: revoking alone leaves
              a circle nobody can join, and that is a state a worried person reaches by accident —
              they press the frightening button to shut a stranger out and their real friend's link
              dies with it. Whatever they press must leave them a link to share, so the action is
              「換一條新的連結」 and the consequence is stated beside it.

              **It ejects nobody and the copy does not imply that it does.** A sentence reading like
              removal gets pressed for the wrong reason, and then the stranger is still there. */}
          <button
            type="button"
            className="ssMinor"
            data-part="reissue"
            onClick={() => void reissue()}
            disabled={busy}
          >
            換一條新的連結
          </button>
          <p className="ssNote">舊的連結就不能用了，已經進來的人不受影響。</p>

          {/* **§2c's seat list is NOT here, and the hole is deliberate.** It needs a read of the
              circle's seats and **no such endpoint exists** — A24's three return
              `{circle_id, member_id, key, join_link}`, `{member_id, key}` and `{join_link}`, and
              the only nicknames any payload carries today are round-scoped (`rolls[]`,
              `trip.nickname`). The two things I could have done alone are both worse than the
              hole: render the creator's row from the nickname they just typed — which looks right,
              never updates, and makes `SS-8` unmeasurable while appearing to pass — or drop it
              silently. Raised with backend; it slots in here and needs no other change. */}

          {/* §2c's seat list. **`cap` comes from the payload, never from the markup** — it is
              `issue.SEAT_CAP`, it has moved once already, and a client that writes 10 here will one
              day disagree with the server about D110.

              **No client-side cap anywhere** (§7): this counts, it does not gate. Nothing here
              greys out, warns near ten, or predicts the 409 — a client that guesses the rule will
              eventually guess it wrong and refuse a legal join.

              **Duplicates render as the server has them** (§7, `SS-8`): no marker, no 「(2)」, no
              disambiguation. Two 小明 are two rows that read the same, which is what the server
              holds and what the owner ruled legal. The React key is the index for exactly that
              reason — the nickname is not unique and must not be treated as an identity. */}
          {seats && (
            <div className="ssSeats" data-part="seat-list">
              <p className="copyLabel">
                這個圈子裡的人 <span className="ssCount" data-part="seat-count">{seats.seats}/{seats.cap}</span>
              </p>
              <ul>
                {seats.members.map((m, i) => (
                  <li key={i} data-part="seat-row">{m.nickname}</li>
                ))}
              </ul>
            </div>
          )}

          <a className="act" data-part="into-circle" href="/round">進去看看</a>
        </>
      )}

      {/* **One error region for every step, rendered where the control is.** No arrival, and it is
          never cleared by a timer: a refusal stays until the person does something else. */}
      {error && <p className="ssErr" data-part="selfserve-error">{error}</p>}
    </main>
  )
}
