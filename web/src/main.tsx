import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { LazyMotion, domAnimation } from './lib/motion'
import './index.css'
import App from './App.tsx'
import Reveal from './components/reveal/Reveal.tsx'
import { NavBar } from './components/Switcher.tsx' // demo scaffolding — see the component
import DeviceScreen from './components/device/Device.tsx'
import Round from './components/round/Round.tsx'

/**
 * One path, one screen — read once at boot, with no router library.
 *
 * **Why not a router:** adding `react-router` is a stack decision with a real cost (a dependency,
 * a build-size line, a second way to express navigation) and it belongs to `[OPEN-2]` — the owner
 * is ruling how a person moves through five destinations, and picking the mechanism first would
 * quietly answer half of his question. Two paths need no library; five destinations may. **This is
 * the placeholder the ruling replaces, not the answer to it.**
 *
 * The proxy already serves `index.html` for any unmatched path (`try_files $uri $uri/ /index.html`),
 * so a path this file does not name reaches it anyway and falls through to the home.
 *
 * **`/preferences` is one of those now** (`spec-return-choice.md` §2, 2026-08-30): the screen was
 * removed, and a typed or bookmarked `/preferences` lands on the home rather than 404ing. That is
 * the fall-through below and not a redirect — a redirect would be a claim that the address moved
 * somewhere, and it did not; the thing it addressed is gone.
 *
 * **Nothing links here yet, deliberately.** The home screen is under A0c's fidelity gate — a pixel
 * diff against the owner-approved page — so an affordance added there would fail that gate before
 * the frame has been ruled.
 */
/** `/reveal?round=<id>` until the frame is ruled. **The round id is in the query rather than the
 *  path on purpose**: a path segment is a routing decision, and how a person arrives at a reveal is
 *  part of `[OPEN-2]`. A query parameter is the form that commits to nothing and is trivially
 *  replaced by whatever the ruling says. */
/**
 * **The home, and the address bar told so** (evaluator's note, 2026-08-30; held out of candidate 4
 * and shipped in 5).
 *
 * Every unmatched path falls through to the home — the proxy serves `index.html` for anything, so
 * `/preferences`, a typo or an old bookmark all land here. Until now the address bar kept saying
 * the path that no longer exists while the home rendered, which made three small things wrong at
 * once: the URL described a screen the person was not on, a refresh looked like it *might* go
 * somewhere else, and `Back` had an entry for a page that was never shown.
 *
 * `replaceState`, not `pushState` and not a redirect. **Not a redirect** because nothing moved —
 * a redirect claims the address has a new home, and `/preferences` does not; the screen is gone.
 * **Not `pushState`** because that would add the very history entry this removes.
 *
 * **Safe here, and only here.** `route()` is called once at module scope (`const screen = route()`
 * below), outside any component render — so this is not the render-phase side effect this codebase
 * bans in three other files, and StrictMode's double invoke cannot reach it. Moving this call into
 * a component would break that, which is why it is written beside the fall-through rather than in
 * an effect.
 */
function home() {
  if (window.location.pathname !== '/' || window.location.search) {
    window.history.replaceState(null, '', '/')
  }
  return <App />
}

function route() {
  const path = window.location.pathname.replace(/\/+$/, '')
  if (path === '/device') return <DeviceScreen />
  if (path === '/round') return <Round />
  if (path === '/reveal') {
    const round = Number(new URLSearchParams(window.location.search).get('round'))
    /* A `/reveal` with no usable round is a fall-through like any other, so it is rewritten too:
       `?round=abc` in the bar over a home screen is the same lie in a different sentence. */
    return Number.isFinite(round) && round > 0 ? <Reveal roundId={round} /> : home()
  }
  return home()
}

const screen = route()

/** The bar is on every screen except the home entry. Two reasons, and they were one before 乙:
 *  home is where 返回 goes, so a back control there is either a no-op or an exit from the product;
 *  and the home's own switcher is a child of the masthead now (`App.tsx`), not of this file. */
const atHome = window.location.pathname.replace(/\/+$/, '') === ''

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* `strict` refuses a `motion.*` component anywhere below it, which is what keeps the feature
        bundle to the half we budgeted for. See `lib/motion.ts`. */}
    <LazyMotion features={domAnimation} strict>
    {/* Demo scaffolding, ruled 2026-08-19; ONE bar since 乙 (`spec-round-menu-2026-09-03.md` §3).
        Removing it is this line plus the import plus the stylesheet import in `index.css` — still
        deliberately three deletions and no untangling, and one line shorter than it was, because
        `Back` is now imported by the bar rather than rendered beside it. The home's switcher is
        not here: it is a child of the masthead in `App.tsx`. */}
    {!atHome && <NavBar />}
    {screen}
    </LazyMotion>
  </StrictMode>,
)
