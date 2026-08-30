import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { LazyMotion, domAnimation } from './lib/motion'
import './index.css'
import App from './App.tsx'
import Reveal from './components/reveal/Reveal.tsx'
import Switcher from './components/Switcher.tsx'   // demo scaffolding — see the component
import Back from './components/Back.tsx'           // demo scaffolding — owner-ruled 2026-08-19
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
function route() {
  const path = window.location.pathname.replace(/\/+$/, '')
  if (path === '/device') return <DeviceScreen />
  if (path === '/round') return <Round />
  if (path === '/reveal') {
    const round = Number(new URLSearchParams(window.location.search).get('round'))
    return Number.isFinite(round) && round > 0 ? <Reveal roundId={round} /> : <App />
  }
  return <App />
}

const screen = route()

/** Back is on every screen except the home entry — home is where back goes, so a back control
 *  there is either a no-op or an exit from the product. */
const atHome = window.location.pathname.replace(/\/+$/, '') === ''

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* `strict` refuses a `motion.*` component anywhere below it, which is what keeps the feature
        bundle to the half we budgeted for. See `lib/motion.ts`. */}
    <LazyMotion features={domAnimation} strict>
    {/* Demo scaffolding, ruled 2026-08-19. Removing it is this line plus the import plus the
        stylesheet import in `index.css` — deliberately three deletions and no untangling. */}
    <Switcher />
    {!atHome && <Back />}
    {screen}
    </LazyMotion>
  </StrictMode>,
)
