// @ts-expect-error — a Node built-in, read only by the test runner; the app's types carry no Node.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

/**
 * **Text on a flood takes the on-flood colour, never the face's on-colour.** Since look D every
 * `--color-flood-*` is one lacquer red while `--color-on-sun` stayed ink, so a sun win painted the
 * reveal's list, hint and navbar ink on red at about 2.3 (live in production until this batch).
 * `test_web_contrast.py` holds each `onflood-*` to 4.5:1 on its flood; this pins that the flood
 * rules actually USE them.
 */
const css = (f: string): string => readFileSync(new URL(f, import.meta.url), 'utf8')
const FACES = ['hot', 'cobalt', 'jade', 'sun']

describe('flood text colour', () => {
  it('the reveal flood sets each face’s on-flood colour', () => {
    const s = css('./reveal.css')
    for (const f of FACES) {
      const rule = s.match(new RegExp(`\\.reveal\\[data-face="${f}"\\]\\s*\\{ background: var\\(--color-flood-${f}\\);[^}]*\\}`))
      expect(rule, f).not.toBeNull()
      expect(rule![0]).toContain(`color: var(--color-onflood-${f})`)
    }
  })
  it('the navbar over a flood uses the on-flood colour too', () => {
    const s = css('./switcher.css')
    for (const f of FACES) {
      const rule = s.match(new RegExp(`\\.navbar:has\\(~ \\.reveal\\[data-face="${f}"\\]\\)\\s*\\{ color: [^}]*\\}`))
      expect(rule, f).not.toBeNull()
      expect(rule![0]).toContain(`var(--color-onflood-${f})`)
    }
  })
  it('no flood rule anywhere sets the face’s plain on-colour as text', () => {
    for (const f of ['./reveal.css', './switcher.css']) {
      expect(css(f)).not.toMatch(/data-face="(hot|cobalt|jade|sun)"\]\)?\s*\{ (background: var\(--color-flood-\w+\);\s*)?color: var\(--color-on-(hot|cobalt|jade|sun)\)/)
    }
  })
})
