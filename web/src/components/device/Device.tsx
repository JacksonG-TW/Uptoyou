import { useState } from 'react'
import { device, doorHref, remember, verify } from '@/lib/round'
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

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    const d = { token: token.trim(), circle: circle.trim() }
    try {
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
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <main className="device" data-screen="device">
      <h1 className="deviceTitle">貼上鑰匙</h1>
      <p className="deviceNote">
        鑰匙由開圈子的人給你，一支裝置一把。貼上之後這台裝置就是你的座位。
      </p>

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

      {existing && (
        <p className="deviceNote" data-part="device-seated">
          這台裝置目前已經坐在第 {existing.circle} 號圈子裡。再貼一次會換成新的鑰匙。
        </p>
      )}
    </main>
  )
}
