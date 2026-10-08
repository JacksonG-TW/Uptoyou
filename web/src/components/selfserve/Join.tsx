import { useEffect, useState } from 'react'
import { Input } from '@/components/ui/input'
import { joinCircle, leaveCircle, previewJoin, type JoinPreview } from '@/lib/selfserve'
import { device, remember } from '@/lib/device'
import { REPLACE_NOTICE } from './copy'

/**
 * §4 — joining by the shared link, `/join#c=<circle_id>&t=<ticket>`.
 *
 * **The circle id and the ticket arrive as props, already read and already erased from the address
 * bar.** `readFragmentSecret('t')` runs once in `main.tsx`'s `route()`, at module scope — the same place
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
  const [seated] = useState(() => device() !== null)
  /** **Already in THIS circle** — typically the creator tapping their own link to check it (the
   *  reviewer's catch on 0de0aaa). Joining would mint a second seat here and leave the first,
   *  taking its invite power with it, so the form is not offered: the line says where the device
   *  already is and links to it. Read once at mount, like `seated`. */
  const [here] = useState(() => device()?.circle === circle)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  /** `null` while the preview is in flight: the form waits for it, so a dead link is said before
   *  anyone types a nickname into it (walk item 8). */
  const [preview, setPreview] = useState<JoinPreview | null>(null)

  useEffect(() => {
    let live = true
    void previewJoin(circle, ticket).then((p) => { if (live) setPreview(p) })
    return () => { live = false }
  }, [circle, ticket])

  const join = async () => {
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const j = await joinCircle(circle, ticket, nickname.trim())
      /* Seated before the screen moves, exactly as `Create` does. **A full navigation rather than a
         step**, because the seat this person now holds belongs to 這一餐 and there is no longer a
         screen of our own between the two. */
      // The seat this device held until now, read before the new key replaces it (one device,
      // one circle), then given back once the new one is safe (`leaveCircle`).
      const old = device()
      remember({ token: j.key, circle })
      if (old) leaveCircle(old)
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
          {/* **The screen names the circle and its creator — frontend's decision of 2026-10-07**,
              after the evaluator's input and with the owner's delegation; the reasoning, its cost
              and the rejected 2026-09-13 branch (a leaked ticket yields the name without a trace)
              are in `spec-ux-batch-2026-10-07.md`. Only a live ticket gets a name. The creator is
              the honest «inviter» because a ticket does not record who passed it on, and with the
              creator's seat gone the line says 有人 rather than a blank. */}
          <p className="eyebrow"><em>★</em>入座</p>
          {preview?.kind === 'live' ? (
            <h1 className="ssInvite" data-part="join-invite">
              <span>{preview.creator ?? '有人'} 邀你加入</span>
              <span className="lit ssCircle">「{preview.circleName}」</span>
            </h1>
          ) : (
            <h1 className="ssTitle"><span>有人邀你</span><span className="lit">一起吃飯</span></h1>
          )}
          {/* U9 — what the product is, for a link opened from a chat with no context. */}
          <p className="ssLead">大家各自提想吃的店，最後用骰子決定這一餐吃哪家。用這條連結進來，你會有自己的座位。</p>

          {/* A dead link is said on open and the form is not drawn: every dead case is one answer
              from the server, so this is its one sentence, verbatim. */}
          {here && (
            <p className="ssNote" data-part="join-already-here">
              這台裝置已經在這個圈子裡。<a href="/round">到這一餐 →</a>
            </p>
          )}
          {!here && preview?.kind === 'dead' && (
            <p className="ssErr" data-part="join-dead" role="alert">{preview.message}</p>
          )}
          {!here && preview !== null && preview.kind !== 'dead' && (
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
            {/* One device, one circle (owner ruling (b), 2026-10-07): said before the act, only
                when there is a seat to lose. `device()` is read at render — one local fact, no
                request. */}
            {seated && (
              <p className="ssNote" data-part="replace-notice">{REPLACE_NOTICE}</p>
            )}
            <button
              type="submit"
              className="act"
              data-part="join-submit"
              disabled={busy || !nickname.trim()}
            >
              加入
            </button>
          </form>
          )}
      </>

      {error && <p className="ssErr" data-part="selfserve-error" role="alert">{error}</p>}
    </main>
  )
}
