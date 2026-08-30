/**
 * Demo scaffolding — the top-level switcher, `[OPEN-2]` as ruled by the evaluator 2026-08-19 under
 * the owner's 「先捨棄手機，目前在趕進度，像 lawcidity 一樣有個 demo 網頁就好」.
 *
 * **This is not the product's navigation and it is built to be deleted.** One component, one
 * stylesheet block, one line in `main.tsx`. When the surface is aimed at a phone again the whole
 * question reopens, and the cost of reopening it should be removing this file rather than
 * untangling it from four screens.
 *
 * **Why it is `position: fixed` rather than sitting in the masthead, which is what the ruling
 * said.** The approved comparison page has no navigation, and `D101` makes that page the fidelity
 * target — the 1440 pixel diff is measured against it object by object. A switcher *in* or *above*
 * the masthead moves every object below it, and the gate that was just verified goes red the
 * moment it lands. Out of flow, it costs the diff only the pixels it covers, in a corner the
 * approved page leaves empty. Raised with the evaluator rather than done quietly; if they want it
 * in the masthead it is a two-line change and the fidelity gate pays for it.
 *
 * **Four destinations since 2026-08-30** (`spec-return-choice.md` §2): 偏好 was removed — with the
 * budget and the ingredient list gone it would have held one sentence about a choice made on
 * another screen, which is the anti-default list's own case — and a tab pointing at 這一餐 was
 * rejected as a tab that is another tab. The rule below is unchanged and is what allowed the
 * removal to be a deletion rather than a disabled stop.
 *
 * **The destinations, all of them built as of A4.** The rule that got them here stands and is
 * worth keeping: a stop appears when its screen exists, never before — a demo that walks a person
 * into a blank page is worse than a demo with fewer stops, which is §1a's argument that a disabled
 * control is still a door. The reveal is the one that still comes and goes, because it needs a
 * round to point at.
 */

/** The reveal needs a round to show. Rather than invent one, the entry carries the last round this
 *  browser actually opened — written by whatever screen last drove a roll — and hides itself until
 *  one exists. A demo link that 404s is worse than one that is not there yet. */
function lastRound(): string | null {
  // The round in the address bar wins over the remembered one. Without this the switcher renders
  // before the reveal's effect has recorded anything, so **the screen you are standing on is
  // missing from the switcher** — which reads as the switcher being broken rather than as a
  // one-tick race.
  const here = new URLSearchParams(window.location.search).get('round')
  if (here) return here
  return localStorage.getItem('upto_last_round')
}

type Stop = { href: string; label: string }

function stops(): Stop[] {
  const list: Stop[] = [
    { href: '/', label: '首頁' },
    { href: '/device', label: '裝置' },
    { href: '/round', label: '這一餐' },
  ]
  const round = lastRound()
  if (round) list.push({ href: `/reveal?round=${encodeURIComponent(round)}`, label: '開獎' })
  return list
}

export default function Switcher() {
  const here = window.location.pathname.replace(/\/+$/, '') || '/'
  return (
    <nav className="switcher" data-part="demo-switcher" aria-label="示範導覽">
      {stops().map((s) => (
        <a
          key={s.href}
          href={s.href}
          data-here={s.href.split('?')[0] === here ? 'yes' : 'no'}
          // A full page load, deliberately. There is no router and no history handling here —
          // the ruling said no routing library, and for three static destinations the browser's
          // own navigation is the whole feature.
        >
          {s.label}
        </a>
      ))}
    </nav>
  )
}
