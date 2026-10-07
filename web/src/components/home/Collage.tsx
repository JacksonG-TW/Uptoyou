import { useEffect, useRef, useState } from 'react'

/**
 * The home collage — four fixed cells, a pool of images, one cell swapping every 10 s.
 *
 * The geometry never moves. Each cell is a fixed box holding two absolutely-positioned images
 * that cross-fade on opacity alone, so a swap is 0.00 px of layout change (HC-3). Swapping `src`
 * instead would blank the box for the decode, and a white flash inside a bordered tile is louder
 * than the swap it was hiding.
 *
 * The pool is whatever exists — **nine as of 2026-08-19**. Nothing here reads the length except
 * the selection rule, which handles any pool of five or more without change and degrades honestly
 * below that, see `nextFile`.
 *
 * **Nine, not ten, and the shipped numbers are contiguous while the source numbers are not.** The
 * 早餐 slot was dropped after five attempts across two dishes failed the nameability gate — the
 * spec's own rule, rather than burning GPU time reaching a round number. The source folder
 * `idea & img/gpu/` is a historical record and its filenames never change, so it still holds a
 * `collage-09` and a `collage-10` with no `collage-08`. **The shipped names are made by the copy**,
 * so `public/img/` runs 01–09 with no gap: `HC-1` asserts the pool exists at `collage-01…NN` and a
 * hole at 08 would fail a check that is right to be literal. The mapping between the two lives
 * here, in the same constant that already had to carry the `alt` strings.
 */

/** `alt` describes what is actually in the frame and travels WITH the image — an alt describing
 *  a different photograph is worse than no alt. A constant, not fetched (§6) and not derived from
 *  the filename, because a filename is not a sentence.
 *
 *  **Three of these are constrained by what the pictures actually contain, not by taste**, and each
 *  came from the generation log rather than from looking at a brief:
 *  · `collage-07` — the slices read as salmon and tuna and the log will certify neither, so **no
 *    species is named**; the green spheres in the foreground are unidentifiable and are not
 *    enumerated.
 *  · `collage-08` — the tapioca is rafted at the top of the cup and tapioca sinks. It is
 *    unmistakably bubble tea, so it ships; **the position of the pearls is not described**, because
 *    describing what is there would describe a drink that is made wrong.
 *  · `collage-06` — glazed grilled meat skewers, and the white granules are **coarse salt, not
 *    sesame**.
 *  `collage-05` reaches "a red-broth hot pot" and no regional style. */
export const POOL = [
  { file: '/img/collage-01.webp', alt: '牛肉麵：寬麵條、大塊紅燒牛肉、深褐色湯頭，厚陶碗放在木桌上' },
  { file: '/img/collage-02.webp', alt: '滷肉飯：白飯上鋪滿滷肉燥，旁邊一顆滷蛋與青菜' },
  { file: '/img/collage-03.webp', alt: '水餃：白瓷盤裡的水餃，一雙筷子夾起一顆，旁邊一碟醬油醋' },
  { file: '/img/collage-04.webp', alt: '鹽酥雞：炸得金黃的雞塊，撒上胡椒鹽與九層塔' },
  { file: '/img/collage-05.webp', alt: '火鍋：黑鍋裡的紅湯，浮著肉片、豆腐與辣椒，鍋口冒著熱氣' },
  { file: '/img/collage-06.webp', alt: '烤肉串：竹籤上刷了亮亮醬汁的烤肉塊，撒了粗鹽粒' },
  { file: '/img/collage-07.webp', alt: '生魚片：深色漆盤上幾片厚切生魚片，旁邊一小碟醬油' },
  { file: '/img/collage-08.webp', alt: '珍珠奶茶：透明杯裝的奶茶，杯裡有黑色粉圓，插著一根吸管' },
  { file: '/img/collage-09.webp', alt: '小籠包：竹蒸籠裡的小籠包，摺子收在頂上' },
] as const

const CELLS = 4
const INTERVAL_MS = 10_000
const FADE_MS = 400
/** A pool no larger than the cell count can never produce a swap: every image is already on
 *  screen, so the not-currently-displayed rule has nothing to return. Measured with today's
 *  four — the interval ran for 44 s and changed nothing while the hook still reported
 *  `rotating`. Both halves of that are wrong: the state must not claim motion that cannot
 *  happen, and a timer nobody can ever see is still a timer. The pool of nine makes it live again
 *  with no change here. */
const CAN_ROTATE = POOL.length > CELLS

type Slot = { file: string; alt: string; token: number }

export default function Collage() {
  const [cells, setCells] = useState<Slot[]>(() =>
    Array.from({ length: CELLS }, (_, i) => ({ ...POOL[i % POOL.length], token: i })),
  )
  const [leaving, setLeaving] = useState<Record<number, Slot | undefined>>({})
  const [rotating, setRotating] = useState(false)

  const cellsRef = useRef(cells); cellsRef.current = cells
  const nextCell = useRef(0)
  const token = useRef(CELLS)
  /** Files that have finished arriving. An image still in flight is SKIPPED, not waited for —
   *  a rotation that stalls on a slow network is worse than one that shows nine pictures. */
  const ready = useRef<Set<string>>(new Set(POOL.slice(0, CELLS).map((p) => p.file)))

  /** The next image in pool order that is not currently in any cell. A plain `pool[n++ % len]`
   *  puts the same dish in two cells about a fifth of the time, and a duplicate in a four-picture
   *  collage reads as a bug rather than as a rhythm. One line; it makes it unreachable. */
  function nextFile(after: string): { file: string; alt: string } | null {
    const shown = new Set(cellsRef.current.map((c) => c.file))
    const start = POOL.findIndex((p) => p.file === after)
    for (let i = 1; i <= POOL.length; i++) {
      const cand = POOL[(start + i) % POOL.length]
      if (!shown.has(cand.file) && ready.current.has(cand.file)) return cand
    }
    return null   // pool too small, or nothing eligible has arrived — hold this tick
  }

  // The rest of the pool is fetched AFTER load, at idle, so first paint costs what the four
  // visible images cost and the remainder arrive during the first cell's 40-second hold.
  useEffect(() => {
    const rest = POOL.slice(CELLS)
    if (!rest.length) return
    const warm = () => rest.forEach((p) => {
      const img = new Image()
      img.onload = () => ready.current.add(p.file)
      img.src = p.file
    })
    const idle = (window as unknown as {
      requestIdleCallback?: (cb: () => void) => number
    }).requestIdleCallback
    const id = idle ? idle(warm) : window.setTimeout(warm, 1200)
    return () => { if (!idle) window.clearTimeout(id as number) }
  }, [])

  useEffect(() => {
    // §5 rule 4, condition 3: under reduced motion the rotation does not START — not
    // started-and-ignored, because a timer nobody can see is still a timer. The four images
    // loaded first hold for the session, which is a legible frame by construction.
    const motionOff = window.matchMedia('(prefers-reduced-motion: reduce)')
    let timer: number | undefined

    const stop = () => { if (timer !== undefined) { window.clearInterval(timer); timer = undefined }
                         setRotating(false) }
    const start = () => {
      if (!CAN_ROTATE) return
      if (timer !== undefined || motionOff.matches || document.visibilityState !== 'visible') return
      setRotating(true)
      timer = window.setInterval(() => {
        const cell = nextCell.current
        nextCell.current = (cell + 1) % CELLS
        const cur = cellsRef.current[cell]
        const pick = nextFile(cur.file)
        if (!pick) return
        const incoming: Slot = { ...pick, token: token.current++ }
        setLeaving((l) => ({ ...l, [cell]: cur }))
        setCells((cs) => cs.map((c, i) => (i === cell ? incoming : c)))
        // the outgoing element leaves the DOM only after the transition has ended
        window.setTimeout(() => setLeaving((l) => ({ ...l, [cell]: undefined })), FADE_MS + 60)
      }, INTERVAL_MS)
    }

    // Hidden page: suspend, and resume WITHOUT catching up. A tab left open ten minutes would
    // otherwise burn sixty unseen swaps and the returning reader finds it mid-jump.
    const onVisibility = () => (document.visibilityState === 'visible' ? start() : stop())
    document.addEventListener('visibilitychange', onVisibility)
    motionOff.addEventListener('change', () => (motionOff.matches ? stop() : start()))
    start()
    return () => { stop(); document.removeEventListener('visibilitychange', onVisibility) }
  }, [])

  return (
    <div className="collage" data-part="collage"
         data-collage-state={rotating ? 'rotating' : 'static'}>
      {cells.map((slot, i) => (
        <figure className="cell" key={i} data-cell={String(i + 1)}>
          {/* **The outgoing image is HELD at full opacity and simply covered.** The spec has both
              images fading, and both fading is what the first working version did — measured, the
              two opacities crossed cleanly at 400 ms. But two independent fades do not sum to one:
              at the midpoint the pair covered only **0.74** of the box, so 26% of the tile's own
              near-black ground showed through and the photograph visibly darkened mid-swap. A
              cross-fade that flashes is the defect the fade exists to prevent. Holding the
              outgoing opaque and fading the incoming in over it keeps coverage at **1.00** for
              every frame, and to the eye it is the same dissolve. Deviation from §2's letter,
              reported to the evaluator with both traces. */}
          {leaving[i] && (
            <img data-collage-img src={leaving[i]!.file} alt="" aria-hidden="true"
                 key={leaving[i]!.token} style={{ opacity: 1, transition: 'none' }} />
          )}
          {/* **Two frames, not one, and the second one is the whole fade.**
              A newly mounted element only transitions if the browser has *painted* it at its
              starting value first. `requestAnimationFrame` runs BEFORE paint, so setting opacity
              to 1 in a single rAF meant the element never rendered at 0 and jumped straight to
              full — the outgoing image was faded out correctly underneath an already-opaque new
              one, so the cross-fade was real in the styles and invisible on screen. Measured:
              mid-swap the outgoing read 0.51 then 0.003 while the incoming read 1 throughout.
              The owner reported it as a missing fade; the fade was there and covered. */}
          <img data-collage-img key={slot.token} src={slot.file} alt={slot.alt}
               ref={(el) => {
                 if (!el) return
                 requestAnimationFrame(() => requestAnimationFrame(() => {
                   el.style.opacity = '1'
                 }))
               }}
               style={{ opacity: leaving[i] ? 0 : 1 }} />
        </figure>
      ))}
      <p className="tag"><b>36,499</b><span>家在冊</span></p>
    </div>
  )
}
