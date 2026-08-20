import { useEffect, useState } from 'react'
import Collage from './components/home/Collage'
import WeatherIcon from './components/home/WeatherIcon'
import {
  TOWNSHIPS, fetchWeather, conditionCode, measure, fetchedLabel, type Weather,
} from './lib/weather'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

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
  const hasDevice = Boolean(localStorage.getItem('upto_token') && localStorage.getItem('upto_circle'))

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

  const name = TOWNSHIPS.find((t) => t.code === township)?.name ?? ''
  const hour = weather?.hour?.slice(11, 16) ?? ''
  const fetched = fetchedLabel(weather)

  return (
    <>
      <div className="col">
        <header className="mast" data-part="masthead">
          <div className="brand"><b>由你決定</b><span>Up to you</span></div>
          <Select value={township} onValueChange={setTownship}>
            <SelectTrigger data-part="picker" aria-label="選擇行政區">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TOWNSHIPS.map((t) => (
                <SelectItem key={t.code} value={t.code}>{t.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </header>

        <div className="hero">
          <div className="heroL">
            <p className="eyebrow" data-part="badge"><em>★</em>臺北市 12 區 · 全部來自公開登記資料</p>
            <h1 className="headline" data-part="headline">
              <span>今天吃什麼</span><span className="lit">讓骰子決定</span>
            </h1>
            <p className="say" data-part="bodyline">
              一人提一家，權重一次算清，兩顆骰子擲一次就定案。沒有人要先犧牲，也沒有人要當壞人。
            </p>

            <div className="wx" data-part="weather">
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

          <div className="heroR"><Collage /></div>
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
            *then start*. */}
        <div className="act-row homeAct">
          <button type="button" className="act" data-part="enter">
            {hasDevice ? '這一餐' : '貼上鑰匙'}
          </button>
        </div>
        </div>
      </div>
    </>
  )
}
