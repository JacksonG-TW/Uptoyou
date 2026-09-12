# design.md — the grounding file for this surface

**Read this before writing any component in `app/web/`.** It holds the tokens, the type ladder, the
named parts and the rules that bind every screen. A build spec references parts from here **by
name** and adds only what is specific to its screen, so the job is composition, not invention.

**Stack, from `D104`:** Vite · React 19 · Tailwind 4 · shadcn/ui, built into the proxy image.
`D3`'s no-build-step rule is superseded.

**This file is derived.** It carries parts and numbers, not arguments; the reasoning lives in the
decision record under the D-number stamped on each section. **When a decision is amended, the
decision is amended first and this file follows** — if the two disagree, this file is the stale one.

---

## 0 · The one thing to understand before installing anything

**shadcn/ui's defaults are the look this project already rejected once.** Rounded corners, soft
shadows, muted grays, a single low-contrast accent — that is the house style of every AI-built
interface, and it is what the four-round loop produced and the owner threw out.

> **shadcn is adopted for its behaviour, not its appearance.** Take the accessibility, the keyboard
> handling, the focus management, the composition. **Restyle every part to the tokens below before
> it renders once.** A part that ships with its default skin is a defect, not a starting point.

**Concretely: `--radius` is `0`, there are no shadows except the hard offset in §3, and the palette
is replaced wholesale.** If a component looks like the shadcn documentation, it is wrong.

---

## 1 · Colour — Tailwind tokens

**There is one colour scheme. Light.** Owner-ruled 2026-08-18 — see the box at the end of this
section before adding a dark variant of anything.

Declared once as CSS custom properties and exposed to Tailwind via `@theme`. **Do not introduce a
colour outside this table, and never pick an on-colour by eye** — every `on-*` is whichever of
ink/paper measured higher on that ground.

| token | Tailwind | value |
|---|---|---|
| ink | `--color-ink` | `#101114` |
| paper | `--color-paper` | `#FFFDF7` |
| muted | `--color-muted` | `#5A5C63` |
| hot | `--color-hot` | `#FF875C` |
| hot-ink | `--color-hot-ink` | `#D95204` |
| cobalt | `--color-cobalt` | `#2547E8` |
| jade | `--color-jade` | `#00A870` |
| sun | `--color-sun` | `#FFC300` |

**On-colours:** `on-hot` `on-jade` `on-sun` = `#101114`; `on-cobalt` = `#FFFDF7`.

**`hot` is a GROUND. `hot-ink` is the same accent as TEXT or a MARK. They are not interchangeable**
— owner-ruled 2026-08-18, the reference demo's orange:

| use | token | measured | floor |
|---|---|---|---|
| pinned bar, badge fill, the count tag — ground with ink on it | `hot` `#FF875C` | **7.98** | 4.5 |
| the headline's second line — large text on paper | `hot-ink` `#D95204` | **4.00** | 3.0 |
| **focus ring, the star, any mark on paper** | `hot-ink` | **4.00** | 3.0 |
| ~~`hot` used as text or a mark on paper~~ | — | **2.33** | **fails** |

**The focus ring must take `hot-ink`.** On `hot` it is 2.33 against a 3.0 graphic floor, and **no
visual review can catch that** — a focus ring only exists while something is tabbed to.

**The reference itself fails this pair**: its display headline sets that orange on cream at 2.33.
We take its colour and not its mistake.

### The flood — the landed reveal's ground

| face | ground | on-flood |
|---|---|---|
| hot | `#FF875C` | `#101114` |
| cobalt | `#2547E8` | `#FFFDF7` |
| jade | `#00A870` | `#101114` |
| sun | `#FFC300` | `#101114` |

**The four `flood-*` tokens stay separate even though they now hold the same values as the
accents.** They are different facts that happen to coincide: `hot` is the accent, `flood-hot` is the
ground the entire viewport takes when the hot face wins. **Today is the proof.** The owner changed
the accent from red to orange; had the two been one token, the reveal's flood — the product's
signature moment — would have changed silently as a side effect of a decision about a button. **The
same argument that keeps `pipred` separate keeps these four.** Collapsing them is a design ruling,
not tidying.

### The die is an object, not a surface

`pip #101114` · `pipred #FF4438` · `diefill #FFFDF7` · `dieedge #101114`.

**`pipred` stays its own token even though the accent no longer flips.** It had two reasons and now
has one: **a die is an object and its pips are red.** The second reason — that a scheme-flipping
accent measured 2.74 on the bone face — died with the dark scheme, and is recorded here as spent so
a later reader does not find half an argument and conclude the token is redundant.

### Floors, re-measured whenever a value moves

Body text on any ground **≥ 4.5**. A purely graphical pair (a pip on a die face, a chip, a focus
ring) **≥ 3.0**. **Nine pairs stand, measured once each.**

**`--radius: 0`** — set it in the shadcn theme, not per component.

---

> ### There is no dark mode, and this is the ruling that removed it
>
> **Owner-ruled 2026-08-18: dark mode is dropped.** `color-scheme: light` — **declared explicitly,
> not omitted**, or form controls and scrollbars still follow the OS and the removal is half-done in
> the one place nobody screenshots.
>
> **It was never chosen.** It arrived in the first `app/` commit — the boot skeleton, 2026-08-11 —
> as `color-scheme: light dark` with a `prefers-color-scheme` block, and no decision record ever
> mentioned it. **It is the anti-default list's own failure case**: an unconsidered default that
> slipped through because it predated the list.
>
> **What it cost while it lasted:** every colour pair measured twice, forever; every gate run doubled
> across three widths; a flood-luminance ceiling that existed only for the dark scheme; a separate
> pip token; and **the olive compromise — in dark, the sun face read olive rather than yellow**,
> which degraded the product's central idea (the winning face's colour owning the screen) in one of
> its four states.
>
> **What removing it costs, stated rather than hidden:** someone choosing dinner at night gets a
> bright screen — and the flood ruling itself said this product is used *「often at night, often in
> bed」*. Some readers expect an app to follow the system setting and read its refusal as unfinished.
>
> **Deleting the blocks is not the removal. Tailwind 4 ships a built-in `dark` variant driven by
> `prefers-color-scheme`, and shadcn's own parts carry `dark:` utilities** — `button` `input`
> `select` `badge` among them. **Delete our blocks without redefining that variant and those
> utilities are handed straight back to the OS setting**: a live rule that fires on a reader's
> laptop and never on ours. `@custom-variant dark` therefore points at `[data-scheme="dark"]`,
> which nothing sets, so the utilities compile and can never match. **That line is load-bearing and
> reads as dead code — the next person to tidy it is the person who re-enables dark mode by
> accident.**
>
> **Verify a removal by rendering, not by grepping.** The check that counts is the page rendering
> **pixel-identical under emulated light, dark and no-preference**. Asserting that the source no
> longer contains the word would not have caught the variant.
>
> **Do not re-add a dark variant of a token to be helpful.** If dark mode returns it is a design
> project — a photographic home on a near-black ground is a different product, and it would need
> designing rather than inverting.

## 2 · Type

Two vendored families: **`UpTo Sans`** (Noto Sans TC, variable, `font-weight: 100 900` **declared** —
the face's default instance is Thin and without the range the whole surface renders hairline) and
**`UpTo Serif`** (Noto Serif TC subset, display only; its source face defaults to **ExtraLight**,
so it is declared `font-weight: 200 900` — the same hazard as the sans's Thin).

**`UpTo Serif` must ship in `app/web`. It does not yet.** The approved page draws its headline in it
from a proposal-only subset; the shipped set is sans-only, so a React build would fall back to a
system serif on the largest object on the screen. **Subsetting it against the home's characters and
teaching the subset gate's manifest a second face is part of the home build, not of the scaffold.**

**There is no third face.** An earlier version of this section named `Archivo Black` for Latin
numerals; **nothing loads it and nothing ever did** — the approved page draws `36,499` in `UpTo
Sans` at weight 900, and that is the rule.

**The declared fallback chain is part of the design:** `"Noto Sans TC", "PingFang TC",
"Microsoft JhengHei", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK TC",
system-ui, -apple-system, sans-serif`. The vendored face cannot draw 89 characters its source face
lacks (88 live names, 0.24%); the chain draws them. **Determinism, not coverage** — it does not
guarantee the glyph exists on the reader's machine.

### The ladder — Tailwind text tokens

| token | 430 | 900 | 2560 | used for |
|---|---|---|---|---|
| `text-answer` | 44 | 72 | 112 | the winner's name on the landed reveal, nothing else |
| `text-display` | 32 | 40 | 52 | a screen's own heading |
| `text-sum` | 32 | 40 | 50 | the dice total |
| `text-temp` | 30 | 34 | 40 | the outdoor temperature, nothing else |
| `text-lead` | 20 | 21 | 24 | a block's lead line, a column head, the bar's label |
| `text-body` | 16 | 17 | 20 | rows, names, controls, fields |
| `text-note` | 13 | 13.5 | 15 | captions, keys, provenance, units |

**The invariant, tested at every width with no ties:**
`answer > display ≥ sum > temp > lead > body > note`.
Build each as a `clamp()` whose **floor and ceiling both obey the ordering** — a ladder that holds
only at the ceiling is the defect this table exists to prevent.

**A section heading takes `text-display`; it does not take the screen's `h1` size.** The mechanism
block's heading sitting on display rank once made an `h1` smaller than an `h2` beneath it.

**A display headline may be serif and two-tone** — ink with one phrase in `hot` — on the home entry.
**Weights:** 900 display/lead/winner, 400 body/note, 500 control labels. **No italics** — neither
face has a true one and a synthesised italic is a tell.

---

## 3 · Space, rule, radius, depth

- **Radius `0`. Everywhere.** The single exemption is `.pip`, which stays round because a die's pips
  are round; squaring them makes the face read as a grid. Nothing else.
- **No soft shadows and no cards.** Separation is colour or a rule.
- **One depth effect exists: a hard offset shadow**, `6px 6px 0 var(--color-ink)`, on images and on
  a raised block. No blur, no alpha. **This is the only shadow in the system — colour included**
  (restored 2026-08-20 evening: the owner ruled 乙 on the device act, which removed the only
  ink-ground command, so the hot-shadow exception written that afternoon died the same day —
  its record lives in ⑤ below). The measured constraint that remains: **an ink shadow on an ink
  ground draws nothing** (`/device`, 1,170 of 10,184 px, a stepped silhouette) — so a command
  simply never sits on an ink ground. **Two readings that are NOT violations** (2026-08-20,
  found by grepping this very sentence): an `inset Npx 0 0` box-shadow drawing a left rule is a
  §3 **rule** wearing box-shadow's syntax so the box does not move — judge it against the rule
  weights, not this bullet; and LIFT's hover offset is `6px + its own 3px lift = 9px` — derived
  from the lift, not a second number. A grep for `box-shadow` is not a grep for depth effects.
- **Rule weights — three component weights, plus one texture hairline:** `3px ink` between a colour
  block and what pins over it; `1.5px ink` between rows and table rows; `2px ink` around a field or
  a ghost control; **`1px` exists only inside a texture ground** (the reveal table band's top rule)
  and never borders a component.
- **Content column:** `min(1200px, 88vw)` — measured **83%** of a 1440 viewport.
- **Block padding:** `16 / 20 / 24 px` vertical. **Spacing steps:** `4 · 8 · 12 · 16 · 20 · 24 · 32`.

---

## 4 · The parts — which come from shadcn, which do not

**Anything marked *custom* has no shadcn equivalent worth bending to it.** Do not install a
component to obtain a part in this column; write it.

| part | source | notes |
|---|---|---|
| `FIELD` | **shadcn `Input`** | restyle: height 48/52/56, `2px ink` border, radius 0, paper ground, `text-body`, muted placeholder. Focus `outline: 2px solid hot; offset 1px`. |
| `GHOST` | **shadcn `Button`** `variant="outline"` | transparent ground, `2px ink` border, radius 0, `text-body`, same height as `FIELD`. |
| `PRIMARY` | **shadcn `Button`** `variant="default"` | ink ground, paper text, radius 0. **Disabled drops the ground entirely** — transparent, muted label, **dashed** ink border, `cursor: not-allowed`. Fading a fill measured **2.75:1** and failed the floor. |
| `TABLE` | **shadcn `Table`** | header `text-note` muted; rows `text-body`; `1.5px ink` row rules; numerals right-aligned `tabular-nums`; a `CHIP` in the first column. **Operator state only — see §4b.** |
| `ALLOC36` | **custom** | the 36 cells in each place's face colour, drawn from the shares the evidence table prints. **It is the round's real allocation, not an illustration** — so it carries no 「示意」 caveat. **Operator state only — see §4b.** |
| `PICKER` | **shadcn `Select`** | the district picker. Restyle the trigger to `FIELD`; radius 0 on the content panel too. |
| `BADGE` | **shadcn `Badge`** | the home entry's eyebrow. `2px ink` border, radius 0, `text-note`. |
| `BLOCK` | **custom** | full-bleed flat colour band, `width: 100vw`, no radius/shadow/border. Ground is one of the palette; text is that ground's `on-*`. Blocks stack edge to edge — **the colour change is the separation**. |
| `BAR` | **custom** | pinned primary control, `fixed inset-x-0 bottom-0`, `3px ink` top rule, content box 56 + 10 padding, `--bar-h: calc(76px + env(safe-area-inset-bottom))`. **At most one per screen.** Every screen carrying one sets `main { padding-bottom: calc(var(--bar-h) + 16px) }`. |
| `ROW` | **custom** | one place in a list. `min-height` 56/60/68, `1.5px ink` bottom rule (last row none), name `text-body`, a `CHIP` at the left. Rows never alternate ground. |
| `CHIP` | **custom** | `12 × 12 px` square, radius 0, `1.5px ink` border, filled from the `FACES = [hot, cobalt, jade, sun]` cycle keyed by pool seat. **Identity, never quantity** — no share, weight or count. |
| `COLLAGE` | **custom** | the home entry's images (`D95`), 2×2 offset, each `2px ink` border + the §3 hard offset shadow, radius 0. **A pool of ten, four visible, one cell swapping every 10 s** (owner-ruled 2026-08-18) — the geometry never moves, only the photograph inside a fixed box. Every image carries `alt` naming the dish and describing the frame, and **the `alt` swaps with the image**. **A picture that cannot be named truthfully does not ship** (owner-ruled 2026-08-18: the menu is drawn only from dishes the generator renders truthfully, and breadth across `D38`'s ten categories chooses it — not taste in food). Rotation, loading, pool order and the `HC` gate: `idea & img/evaluator/spec-home-collage-rotation.md`. |
**`R-D9`'s floor applies to the TUMBLING stage, not the resting one — ruled 2026-08-19 by the
evaluator from the staged recording, and it is conditional.**

Under `D111`'s staging the mechanism is **300 px** at the moment it is the subject — larger than it
has ever been — and what remains afterwards is a **record of a number already read**. So the resting
dice may sit below 180 px (the staged build records 126 px).

**The condition, and it is the whole of the ruling: the resting dice may fall below the floor ONLY
while the pairs list states every pair as text.** In the staged build it does — `Amy 5·1`, `Op 2·6` —
so the number is carried in two places and the small die is an illustration of a value that is also
written down. **Remove or hide that list and the floor reapplies immediately**, because the die
would then be the only carrier of a number at a size that cannot be trusted to deliver it.

**The evidence for the condition rather than a plain amendment:** `frontend` **misread the resting
die as a 6 when it was a 5**, checked `data-value`, and reported it against its own argument. One
misread is not a finding, but **5 and 6 are the confusable pair at small size** — four corners plus a
centre against two columns of three — and it happened at exactly the size the ruling produces.
**A record nobody can read is not a record; a record beside its own text is.**

**And the case the floor was really protecting: someone arriving late.** A member who reconnects, or
opens the reveal afterwards, **never sees the 300 px stage** — for them 126 px is the only size the
dice are ever shown at. **The text list is what makes that acceptable, which is why it is a condition
and not a footnote.**

**`RV-18`:** wherever the resting dice are below `R-D9`'s floor, the pairs list is present and states
each pair as text. Failing either half fails the line.

| `DIE` | **custom** | the 3-D cube — **it already is one**; six faces, `rotateX`/`rotateY`, `translateZ`. It lands **face-on**, which is why the resting state reads flat to a viewer. **If a tilted resting angle is ever ruled (raised by the owner 2026-08-19, unruled), one constraint binds it and it is not cosmetic: the landed face's pip count must stay unambiguous — a person reads the number without counting twice.** The landed face is the only place the roll's result is legible, and `D91` forbids the animation misrepresenting a decided result; the resting frame is where that result is asserted. Foreshortening the winning face while neighbouring faces contribute pips is exactly that failure, so **a small angle that keeps one face dominant is the target — near-corner-on views, where three faces sit at similar prominence, are where it breaks.** Choose by rendering candidates and ruling from them, never by picking a number (frontend's constraint, 2026-08-19). One variable, `--die`, at **140**/180/240 px; the `translateZ` that closes the six faces **derives from it** — change the value, never the derivation. **140, not 132, ruled 2026-08-19** (frontend found the conflict; the recommendation was its): 132 is **17.37%** of 760 against `R-D9`'s **18%** floor, so the token contradicted the gate it is measured by. 136.8 px is the exact floor and 140 clears it at 18.42% with margin for a border. **The floor was not moved to fit the token** — a target adjusted to pass its own test measures nothing, and 18% came from R-D9's measurement of the reference. Parked-width note: 430 is out of scope under §7b, so this changes nothing today; it is fixed now because a known contradiction left in this file is one the next reader has to rediscover. |

### §4a′ · 將選擇權還給使用者 — owner-ruled 2026-08-30 evening; supersedes §4a's sheet (`spec-return-choice.md`)

**There is no 偏好 screen.** Budget and 不吃的食材 leave the product (screen, contributor, endpoint kind; A19's ingest
stays); the keep guard goes with them; the switcher has four tabs (首頁 · 裝置 · 這一餐 · 開獎); a keyed device goes home →
這一餐. The whole of preference is one row of **eleven** 「這次不吃」 chips on 這一餐 (D38 + 便利商店), tonight-only, `persist`
always false, with the per-chip stat, the coverage sentence, the discount sentence, the cross-kind total (`tonight-total`,
moved from the sheet) and D22's crossed warning under it. The ingredient marks (原料未公開／已公開) and the reveal's
`my-reasons` block are removed. §4a below stays as the record of the sheet that was; the `AlertDialog` and `.mark` parts
stay in the registry. The owner's frame: 「將選擇權還給使用者，我們專心做好分類」.

### §4a · Preferences by tempo — owner-ruled 2026-08-28 (`spec-preference-split.md`)

**偏好 is for months; 這一餐 is for tonight.** The preferences page holds the budget and 不吃的食材 —
what is about the person. The round page holds 「這次不吃」, D38's ten types as a chip row above the
search, set by one tap and lapsing at the nightly erasure (D17), **with no keep toggle**: a type is
short-term by ruling. The stat sentences (較少中 · 抽不到 · D22's breadth) travel with the stance to
wherever it is set, never separately. Same wire, same numbers — the split is where a hand lands,
not what the engine reads. Chip part: `data-part="tonight-chip"`, `data-on`, filled on / ghost off. **An `allow` that ends a row
mirrors that row's `persist`** (amended 2026-08-28 — a non-kept `allow` over a kept `avoid` is undone
by the nightly erasure).

**偏好 asks once before you leave with an un-kept change — owner-ruled 2026-08-28, corrected the same
day (`spec-ingredient-keep.md`; the kept-by-default wording was withdrawn by him and never built).**
D17's opt-in stands for every kind. A change made this visit whose row is not kept is a *pending* one;
any in-app exit from 偏好 with a pending change opens the registry's one dialog part — `keep-dialog`,
shadcn `AlertDialog`, in-page, never `window.confirm` — 「要保留這次的變更嗎？／保留的話，只有你看得到。」 + per pending kind 「不吃的食材會一直記著。」／「預算記到下個月底。」 (no 05:00 sentence; a kept ingredient never lapses — owner, 2026-08-28) with 保留 as the filled
primary and 不保留 as the ghost; either continues the navigation, `Esc` stays. Closing the tab is not
guarded and the change lapses at 05:00, which is the stated default. Categories on 這一餐 stay
tonight-only with no keep control and nothing to guard.

### Feedback for a stance belongs at the tap; the reveal reports only what the roll did — ruled 2026-08-30 by the evaluator, answering the owner's critique

The owner, verbatim: 「為何是透過顯示一行字，應該是當使用者點選後，前端透過選項變色的方式，讓使用者知道已經勾選，這部分evaluator參考的資料不足」.
He is right about the moment, and half-right about the mechanism. Two rulings:

**1. The chip's on-state must carry a second cue that is not colour.** Today 「這次不吃」's on-state is an ink fill
with paper text and 500→700 weight. A fill inversion is a *lightness* change, so it survives colour-blindness, and
weight is a second cue — but neither is a glyph a person can name, and the product already has one: the 偏好 rows'
leading `.mark` square, □ off / ■ on. **The chip gets the same mark**, □/■ before its label, so a selected chip reads
as selected in monochrome, at a glance, and in the same vocabulary as the sheet the person just left. Sources:
WCAG 2.2 SC 1.4.1 *Use of Color* (colour is never the only visual means of conveying state) and SC 1.4.11 *Non-text
Contrast* (the chip's 1.5 px ink border and the mark ≥ 3:1 against paper — measured 15.9:1); Material 3 *Chips* —
a selected filter chip shows a leading check glyph *and* a container colour change, never the colour alone; Apple
HIG *Feedback* — confirm a selection where it was made, immediately; Nielsen #1 *Visibility of system status* and
#6 *Recognition rather than recall*; Doherty threshold (the optimistic flip is < 400 ms today — measured ~120 ms to
paint); Refactoring UI, "don't rely on colour alone to communicate state". Spec: `spec-chip-mark.md`.

**2. The reveal's `my_reasons` line is a different moment only when the roll DID something.** A stance is
confirmed at the tap (ruling 1). What the tap cannot show is what the roll did with it — and there are two very
different answers. An ingredient veto **removed a place from the table** (×0): that is an outcome the person cannot
see anywhere else, and Nielsen #1 says the system reports what it did; the line stays: 「原料含有：蛋」 / 「部分品項含有：蛋」.
A category discount **removed nothing** (×0.8, the place can still win, the effect is invisible by design — the roll
is random): 「避開的類型：火鍋」 restates the stance the chip already shows and adds no outcome; on the reveal it is
redundant, and next to the veto's line it reads alike while meaning the opposite (backend's own note). **So
`my_reasons` carries veto outcomes only** — sentences from the `ingredient` contributor — and the discount's
sentence is not rendered on the reveal. The filter belongs on the wire (one predicate on the contributor), not in
the browser, which must not sort reasons by what they mean. This narrows D105's 2026-08-29 amendment (「要」, all
kinds) on the *reveal* only: the person still *may* read every own reason — the GET already states the stance and
its count on 偏好 and 這一餐 — the reveal just stops repeating the ones that changed nothing. Cost: one wire
predicate (backend), nothing in the browser. Rejected: render all (the owner's critique); render none (a place
vanished with no trace); two visual weights for two meanings (the fix for a redundant line is not a lighter font).

**Where the owner's "reference material" point lands, stated plainly:** the chip spec (2026-08-28) ruled weight
and fill from the depth vocabulary and did not consult the accessibility criteria for state; that is the gap he
named, and ruling 1 closes it with the sources above. The list of what to consult is now in
`idea & img/research/skill-research-sources.md`'s design section.

### §4b · The reveal has two states, and they are not a permission toggle over one design — `D105`

**Member state — what a person in the circle sees after the roll:** the winner, the dice, **one line
「三十六格已按權重分配」**, and the bar. **No per-place shares. No reasons. No table. No allocation
grid.**

**Operator state — demo and operator only, gated on a flag on the `device_secret`, set at issue
(`python -m upto.issue <circle_id> <nickname> --operator`), never on a URL flag:** everything above
**plus** `TABLE` and `ALLOC36`. **The role rides the credential, not the person** — `D12` keeps
`principal` holding an id and a stamp and nothing else — so the response shape is chosen by which
credential authenticated, and no parameter can carry it. The operator holds a seat like any member.

**Why, and it is the same argument as `B1`'s veto carried past the roll:** a narrow exclusion with an
obvious cause — 麻辣火鍋 at 0/36 — is **one guess in a five-person circle**. Publishing the shares
after the roll leaks precisely what the anonymity machinery exists to protect, and it leaks it to
the four people best placed to use it.

**Two consequences for how this is built and measured, and both are easy to get wrong:**

1. **`R-D9`'s answer-region targets apply to the MEMBER state.** Its non-negotiable clause — *the
   evidence table's first data row stays above the fold* — **has no object in member state, because
   there is no table.** With nothing below it, the answer region can be **more generous than 40 /
   45 / 50%**, not less. That is a gain, not a loosening.
2. **`D91`'s regression splits.** *Zero layout shift* and *the answer hidden mid-tumble* apply to
   **both** states. *The evidence table fully drawn while the dice move* and *the hit row at
   neighbour weight until it lands* apply to the **operator** state only — **members have no table
   for a hit row to leak from.**

**The cost, stated because nobody else will say it:** the home promises 「每一個數字都查得到出處」
and the reveal is where that promise was kept. **A member can now no longer check it.** The claim
becomes something the product does rather than something a user can verify, and its visible proof
lives in demo mode. That is a real trade and D105 makes it deliberately; it is not an oversight to
be quietly repaired by leaking a share back into the member view.

### The winner headline — A16, `D92` as amended 2026-08-27; this line added 2026-08-28 by the evaluator

**The headline is the API's `winner_headline`, verbatim; the browser computes nothing.** The server
strips trailing business-type tokens from a *registered-rung* winner (一階堂拉麵餐飲有限公司 → 一階堂拉麵,
欣葉國際餐飲股份有限公司 → 欣葉), leaves a sign or brand name untouched, and shows the original when
the strip would leave fewer than two characters (悠國際有限公司 stays whole). **Every list keeps the
composed name** — the 提名 list, the operator table, the pairs list — because a list is where a
person tells rows apart, and the headline is where one name is read alone. `null` falls back to
`places[winning_place_id]` and never renders empty (`Reveal.tsx`). A shortened name in any list row
is a defect; a list row and the headline disagreeing is not.

**The bracket — owner-ruled 2026-08-28 (99b9950, `D92` amended; gate `gate-a16-2026-08-28.md`).** A
composed name that carries `D92`'s bracket splits on the wire: `winner_headline` is the **shortened
base** (一階堂拉麵), `winner_qualifier` is the **bracket's content without its parentheses**
(大安和平東路), `null` when the name has none — both fields on both wires. The reveal renders it so:

- `<p class="qualifier" data-part="qualifier">` **directly under `h1.winner`, inside `.answer`**, so it
  rides the block's `aria-hidden` / `inert` and its fade, and `D91`'s zero-shift clause is kept for
  free. Rendered **only when non-null** — no empty element, no reserved box: a single-site winner has
  nothing to say there and the sentence moves up by exactly the line it did not need.
- `text-lead`, the body face, regular weight, **`currentColor`** like everything else on the flood —
  never `muted`, which fails the floor on every `-deep` companion. Letter-spacing `.04em`; no
  parentheses, no dash, no icon: the browser adds nothing to the string and computes nothing from it.
- It is a statement of *which* branch (the address line the member payload otherwise lacks), so it
  matches the 提名 row beneath by eye — the row reads 一階堂拉麵餐飲有限公司（大安和平東路）, the headline
  reads 一階堂拉麵 over 大安和平東路. A qualifier that appears on a list row, or a parenthesis that
  appears in the qualifier, is a defect.
- Gate lines HL-6 / HL-14 in `probes/evaluator-harness/g_a16.py`.

---

**The fill follows reversibility, not the part (`R-2`, `R-11`).** A control carrying a safe,
reversible act may be filled. **A control carrying an irreversible act is a ghost at rest** and
fills only once armed, at which moment whatever else was filled drops to ghost. **The rule is *at
most one* filled control per screen, asserted over every reachable state** — a screen may rest with
**none**, carrying a primary *shape* (an ink border, no ground) instead. **A disabled control is
never "filled".**

---

## 5 · Motion

1. **The flood** transitions background and colour over `.45s ease-out`. Nothing else about the
   landing animates.
2. **A bar's state change** is an opacity and label cross-fade of **120 ms**. Its box does not move,
   resize or slide.
3. **`prefers-reduced-motion: reduce`** removes the tumble, both transitions and rule 4's arrival
   (no travel, no stagger); **the end states still apply, instantly.**
4. **Arrival — one per screen, on first paint, once per mount** (`--t-flood` 450 ms `ease-out`,
   from `translateY(12px)` + `opacity: 0`, staggered 90 ms in reading order). The full rules are
   `spec-motion-arrival-2026-09-11.md` §1a; the two that are most often got wrong are **never on
   anything that renders in response to an action** (a refusal that fades in has not refused
   anything yet — `BF-1`) and **never on 開獎**, whose sequence is `D111`'s and is the only motion
   that screen has.

**Nothing scroll-triggered, nothing springy.** Disable shadcn's default enter/exit animations where
they are not one of the four above.

***Amended 2026-09-11, owner 「1」*** (`decision-log.md`; direction 乙, the reference
`https://www.i-web.com.tw/` and his 「動態感太少」). This paragraph read **「Nothing scroll-triggered,
no entrance animation on a block, nothing springy.」** and the middle clause is **withdrawn**; rule 4
is what replaced it. *Kept rather than rewritten, because the ban was right about the thing it was
aimed at and the measurement is what moved it:* our motion density already matched the reference
(首頁 13 of 81 elements carry a transition, **16.0%**, against the reference's **15.4%**), so the
complaint was never a shortage of animation — **every transition we owned was reactive, firing only
if the member touched something, and nothing on a screen ever arrived.** The reference spells arrival
as *scroll* because it is 9,499 px tall; our pages are exactly one viewport (900 px at 1440,
measured), which is why **scroll-triggered stays banned** — here it would be furniture — and why
*springy* stays banned too (`D109` retracted the bounce and it stays retracted).

### 質感 — the perceived-quality rules, ruled 2026-08-20 by the evaluator under `D101`'s delegation

*Why this section exists: the owner has said 廉價 about this surface more than once, and the
diagnosis is now settled — the cheapness was never the stack, the hardware, or the builder; it was
**generic web-widget vocabulary drawn onto a print-direction page**. These rules are the fix, stated
as rules. Grounded in the `ui-ux-pro-max` database (in the repository, `.claude/skills/ui-ux-pro-max` —
query it with `python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain <ux|style|gsap|typography>`);
where a search result and this file disagree, **this file and the rulings win** — the database is
reference, not authority.*

1. **Print vocabulary.** A control on this surface is drawn as an act from print culture — a stamp,
   a signature line, a ledger entry, a filled ink block — never as the generic web widget that does
   the same job. The test before shipping any control: *could this element appear in any SaaS form
   unchanged?* If yes, redraw it. (The ghost button, the gray disabled pill, the dashed drop-zone
   box are the named offenders.)
2. **Press feedback, inside the bounds.** Every clickable element changes visibly on press —
   the vocabulary here is **ink-fill** (background → ink, text → paper), 120 ms — and the change
   never shifts layout bounds. No `scale` on press: a stamp inks, it does not shrink.
3. **Motion tokens, never loose durations.** The tokens are: `--t-press: 120ms` (press and
   cross-fade, §5 rule 2), `--t-hover: 120ms` (§5 hover rule), `--t-flood: 450ms` (§5 rule 1).
   New motion picks one of these; needing a fourth number is a ruling, not a tweak. One duration
   copied onto every transition is the database's own named anti-pattern — the token set is small
   **and chosen per role**, which is different from small by laziness.
4. **State correctness never waits for `transitionend`/`animationend`.** Set the semantic state
   directly; let the animation catch up or be cancelled. This is `RV-19`'s lesson stated as a
   building rule: the reveal's failsafe raced its own animation for a week because a state change
   was coupled to an animation's completion contract. **The watched form is the stated exception
   (amended 2026-08-20, `F-5` — the rule as first written banned `RV-19`'s own fix):** a handler
   on `animationend` may commit a state **when a watchdog commits the same state if the event never
   fires** (`Reveal.tsx`'s landing). The ban is on the unwatched wait, not the watched one.
5. **Stroke hierarchy, fixed — four weights, each owning a layer** (corrected 2026-08-20, `F-4` —
   this sentence and §3 disagreed while citing one ladder; the build was right and the sentence
   wrong): `3px` = structural rules (section tops, the flood's frame); `2px` = component borders
   and focus outlines (§3's field/ghost line); `1.5px` = row rules — list rows, table rows, the
   chip's border (§3's row line); `1px` = hairlines inside a texture ground (the table band's top
   rule). Mixing weights inside one layer reads as sloppy at exactly the viewing distance the demo
   is judged from.
6. **Icons are SVG from one family, or absent.** No emoji glyphs as icons anywhere. (Today the
   surface uses almost none — keep it that way rather than decorating.)
7. **`cursor: pointer` and a visible `:focus-visible` (2px ink outline) on every interactive
   element.** Already §7's anti-default entries; repeated here because they are also the two
   cheapest signals of care a page can carry.

### The depth vocabulary — ruled 2026-08-20 by the evaluator under `D101`'s delegation

*Measured from the `ui-ux-pro-max` demo the owner pointed at (22 elements probed by Playwright,
computed styles diffed across hover): its entire "feel" is three recipes, each under ten lines of
CSS, applied everywhere consistently. Adopted here with our tokens. The owner's standing complaint
(廉價) is answered by COVERAGE — every interactive element carries exactly one of these, chosen by
role; a bare `hover:bg` on anything interactive is now a defect.*

- **SINK — commands (buttons, the stamp).** At rest the element sits on a hard ink shadow
  `4px 4px 0 0 var(--color-ink)`; on hover it moves `translate(2px,2px)` while the shadow drops to
  `2px 2px 0 0`; on `:active` it bottoms out — `translate(4px,4px)`, shadow `0 0 0 0`, **ink-fill**
  (bg → ink, text → paper). All at `--t-press` (120 ms). The metaphor is a lead type pressed into
  paper; `scale` stays banned.
- **INK-FILL — quiet/ghost commands** (secondary actions drawn as bordered text): hover fills
  bg → ink, text → paper, 120 ms. Same move as the press rule; hover previews it.
- **SELECTION controls are commands** (③, 2026-08-20): a control whose press changes what the
  engine does next roll — `.band`, `.keep` — takes **SINK**; a list row (`.rowTap`) is enterable
  content and takes **LIFT**. `frontend`'s assignments, confirmed.
- **The device act is 乙 — `--hot` ground, ink text, the standard ink SINK shadow** (⑤,
  **owner-ruled 2026-08-20 evening from the rendered `device-act-sink.html`**, superseding the
  evaluator's same-day 丙). This is a stated reversal, made in the demanded form: the owner saw
  all four candidates with 乙 labelled "it is Ruling 2's recipe and choosing it reverses this
  morning's supersession", and chose 乙. What returns is Ruling 2's **colour** — the size stays
  the act's (the candidate the owner ruled from was act-sized, not Ruling 2's full-width
  56/60/64). Consequences: no command sits on an ink ground anywhere (甲 measured illegible —
  1,170/10,184 px stepped silhouette), so §3 keeps its single shadow colour; the 丙 hot-shadow
  exception lasted one afternoon and is recorded here so it is not re-invented. *Still rejected:*
  甲 (invisible), 丁 (half a recipe — the shadow is the promise the block can be pressed).
- **The district picker takes INK-FILL** (④, 2026-08-20, `F-7`): `[data-part=picker]` was the one
  interactive element on four screens with no hover recipe and `cursor: default`. By ③ a case
  existed for SINK; **rejected because SINK changes the RESTING state** (the 4px hard shadow), and
  home's resting render is pinned by `A0c`'s pixel gate to the owner-approved page — a depth recipe
  may not silently change a gated resting state. INK-FILL previews the press and changes nothing at
  rest. It also gains `cursor: pointer` (rule 7).
- **LIFT — enterable content blocks** (list rows, cards, collage cells): §5's existing hover rule
  unchanged — `translate(-3px,-3px)` + hard shadow toward the lower right, 120 ms, on the cell
  never the `<img>`, `@media (hover: hover)` only. Commands sink INTO the page, content lifts OFF
  it — the two directions are opposites on purpose, and giving one element both is a defect.

### The reveal act — 蓋章, ruled 2026-08-20 by the evaluator under `D101`'s delegation

The reveal's sign act is the **stamp** (`sign-act.html` 乙, hub item b): the staged state asks
「這一餐，說定了嗎？」 in the display face beside an **empty seal** — `80×80`, `2px dashed` the
flood's foreground colour. Hover: border turns solid, fills paper, text turns `--color-hot-ink`,
rotates `-4deg` (a stamp never lands square). Active: adds the SINK bottom-out. Signed state, same
position: the seal is paper, the member's nickname at 900 weight at the same `-4deg`, with
「說這一餐去了」 beside it — `D106`'s named trip, same nickname the wire carries.
**Amended 2026-08-20 after `frontend` built it:** (①) **the nickname is set in the SANS, not the
display face** — and the reason is a law, not a taste: **the display face carries AUTHORED copy
only; data off the wire (names, anything typed at key-issue) is always sans**, because D101's
subset is derived from the stylesheets' own copy and a derivation cannot know a nickname — the
display face on data is tofu by construction. The stamp's quality rides the 900 weight, the
setting and the -4deg, none of which needs the face. (②) **orientation forks on content**: a
nickname containing CJK sets `vertical-rl` upright; an all-Latin nickname sets **horizontal** —
`vertical-rl` rotates Latin 90° and a rotated word is not a stamped one (RV-17's lesson again:
CJK and Latin fail differently, so the fork is data-driven, and any fixture for it must include a
Latin name).
Cross-fade only (§5 rule 2); the seal's box is reserved from first paint (RV-17's logic).

### The reveal's ground — 網點即骰點, ruled 2026-08-20 by the evaluator under `D101`'s delegation

*The owner's standing complaint was 單調, and the licence given was a static image. The ruling
spends it on pattern, not photograph: the halftone dot is print's own texture AND the die's pip —
the one mark this product owns. Riso-print logic: paper, spot colours, halftone. Reference render:
`idea & img/design-proposals/reveal-ground.html`. Pure CSS (`radial-gradient` tiles), zero image
assets, §6's dead-wifi rule untouched. **Glow is banned on this ground — print does not glow**;
the staged state's radial blur dies with this ruling. **Scope (2026-08-20, `F-6`): the ban is the
reveal's print ground, not the whole product** — home's sun halo (`.halo`, the 5 s pulse) is
weather iconography inside the composition `A0c` gates against the owner-approved page, and it
stands until that page itself is re-ruled.*

- **Tumble state:** paper ground with a neutral halftone field (`~7%` ink dots on an 18px tile),
  and a **table band** along the bottom edge — denser dots (`~13%`, 12px tile) with a 1px hairline
  top — the structural line the dice land on. Neutral means neutral: **no cluster may read as a
  die face before the result exists** (D91 — the ground must not answer first).
- **Staged state:** the flood keeps a faint ink halftone for tooth, and **this round's real pair
  is printed as two poster-scale die faces in a darker step of the flood's own colour** — pip
  grids ~340px with a 4px tone border so a face reads as a face (cropped dots read as blobs — the
  rubric's named slop), bleeding off opposite edges, each at a small fixed rotation. The ground
  repeats the truth, never invents it: the faces are the stored dice, so RV-16 is untouched
  (nothing appears before landed) and the tone stays below the text layer — copy is always the
  brightest layer.
- **One recipe, four colours:** every face colour carries a `-deep` step (cobalt `#1B34B8`, hot's
  deep is the existing hot-ink family, jade and sun derived the same one step down); no per-colour
  design.

### The dependency shelf — owner-ruled 2026-08-19

**The rule first: nothing is adopted because a reference has it.** The owner declined to walk
`got-you.vercel.app`'s stack item by item. **This list is a shelf to reach for when a real need
arises — propose then, through orchestrator, with recommendation, cost and reason.** `design.md`'s
dependency rule stands: anything with a cost goes up before it goes in.

| | ruling |
|---|---|
| **Next.js** | **不換.** Vite stays. |
| **Cloudflare** | **要** — the public-deployment ruling comes later. |
| **`motion`** | **approved and in** (D104 amendment, `115ad08`) — LazyMotion, minimal features, +27,815 B gzipped measured, bundled not fetched. |
| **Zustand** | **not now.** One SSE snapshot is the truth; a store would be a second one. |
| **React Hook Form + Zod** | **not now** — the forms are tiny. |
| **Day.js · DayPicker · react-icons · overlayscrollbars · linkify** | no need today. |
| **Supabase** | **no.** Our own Postgres + FastAPI **is** the portfolio; replacing it with a hosted backend deletes the thing being shown. |
| **Vercel** | a deployment question, later. |
| **Google Places** | **narrow only** — live photos and hours **of the winner**, on the reveal, **never stored**. Needs its own card. Research summary in `decision-log` 2026-08-19 night. |

**Why a shelf rather than a stack:** every entry above is a real dependency with a real payload, and
**the one we did adopt was adopted on evidence — six rejected animations — not on a reference having
it.** That is the bar for the next one.

### Reference sources, and what each one is good for — recorded 2026-08-19

**Owner-supplied:** 21st.dev (community templates + components), Magic UI, Aceternity UI,
react-bits.dev, hover.dev, shadcn/ui examples, and **Dribbble** (search *food app hover*, *dice roll
ui*, *restaurant picker*).

**They are not interchangeable and the difference is load-bearing.**

- **The moodboard (`idea & img/design-proposals/moodboard/`) is nine SHIPPED commercial products** —
  the owner's stated bar, 「商業等級的範例」. **It is the fidelity reference and nothing else replaces
  it**: every screen in it survives real data, real names, real edge cases.
- **The component libraries are recipes.** Useful for *how* an effect is built. Each one costs a
  dependency or a second visual language, so a pick from them goes to orchestrator first.
- **Dribbble is concept art, and that is its use and its limit.** Nothing there has to survive
  36,499 rows or a 62-character place name; a shot is composed around content chosen to flatter it.
  **Good for motion ideas and composition. Never a fidelity bar** — measuring this product against
  an unbuilt concept would repeat the D87 mistake in the opposite direction, where a check convicted
  a family rather than a defect.

**Every pick is recorded in this file with its source.** Where an effect is derived from this
surface's own language rather than taken from a source, that is recorded too — it is the cheaper
answer and usually the better one.

### Hover — the fifth rule, ruled 2026-08-19 by the evaluator under `D101`'s delegation

*Owner: 「找一些網頁讓evaluator可以參考，我不想做太多決定，像是當鼠標移動到首頁圖片時會有浮動效果。」
Micro-interaction picks are the evaluator's and are recorded here with their reasoning rather than escalated.*

**The `COLLAGE` tile lifts on hover, and the effect is derived from this surface's own shadow rather
than imported.** Every tile already carries a `2px ink` border and a **hard offset shadow** — no blur.
The idiomatic hover for a hard-shadow object is the one that reads as it leaving the page:

- **`transform: translate(-3px, -3px)`** and the shadow's offset **grows by the same 3 px**, so the gap
  between object and shadow widens. **Nothing scales and nothing rotates.**
- **`120 ms`. It IS a new number, and the reason first given for it was false** — corrected
  2026-08-19 by `frontend`, which checked. This surface had no acknowledging duration before today:
  the only transitions were the collage's 400 ms cross-fade and the reveal's .45 s flood, **both
  ambient rather than acknowledging.** The value stands on its own merits; **the justification that
  it was already here did not, and that kind of reason goes on sounding true.**
- **Wrapped in `@media (hover: hover)`** — without it a touch device parks the tile lifted on tap.
- **The lift is on the CELL, not on the `<img>`.** The collage swaps every 10 s; an effect bound to the
  image would drop mid-hover when the photograph changes under the cursor.
- **`transform` and `box-shadow` only — no layout property.** `D91`'s held-box family: the tile moves
  visually, the flow does not, so nothing reflows.
- **`prefers-reduced-motion: reduce` keeps the end state and drops the transition** — §5 rule 3's
  existing pattern. Hover still reads; it arrives instantly.

**Explicitly rejected: scale.** A 2×2 *offset* grid puts neighbours close on the diagonal, so scaling
pushes them into each other; it also softens a photograph already delivered at 640×360.

**Explicitly rejected: importing an effect.** Magic UI, Aceternity, hover.dev and react-bits were the
owner's suggested sources and each has a card-hover recipe, but **every one would add a dependency or
a second visual language to replace four lines of CSS this surface already expresses.** The reference
set is worth keeping for effects we cannot build — this is not one. **Anything that does add a
dependency goes to orchestrator first.**

**Gate:** `HV-1` the rest frame is unchanged with and without the cursor — hover must not move
anything the fidelity gate measures · `HV-2` the cell's **`offsetTop`/`offsetLeft`** are unchanged and **every neighbour's rect is
identical** — **corrected 2026-08-19: `getBoundingClientRect` includes transforms, so it fails any
transform-based hover by construction, here by exactly the ruling's own 3 px. Right intent, wrong
instrument** — the same family as §9's box-vs-content rule · `HV-3` under `reduced_motion: reduce` hovered and unhovered still differ and
the transition duration is 0.

### Ambient loops — the fourth rule, added 2026-08-18

**An infinite animation is allowed only where the thing it animates is itself continuous.** Weather
is continuous; a slowly rotating collage is a rhythm; a button is neither. **Three conditions, all
required:**

1. **It must not move layout.** Everything animates on `transform` and `opacity` inside a **fixed
   box**, so a state change — a different weather condition, a different photograph — **shifts zero
   pixels**.
2. **Its period is 1.5 s or slower.** The surface's ambient set: 1.5 s rain, 3.2 s flash, 5 s halo,
   6–8 s drift, 14 s rotation, 10 s collage swap.
3. **`prefers-reduced-motion: reduce` stops all of it on a legible frame** — not a blank one. A
   stopped sun keeps its halo; a stopped collage keeps a photograph.

**A loop that fails any of the three is an entrance animation wearing a longer duration**, and §5's
rule 2 already refuses those.

---

### The verb — ruled 2026-08-19 by the evaluator under `D101`'s delegation

**This is not a choice between 擲 and 翻開. Both are correct, for two different acts, and the fault
would be swapping them.**

| the act | the verb | why |
|---|---|---|
| **your own dice, your own tap** | **擲** | You are causing it. 「提完了就擲」, bar 「擲骰」. |
| **someone else's result appearing** | **翻開** | You are not causing it; it already exists and is being shown. 「還沒翻開」. |
| **whose dice decided it** | **開 / 以…的骰子為準** | The screen is called 開獎. |

**The rule, and it is the gateable half:** *a verb on a control promises what tapping it does.* **擲 on
a control that only reveals an already-determined result is a lie**, and **翻開 on the control that
actually generates your roll understates it into passivity. Never label a control with the other
act's verb.**

**`VB-1`:** every control's verb matches the act it performs — 擲 only where the tap produces the
value, 翻開/開 only where it exposes one that already exists. **`VB-2`:** the two vocabularies never
appear for the same object in one screen.

**Flagged rather than ruled, because it crosses two of the owner's own rulings:** the A7 animation is
**拋擲** — dice fly in from off-frame — and `D108` says the deciding dice are *revealed*. A throw for
your own roll is honest; **a throw for the reveal of a pair that already existed is the animation
asserting an act that did not happen.** Whether the flying entry survives into the reveal is the
owner's, not mine. `D91` is the entry it would be argued under.

---

### The band below the fold — ruled 2026-08-19, after it happened three times in one day

**The pinned `BAR` reserves its own height, and the reserved band is not free space.** Content placed
there is invisible at rest on every screen whose page scrolls less than the band is deep. Three
instances today: `D110`'s home line (text wholly inside the bar's band at rest), the round screen's
refusal (fixed), and the reveal's seed line.

**What may live there:** **provenance and standing description** — where a number came from, what the
product's shape is, a source credit. Things a person may want and will go looking for.

**What may not:** **anything a person must read at the moment it appears.** Errors, refusals,
confirmations, anything answering *what just happened* or *what do I do now*. **A refusal a person has
to scroll to find has not refused anything** — it has failed silently while looking like it worked.

**The test is not "is it important" — it is "does it arrive".** A standing line was always there and
can be discovered. A line that appears in response to an action has one moment to be read, and the
band takes that moment away.

**`BF-1` has TWO halves and the first one reads like the whole rule — corrected 2026-08-19.**
**(a)** no element that renders in response to a user action has its text inside the bar's band at rest;
**(b)** **the page must be able to grow past the band.** `frontend`'s absolute-positioned column satisfied
(a) and failed (b): `scrollHeight` equalled the viewport, the commitment sat at 843–890 behind a bar whose
top edge is 824, **and no scroll existed that could reach it.** It was standing provenance — allowed in the
band — and still unreachable. **A rule about what may live there is worthless if the page cannot be scrolled
to it.** **Measured from the text's own `Range` rect, never the padding box** (§9) — the reservation is
not the line.

---

## 6 · Rules that bind every screen, whatever the stack

A change here is not a design decision and cannot be made from this file.

- **The surface may state; it may never advise.** No recommendation UI, ever. `D20`
- **Weather appears on the home entry and nowhere else.** `D20`
- **No restaurant name on the home entry.** `D94`
- **Nothing before the roll shows a share, weight or per-place count**, in any reachable state. `B1`
- **The result is decided before a frame animates**, the answer is genuinely hidden while the dice
  move, and the landing shifts **0.00 px** — the answer holds its space via `opacity 0 → 1`, and
  **the hit row is gated by font-weight**. `D91` **Do not refactor this.**
- **No external asset.** Nothing fetches from another host; it renders with the wi-fi off. **This
  survives the build step: Vite must inline or emit local assets only, and no CDN font.**
- **`dangerouslySetInnerHTML` is never used.** (React's form of the old `v-html` prohibition.)

---

## 7 · The anti-default list — scoped to *unconsidered* defaults

**Scope, and it is a correction.** This list catches a default that arrived because nobody chose it.
**It does not rule out a family.** The family check convicted a warm-cream-and-serif direction that
the owner's own reference belongs to — a cliché is a thing done often because it works, and testing
for one is not testing for quality. **That half of the list is dead; do not resurrect it.**

What still counts as a defect:

1. **A shipped shadcn default skin** — rounded, soft-shadowed, gray. §0.
2. **Rounded cards floating on a ground with a soft shadow.** Radius is 0; the only shadow is hard.
3. **A gradient anywhere.** There are none.
4. **Emoji or icon fonts as UI.** The dice are real pips; the picker's caret is CSS.
5. **A weather or a metric printed larger than the thing the product exists to answer.** The ladder
   makes this structurally impossible — check it, do not trust it.
6. **Saturated colour spread across the screen instead of concentrated.** Measured: the reference
   holds high-saturation pixels to **10.8%** of the frame; a home at **36.7%** is the state the
   owner rejected. **Target: keep it under 20% and moving toward the reference.**
7. **A screen with no imagery where imagery is what carries the subject.** `D95`

---

## 7b · DEMO SCOPE — owner-ruled 2026-08-19, and it overrides the widths everywhere below

**「先捨棄手機，目前在趕進度，像 lawcidity 一樣有個 demo 網頁就好」.**

**The target is one width: 1440 — the approved page's own viewport.** Every spec in
`idea & img/evaluator/` states numbers at 430 / 900 / 2560; **while this section stands, only the
1440 column is built and only the 1440 column is gated.** The others are not deleted from the specs,
because deleting them is how they come back as guesswork.

**What this is and is not.** It is a portfolio demo — a page that shows the mechanism and the data
pipeline to someone assessing the work. It is **not** the shipped product. The product's real use is
five friends on five phones deciding where to eat, and a desktop-only build cannot do that job. That
cost is accepted deliberately, on a deadline, by the owner.

**Carried, not lost — the phone findings that were open when this landed:**

- **430's vertical rhythm compounds tighter than the approved page** — every gap ~1–2 px smaller,
  reaching **7.7 px at the collage** (inside ±8 px, at its edge), and aligning the frames still
  leaves 11.08% differing, so the smaller type tiers diverge as well as move.
  `gate-a0c-fidelity.md` holds the measurement.
- **`D89`** (the round screen responsive from 760 px) and **`R-D9`**'s 430 targets are **parked, not
  reversed.**

**Flip condition — one line, so nobody has to reconstruct it:** the day the product is aimed at
phones again, re-run `gate-a0c-fidelity.md` at 430 first. **The 430 drift is a known open defect and
must not be rediscovered as a surprise.** A build that has only ever been gated at 1440 has not been
shown to work on a phone; it has been shown to photograph well on a laptop.

**Do not read a green 1440 gate as a green product.**

### The switcher's corner at ultra-wide — ruled 2026-08-21, WITHDRAWN by the owner 2026-09-04

> **This paragraph no longer describes the product. Owner-ruled 2026-09-03, 軸二 = 乙 報頭內
> (`D101` amendment (10)'s sibling ruling; `spec-round-menu-2026-09-03.md` §3): the switcher moves
> INTO the home's masthead row — brand · dateline · picker · switcher — and the four inner screens
> get ONE slim fixed bar carrying 返回 at the left and the links at the right. It reverses ruling ⑥
> of 2026-08-20 and it reverses the sentence below.**
>
> **It is kept rather than deleted because its argument is still the live constraint.** *Chrome
> belongs to the window; the page belongs to the page* is why the inner screens keep a fixed bar
> instead of putting navigation into each screen's own flow, and why the bar is one full-width rule
> rather than something aligned to the composition. What the ruling changed is the HOME, where the
> masthead is itself chrome and the switcher inside it is no longer a second, competing frame.
>
> **What it cost, measured before the build** (candidate 5, `idea & img/evaluator/baseline-cand5/`):
> the masthead is a wrapping flex row already holding brand, dateline and the picker. At **1440 and
> 2560 the switcher fits on that row and the masthead's height does not change**, which is why A0c
> stayed at 0.00 px through this change. At **≤900 it does not fit** (752 px of content against 777
> needed) and the masthead grows by the switcher's own row — **+44 at 900, +43 uniform at 430**,
> verified as a uniform delta with nothing else moving. Nothing was shrunk to prevent it: a cramped
> four-item row is worse than an honest second line, and 900 is not a gated fidelity width.
>
> **`D107` still stands and the deletability promise with it.** The switcher is still demo
> scaffolding — one component, one stylesheet block, one line in `main.tsx`. One bar is fewer
> pieces than two.

*(The withdrawn text, kept whole:)* **The switcher and the back arrow stay pinned to the viewport's
corners at every width. No code change.** Measured at 2560: the home composition scales as one object (9ad903d, 甲) and centres,
so the 273px switcher strip sits 167px clear of the column's right edge — visibly detached from
the composition. **That detachment is correct, not a defect.** The switcher is demo scaffolding
(`D107`: it disappears with the demo), and scaffolding that aligns itself to the composition
reads as product. Chrome belongs to the window; the page belongs to the page. The back arrow
pins the opposite corner, and moving one without the other would split the pair.

**Rejected: aligning the switcher to the scaled column's right edge at ≥1920.** It looks tidier
in a screenshot and it costs a media query plus a claim — that this control is part of the
composition — which `D107` says is false. The day the switcher dies, nothing about the
composition has to be re-ruled.

---

## 8 · What each screen is measured against

**From now the gate is the owner-approved comparison page, pixel-for-pixel, not conformance to a
palette ruling.** The reference wall stays as the standing bar: reveal ↔ Wheel of Names, round sheet
↔ Rallly's poll panel, home ↔ the La Maison demo and Gumroad, device ↔ Splitwise. **A marketing page
is not a product screen** — where one is cited, only its colour energy and type scale are borrowed.

---

## 9 · Writing a check against this surface

**A box is not its content — measure the edge you actually mean (added 2026-08-19).** Any element
carrying `padding-bottom` to reserve the fixed `BAR`'s height has two different bottoms, and they
differ by exactly the reservation. D110's home line: **text bottom 790, padding-box bottom 975, a
185 px gap.** Asking `boxBottom > scrollY + barTop` solved to *"needs 153 px of scroll"* on a page
whose **entire scroll range is 75 px** — i.e. it reported the line as unreachable at every scroll
position, a defect that does not exist. **The reservation is not the line; it is the empty space
that exists so the line is not sat on. Measuring it as if it were the line reports the reservation
as the failure it was added to prevent.**

**A `preserve-3d` element's own rect is one PLANE through the solid, not its hull.** `.cube`'s border
box read `top: 1.2 px` while the union of its six `.face` rects read `-16.5 px` on the same build —
the faces are what project the hull. **Derive a 3-D object's region from its faces.**

**Use the text's own `Range` rect, not the element box**, whenever a check asks whether something is
*visible* rather than whether it is *placed*. This is a distinct failure from a probe pointed at an
absent subject: **right subject, right edge-question, wrong edge of the subject.**


**A probe that asserts a mechanism it did not read is not a check — it is a coincidence.** Four
measurement errors were made against this page in one day, by two people, every one the same shape.
One was a **false pass** that let a real defect through.

| the assumption | what the page actually does |
|---|---|
| the answer is hidden with `visibility` | **`opacity: 0 → 1`**, holding its box — which is what makes the shift 0.00 px. `checkVisibility()` **ignores opacity by spec**. |
| the hit row is hidden like the answer | it is gated by **`font-weight`**. An opacity probe cannot see it leak. |
| a custom property's value is a length | `getPropertyValue` returns the **declared `clamp(...)` string**. Resolve it by applying it to a probe element. |
| a filled control is a `<button>` | the pinned bar puts the fill on the **container**, with a transparent button inside. |

Two more that mislead the same way: **`innerText` is empty inside a closed `<details>`** though its
box exists; and **a disabled control is not a faded filled one** — the treatment drops the ground.

**Tailwind 4 tree-shakes any theme variable no utility references, and this produces a confident
false reading.** A probe asking for `--color-pipred` before any component uses it gets an **empty
string**, not the value — `getPropertyValue` returns nothing, the probe inherits, and pairs come
back at exactly **1.00** as though the palette were broken. **The palette is fine; the token is not
in the built CSS yet.** To verify a token before a screen consumes it, force its emission with a
throwaway component, measure, delete it, and confirm `dist` is clean afterwards.

**And pair a flood against its `on-flood` token, not against `paper`.** Measuring the wrong partner
returned 2.33 / 1.99 where the real pairs are 7.98 / 9.31 — the page was right both times.

**A screenshot-identity test is invalid on a page with ambient motion — and this bit after the test
had already been used to prove something.** Comparing two renders by `md5`, the check that proved
the dark scheme was gone, **stopped working the moment the weather icon was added**: an animated
page never produces two byte-identical frames, so it reported a difference that was the animation
frame rather than the colour scheme. **Run scheme- and state-identity comparisons with
`reduced_motion: "reduce"`** — that stops the loops on their legible frame and leaves only the
difference under test.

**Deleting a variant prefix is a specificity change, not a no-op — and this one is aimed at the
React port, where it will happen again.** Stripping `html[data-variant="a"]` dropped a rule from
`(0,2,2)` to `(0,1,1)`, where it **lost to a `:nth-child` selector at `(0,2,1)`** that it had
previously beaten. Four equal images became **370 / 328 / 328 / 370**, two overrunning their column
by 62 px. **Visible in the render, invisible in the diff.** Every `dark:` and `data-*` prefix that
comes off during a rewrite can hand a rule to a competitor it used to outrank, silently.

**Under React, add one:** a stable hook for every part named in §4 — `data-part="bar"`,
`data-part="row"`, and so on. **Class names will change every time the styling changes; the gate
must not.**

---

## 10 · Working rules for this directory

- **There is a build step now.** After any change, rebuild the proxy image and bring it up, or you
  are looking at the old page. A stale image does not announce itself.
- **Judge the built page, not the source.** Screenshot at **430 / 900 / 1440 / 2560**. 1440 is in
  the list because it is the reference's own viewport. **One scheme — see §1.**
- **The surface's tests live outside this directory and are not yours to edit.** Send the needed
  change to whoever owns that file.
- **The rendered weight is asserted**, not assumed — see §2 on both faces defaulting to their
  thinnest instance.
