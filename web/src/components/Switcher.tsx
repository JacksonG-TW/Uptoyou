/**
 * Demo scaffolding — the top-level switcher, `[OPEN-2]` as ruled by the evaluator 2026-08-19 under
 * the owner's 「先捨棄手機，目前在趕進度，像 lawcidity 一樣有個 demo 網頁就好」.
 *
 * **This is not the product's navigation and it is built to be deleted.** One component, one
 * stylesheet block, one line in `main.tsx`. When the surface is aimed at a phone again the whole
 * question reopens, and the cost of reopening it should be removing this file rather than
 * untangling it from four screens. **After 乙 that promise is still kept**: the bar the inner
 * screens now wear is drawn in this file, and `Back` is imported by it rather than by `main.tsx`,
 * so the deletion is one import shorter than it was. One bar is fewer pieces than two — it must
 * not spread into the screens.
 *
 * **It sits in the masthead now, and the paragraph that argued for a fixed corner is spent**
 * (`spec-round-menu-2026-09-03.md` §3, owner-ruled 軸二 = 乙・報頭內, reversing ruling ⑥ of
 * 2026-08-20). That paragraph said a switcher in the masthead moves every object below it and
 * reddens `A0c`'s pixel diff. **Measured on candidate 5 before the change, it does not:** the
 * masthead is already a three-child wrapping flex row, and at 1440 brand + dateline + picker +
 * switcher + gaps is 785 of 1160 — one row, height unchanged, nothing below moves. The gate is
 * paid where it is actually charged, at ≤ 900, where the switcher takes its own row inside the
 * masthead and A0c does not read.
 *
 * **Two shapes, one component.** On the home the nav is a child of `.mast`. On every inner screen
 * `NavBar` below wraps it with `Back` in ONE slim fixed bar — replacing the two separate fixed
 * boxes that used to pin opposite corners. `--bar-h` in `switcher.css` is now one bar's height
 * rather than the taller of two, and `spec-inner-header.md`'s `main` offset is unchanged in shape.
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

import Back from './Back'

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

/**
 * The inner screens' single bar — `spec-round-menu-2026-09-03.md` §3, 乙・報頭內.
 *
 * **返回 left, the stops right, one 2 px ink rule under the lot.** It replaces `.backLink`'s
 * top-left box and `.switcher`'s top-right box, which read as two decisions pinned to opposite
 * corners of a screen they did not belong to. `Back`'s own behaviour is untouched — the referrer
 * still decides between `history.back()` and a real `<a href="/">`; this moves the box and nothing
 * inside it.
 *
 * **Fixed, and `--bar-h` is why that costs nothing.** `round.css` and `reveal.css` start `main` at
 * `--bar-h + 24`, derived from this bar's own tokens rather than measured off a screenshot, so a
 * bar that changes height moves the content with it by construction. Not rendered on the home:
 * there the nav is a child of the masthead and there is nowhere to go back to.
 */
export function NavBar() {
  return (
    <div className="navbar" data-part="nav-bar">
      <Back />
      <Switcher />
    </div>
  )
}
