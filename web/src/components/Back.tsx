/**
 * Demo scaffolding — the back affordance. Owner-ruled 2026-08-19: 「不,demo也需要返回鍵,像是POC
 * 那種等級」 and 「該做的還是要做完」, overriding the evaluator's earlier *no back affordance*.
 *
 * **It returns the person to where they came from, not to a hardcoded home**, which is the part of
 * the ruling that costs anything. `history.back()` is the whole mechanism — the browser already
 * holds the answer, and every alternative (a `from=` query parameter, a remembered stack in
 * `localStorage`, a routing library) is a second copy of a fact the platform is already keeping
 * correctly. A second copy is how the arrow starts lying about where you were.
 *
 * **The one case `history.back()` gets wrong is arriving cold** — a pasted URL, a new tab, the
 * evaluator's harness opening a screen directly. There is no previous page inside this app, so
 * `back()` would leave it entirely, which for a demo means walking the audience out of the
 * product. So the referrer decides: same origin means there is somewhere of ours to go back to;
 * anything else falls back to the home entry, as a real link, so it works with middle-click and
 * shows its destination in the status bar.
 *
 * **Not on the home entry.** Home is where back goes; a back control there is either a no-op or an
 * exit. `main.tsx` decides that by not rendering this component on `/`.
 *
 * Deletes with the switcher: one component, one block in `switcher.css`, one line in `main.tsx`.
 */

function sameOriginReferrer(): boolean {
  try {
    return Boolean(document.referrer) && new URL(document.referrer).origin === window.location.origin
  } catch {
    // A malformed referrer is not a crash: treat it as "arrived cold" and use the link.
    return false
  }
}

export default function Back() {
  const canGoBack = sameOriginReferrer() && window.history.length > 1

  if (canGoBack) {
    return (
      <button
        type="button"
        className="backLink"
        data-part="back"
        data-budget-exempt="nav"
        onClick={() => window.history.back()}
      >
        <span aria-hidden="true">←</span> 返回
      </button>
    )
  }
  return (
    <a className="backLink" data-part="back" data-budget-exempt="nav" href="/">
      <span aria-hidden="true">←</span> 返回
    </a>
  )
}
