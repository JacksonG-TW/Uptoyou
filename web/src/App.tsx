import { useEffect, useState } from 'react'
import Collage from './components/home/Collage'
import WeatherIcon from './components/home/WeatherIcon'
import {
  TOWNSHIPS, fetchWeather, conditionCode, measure, fetchedLabel, type Weather,
} from './lib/weather'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { device, doorHref } from './lib/round'
import { arrive } from './lib/motion'
import Switcher from './components/Switcher'   // demo scaffolding — the masthead's nav
import { dateline } from './lib/dateline'

/**
 * The home entry — appetite, per the owner's ruling that the 36-cell mechanism does not belong
 * here. Built against the approved comparison page; the numbers live in `home.css` beside the
 * declarations they came from.
 *
 * D20 binds: the weather STATES and never advises, and it appears on this screen and no other.
 * D94 binds: no restaurant name on the home.
 */
export default function App() {
  const [township, setTownship] = useState('63000040')   // 中山區, the demo circle's district
  const [weather, setWeather] = useState<Weather | null>(null)
  const [error, setError] = useState('')
  /* `device()` rather than two `getItem`s: the same helper the rest of the surface uses to answer
     "is this browser a seat", so the door and the screens cannot disagree about what a key is. */
  const hasDevice = Boolean(device())

  useEffect(() => {
    let live = true
    const load = () => fetchWeather(township)
      .then((w) => { if (live) { setWeather(w); setError('') } })
      // the API's own detail, never a sentence invented here: a wrong reason on screen is worse
      // than a blunt one
      .catch((e: Error) => { if (live) { setWeather(null); setError(e.message || '連不上 API') } })
    load()
    // the forecast republishes about every six hours and the observation hourly, so a five-minute
    // poll is already far more often than the data can change; it exists so the hour rolls over
    const t = window.setInterval(load, 5 * 60 * 1000)
    return () => { live = false; window.clearInterval(t) }
  }, [township])

  /** 甲・日報 §1 — **computed once, on mount, and never again.** The initialiser form is the
   *  ruling: a sheet printed at 16:59 does not become the evening edition while you look at it,
   *  so there is no interval here and nothing to tear down. */
  const [sheet] = useState(dateline)

  const name = TOWNSHIPS.find((t) => t.code === township)?.name ?? ''
  const hour = weather?.hour?.slice(11, 16) ?? ''
  const fetched = fetchedLabel(weather)

  return (
    <>
      <div className="col">
        <header className="mast" data-part="masthead">
          <div className="brand"><b>由你決定</b><span>Up to you</span></div>
          {/* **甲・日報's dateline** (`spec-home-dateline.md` §1, evaluator 2026-08-26; owner ruled
              甲 alone from the rendered three-way). Four segments, every one of them a statement
              of fact — D20's register, which is why this layer won over crop marks and category
              chips: furniture asserts nothing, and a date does.

              **The solar term is allowed to be absent** and renders three segments and two dots
              when it is. `dateline.ts` returns `null` for a year it has not sourced; a blank is
              true and a wrong 節氣 is not. Nothing here decides that — the module does, so the
              rule lives beside the table it guards.

              Text nodes, not `dangerouslySetInnerHTML` (H7): the `<b>` the spec asks for around
              the weekday is markup here rather than a string carrying tags. */}
          <p className="dateline" data-part="dateline">
            {sheet.date}{' · '}<b>{sheet.weekday}</b>
            {sheet.term !== null && <>{' · '}{sheet.term}</>}
            {' · '}{sheet.edition}
          </p>
          <Select value={township} onValueChange={setTownship}>
            <SelectTrigger className="arrive" style={arrive(3)} data-part="picker" aria-label="選擇行政區">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TOWNSHIPS.map((t) => (
                <SelectItem key={t.code} value={t.code}>{t.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* **乙・報頭內** (`spec-round-menu-2026-09-03.md` §3; owner-ruled 軸二, reversing ⑥ of
              2026-08-20). Last child, so it lands past the picker — the order the evaluator fixed
              under D101's delegation is brand · dateline · picker · switcher, and the dateline and
              the picker stay adjacent because both are 「今天的條件」.

              **It is allowed to wrap and is never sized from its link count.** Three links measure
              188 px and four do once 開獎 exists, so a rule that forced one row would break itself
              the first time a round was open. At 1440 and 2560 all four children share the row and
              the masthead's height is unchanged, which is what A0c reads; at ≤ 900 the switcher
              takes its own row inside the bar and that is the ruled behaviour, not a defect. */}
          <Switcher />
        </header>

        <div className="hero">
          <div className="heroL">
            {/* 乙 §2 — 首頁's four arriving blocks, in the ORDER THE SPEC GIVES: the weather
                line (0) · the appetite block (1) · the collage (2) · the picker (3). Four blocks,
                720 ms, done — nothing else on this screen arrives, which is what keeps it inside
                §1a rule 4's one beat.

                **The appetite block is three siblings sharing one step, not a new wrapper.** The
                eyebrow, the headline and the body line are separate children of `.heroL` (the
                weather line is a fourth), so 「one block」 is expressed as one step rather than as a
                `<div>` — a wrapper would be a DOM change on the one screen whose settled frame is
                pinned pixel-for-pixel by `A0c` (`YI-1`), and it would buy nothing the shared step
                does not. */}
            <p className="eyebrow arrive" style={arrive(1)} data-part="badge"><em>★</em>臺北市 12 區 · 全部來自公開登記資料</p>
            <h1 className="headline arrive" style={arrive(1)} data-part="headline">
              <span>今天吃什麼</span><span className="lit">讓骰子決定</span>
            </h1>
            {/* **「各自提店」, not 「一人提一家」 — a contradiction on this very screen** (evaluator,
                from the 2026-08-20 re-gate shots at 1440 and 2560). The lead said one place each
                while the shape line 40 px below it says 每人最多提 3 家店. Same screen, two rules.
                D110 already fixed exactly this on the round screen; the home kept the old wording.

                **The lead now states the shape without a number and lets the cap line own it.**
                Naming 3 twice would be the other failure — a page repeating its own limit reads as
                a page arguing with itself, and the cap belongs where the refusal is explained.
                Rhythm and length are unchanged, so the type block does not move.

                `擲` is left alone: D108's question about that verb is open on this line as on the
                round's note, and answering it here would be improvising a ruling. */}
            <p className="say arrive" style={arrive(1)} data-part="bodyline">
              各自提店，權重一次算清，兩顆骰子擲一次就定案。沒有人要先犧牲，也沒有人要當壞人。
            </p>

            <div className="wx arrive" style={arrive(0)} data-part="weather">
              {error ? (
                <p className="wxnow"><span className="c">{error}</span></p>
              ) : (
                <>
                  <p className="wxnow">
                    <WeatherIcon code={conditionCode(weather)} />
                    <span className="t">{measure(weather, 'temperature_c')}<span>°C</span></span>
                    <span className="c">{measure(weather, 'weather_text')}</span>
                  </p>
                  <div className="wxstrip">
                    <span className="u"><span className="k">體感</span>
                      <span className="v">{measure(weather, 'apparent_temperature_c')}°C</span></span>
                    <span className="u"><span className="k">降雨機率</span>
                      <span className="v">{measure(weather, 'rain_probability_pct')}%</span></span>
                    <span className="u"><span className="k">相對濕度</span>
                      <span className="v">{measure(weather, 'humidity_pct')}%</span></span>
                  </div>
                </>
              )}
              {/* provenance is kept and demoted, never removed — it is the claim itself */}
              {/* **Four facts, and the fourth was missing.** The approved page reads
                  「中山區 17:00 · 預報 · 中央氣象署開放資料 · 今天 14:00 取得」 and the build
                  stopped at the source's name — so the line said where the reading is for and who
                  published it, and never when we went and got it. At 900 that cost a wrapped line
                  and 22 px of block height against the reference, which is how it surfaced; the
                  reason to fix it is not the 22 px. `time_label` is the API's own word for which
                  clock `detected_at` is on. */}
              <p className="wxsrc" data-part="weather-source">
                <span className="where">{name}{hour && ` ${hour}`} · </span>
                {weather?.kind === 'observation' ? '觀測' : '預報'}
                {' · 中央氣象署開放資料'}
                {fetched && ` · ${fetched}`}
              </p>
            </div>
          </div>

          {/* The collage's own 10 s swap and the halo's 5 s pulse start at rest and are
              untouched — §1a rule 8, and `YI-9` asserts the ambient set is still the same six
              periods. */}
          <div className="heroR arrive" style={arrive(2)}><Collage /></div>
        </div>

        {/* **The foot — footnote + act as one group, INSIDE the column** (甲's change 1a,
            owner-ruled 2026-08-20 night from the rendered three-way; `spec-home-wide.md`).

            These two were siblings of `.col` in ordinary flow below it until tonight, each
            carrying its own copy of the column's width. That is what produced the dead bands the
            owner screenshotted on a 27-inch monitor: the hero centred alone inside the column
            while the foot sat outside it, so at 2560×1440 the act landed 1,365 px down. Inside
            the flex column, `.hero { margin-top: auto }` and `.homeFoot { margin-bottom: auto }`
            split the slack and the two centre together as one object.

            **The wrapper is what makes them one group.** Two independent `margin-bottom: auto`
            siblings would each claim the slack and the footnote would drift off the act. */}
        <div className="homeFoot">

        {/* **D110 — the supported shape, stated on the home page** (owner-ruled 2026-08-19).
            It used to sit BELOW the approved frame rather than inside it, so that it added a line
            without moving one — that reasoning retired with 甲, which moved the whole foot into the
            column and made the built page the new baseline (`spec-home-wide.md` §3).

            **The shape, never the reason.** A circle holds twelve and a person proposes three; the
            36 pairs underneath are the arithmetic that produced those two numbers and they are ours,
            not the reader's — a home page that explained itself would be teaching the mechanism the
            owner already ruled off this screen. D20's register holds: it says what a circle holds,
            never what anyone should do about it.

            Both limits are enforced, and this line is why neither refusal is a surprise — the 11th
            seat is refused at join and the 4th place at propose, and a person who read this knows
            before they hit either. */}
        <p className="shape" data-part="shape">
          一個圈子最多 10 人，每人最多提 3 家店。
        </p>

        {/* **The act, inline — owner-ruled 2026-08-20, option 乙.** The pinned BAR is retired. One
            filled control, and its label follows device state: a person with no key would otherwise
            land on a home whose only primary action points where they cannot go.

            It sits directly under the supported-shape line, which is the last thing the home says
            before it asks for something — the sentence answers *can I use this?* and the act is
            *then start*.

            **It is an `<a>`, not a `<button>` — conditional routing, 2026-08-21**
            (`spec-conditional-routing.md`). Until now it carried no handler and went nowhere; it
            now carries a destination computed from two local facts, and a destination belongs in
            an `href` so middle-click, open-in-new-tab and the status bar all tell the truth —
            Back.tsx's argument, applied to the door.

            **The label still follows device state, deliberately**: `貼上鑰匙` without a key is the
            honest door, because the press is about to ask for one. A fixed 這一餐 (the flow map's
            wording) promises a meal and delivers a form.

            `doorHref()` reads `localStorage` only, so it is safe during render and the markup is
            right on the first paint rather than after an effect. The box must not move — the act's
            fidelity at 1440 and 2560 is gated (G10) and `.act` already styles an inline-block. */}
        <div className="act-row homeAct">
          <a className="act" data-part="enter" href={doorHref()}>
            {hasDevice ? '這一餐' : '貼上鑰匙'}
          </a>
        </div>
        </div>

        {/* **甲・日報's colophon** (`spec-home-dateline.md` §2) — the foot names where every fact
            on this page came from. It sits AFTER `.homeFoot` and still inside `.col`, which is
            what keeps 甲's centring intact: `.homeFoot { margin-bottom: auto }` goes on splitting
            the slack, and the colophon rides at the very bottom of the sheet like a printed one.

            **Only what has been checked is named.** The spec dropped the cadence words (每日核對 ·
            逐時 · 每月) for want of a measured number and dropped the 家在冊 count because the
            collage already carries it — one literal per number. The 招牌與品牌 line differs from
            the spec on the same principle and against measurement: `api_common.compose_names`
            takes the sign from `storefront.name` (`ingest/gradelist.py`, 臺北市餐飲衛生分級評核)
            and the brand from `brand.brand_name` (`ingest/foodtracer.py`, 臺北市食材登錄平台),
            both data.taipei publications — 財政部's 稅籍登錄 (`ingest/fia.py`, D85) reaches no
            displayed name today. So this says 臺北市政府 開放資料, which is what the two names are.
            Reported to the evaluator to rule; the wording is theirs, the measurement is why. */}
        <footer className="colophon" data-part="colophon">
          <span className="u"><b>店家</b>衛福部 食品業者登錄</span>
          <span className="u"><b>天氣</b>中央氣象署 開放資料</span>
          <span className="u"><b>招牌與品牌</b>臺北市政府 開放資料</span>
          <span className="u"><b>營業狀態</b>經濟部 商工登記</span>
        </footer>
      </div>
    </>
  )
}
