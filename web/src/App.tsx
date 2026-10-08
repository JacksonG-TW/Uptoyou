import { useEffect, useState } from 'react'
import Collage from './components/home/Collage'
import WeatherIcon from './components/home/WeatherIcon'
import {
  TOWNSHIPS, fetchWeather, conditionCode, measure, fetchedLabel, type Weather,
} from './lib/weather'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { doorHref } from './lib/round'
import { CIRCLE_LINE, NO_SEAT } from './components/selfserve/copy'
import { device } from './lib/device'
import { arrive } from './lib/motion'
import { dateline } from './lib/dateline'
import { fetchPlaceCount, type PlaceCount } from './lib/places'
import { fetchMembers, readInviteRole, type Members } from './lib/selfserve'

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
  /* UX batch U1: set by `/round` when it bounced a device with no seat here. Read once and
     cleared, in the initializer so StrictMode's second render reads the same answer. */
  const [noSeat] = useState(() => {
    try {
      const v = sessionStorage.getItem('upto_no_seat') === '1'
      sessionStorage.removeItem('upto_no_seat')
      return v && !hasDevice
    } catch { return false }
  })

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
  /** The source's own count, read live (the brief: 「3 萬多家店」 must match it). `null` until it
   *  answers and on any failure — then the line names the source without a number. */
  const [places, setPlaces] = useState<PlaceCount | null>(null)
  useEffect(() => {
    let live = true
    void fetchPlaceCount().then((c) => { if (live) setPlaces(c) })
    return () => { live = false }
  }, [])

  /* **A member's home names their circle and who is in it** (the evaluator's item-1 gate,
     2026-10-08: a reader told «a friend added you yesterday» could not tell from the home that they
     were in a circle at all, nor whether 選這一餐 decides for them alone). One line above the doors,
     so the three acts read as acts on that circle. Any failure renders nothing: a key that no
     longer opens the circle is the round screen's to explain, not this line's. */
  const [circle, setCircle] = useState<Members | null>(null)
  useEffect(() => {
    const d = device()
    if (!d) return
    let live = true
    fetchMembers(d).then((m) => { if (live) setCircle(m) }).catch(() => {})
    return () => { live = false }
  }, [])

  /* **The 邀朋友加入 door is the creator's alone** (`spec-round-diet-circle-2026-10-08.md` B): only
     they can make a link, so for everyone else the door led to a page that says «ask someone
     else». The same read `/circle` uses. Not shown while the read is in flight, and not shown if
     it fails or says anything but creator (`unknown` is `/circle`'s fallback, not a reason to
     offer the door here). */
  const [isCreator, setIsCreator] = useState(false)
  useEffect(() => {
    const d = device()
    if (!d) return
    let live = true
    readInviteRole(d).then((r) => { if (live) setIsCreator(r.role === 'creator') }).catch(() => {})
    return () => { live = false }
  }, [])

  const name = TOWNSHIPS.find((t) => t.code === township)?.name ?? ''
  const hour = weather?.hour?.slice(11, 16) ?? ''
  const fetched = fetchedLabel(weather)

  return (
    <>
      {/* **Home's first view holds one act and six pieces of our own text** — the attention
          principle the owner ruled on 2026-10-08 and the budget agreed with the evaluator
          (`idea & img/frontend/specs/spec-nav-labels-home-2026-10-08.md` N3). Everything a person
          does not need to start — the weather, the date, the sources — sits below the first view,
          still on this page and still this page's alone (D20). No bar here: the doors are the
          navigation, and a bar repeated 這一餐 beside the door that said it. */}
      <div className="col">
        <header className="mast" data-part="masthead">
          <div className="brand"><b>由你決定</b></div>
        </header>
        <div className="hero">
          <div className="heroL">
            <h1 className="headline arrive" style={arrive(1)} data-part="headline">
              <span>今天吃什麼</span><span className="lit">讓骰子決定</span>
            </h1>
            {/* How, and how it feels after (the brief: 輕鬆，沒有人為難). For a stranger only — a
                seated person has done it once, and their three doors use the budget. */}
            {!hasDevice && (
              <p className="say arrive" style={arrive(1)} data-part="bodyline">
                大家各自提店，骰子擲一次就定案，沒有人要當壞人。
              </p>
            )}
            {/* **The filled door is the act this person came for** (`data-primary`): a stranger
                opens a circle; a seated member picks this meal. Labels say what happens on the
                other side (N2): 選這一餐 where 這一餐 named a page, 邀朋友加入 where 找人進來 read
                as «join someone's». `/circle` and `/create` keep their ruled reasons — the invite
                link is reachable after the create flow (SS-13), and a seated person may leave for
                another circle, which the next screen's notice explains. */}
            {hasDevice && circle && circle.members.length > 0 && (
              <p className="circleLine yourCircle" data-part="your-circle">
                {circle.name
                  ? <>你在「<b data-user-content>{circle.name}</b>」，一起的人：</>
                  : <>你在這個圈子，一起的人：</>}
                <span data-user-content>{circle.members.map((m) => m.nickname).join('、')}</span>
              </p>
            )}
            <div className="act-row homeAct">
              {hasDevice ? (
                <>
                  {/* 「一起」 since the member-home gate (2026-10-08): with the circle named above
                      it, both readers still asked 「是不是只有我自己抽？」. The bar keeps 選這一餐. */}
                  <a className="act" data-part="enter" data-primary href={doorHref()}>一起選這一餐</a>
                  {isCreator && (
                    <a className="act actMinor" data-part="circle-invite" href="/circle">邀朋友加入</a>
                  )}
                  <a className="act actMinor" data-part="create-circle" href="/create">開一個圈子</a>
                </>
              ) : (
                <a className="act" data-part="create-circle" data-primary href="/create">開一個圈子</a>
              )}
            </div>
            {/* What a 圈子 is — the word the cold reader could only guess (N2). After a bounce from
                `/round` the same place says where circles come from instead (U1). */}
            {!hasDevice && (
              noSeat
                ? <p className="circleLine" data-part="no-seat" role="status">{NO_SEAT}</p>
                : <p className="circleLine" data-part="circle-line">{CIRCLE_LINE}</p>
            )}
          </div>
          <div className="heroR arrive" style={arrive(2)}><Collage /></div>
        </div>
      </div>

      {/* ── below the first view: today's conditions, then where every fact came from ────── */}
      <section className="today" data-part="today">
        {/* 甲's dateline, without its edition word (早報／午報／晚報 — noise to the cold reader, and
            the brief's voice is a friend, not a paper). `dateline.ts` still owns the 節氣 rule: a
            blank is true and a wrong term is not. */}
        <p className="dateline" data-part="dateline">
          {sheet.date}{' · '}<b>{sheet.weekday}</b>
          {sheet.term !== null && <>{' · '}{sheet.term}</>}
        </p>
        <div className="wxHead">
          <h2 className="todayH">今天的天氣</h2>
          {/* Labelled as what it changes (the weather's district), which the cold reader could not
              tell from 「中山區 ▾」 beside a collage of shops. */}
          <Select value={township} onValueChange={setTownship}>
            <SelectTrigger data-part="picker" aria-label="選擇天氣的行政區">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {TOWNSHIPS.map((t) => (
                <SelectItem key={t.code} value={t.code}>{t.name}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="wx" data-part="weather">
          {error ? (
            <p className="wxnow"><span className="c">{error}</span></p>
          ) : weather?.kind === 'absent' ? (
            /* UX batch U4 — no observation and no forecast for this hour: one sentence, not dashes. */
            <p className="wxnow" data-part="weather-absent"><span className="c">現在拿不到{name}的天氣。</span></p>
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
          {weather?.kind !== 'absent' && <p className="wxsrc" data-part="weather-source">
            <span className="where">{name}{hour && ` ${hour}`} · </span>
            {weather?.kind === 'observation' ? '觀測' : '預報'}
            {' · 中央氣象署開放資料'}
            {fetched && ` · ${fetched}`}
          </p>}
        </div>

        {/* 甲's colophon: where every fact on this page came from. The shop count left the
            collage (the cold reader read 「家在冊」 as noise) and lives here as what it is — the
            size of a source, with the source's own date. **Read live, never written into the
            page** (`GET /api/places/count`): the literal 36,499 was August's first file and wrong
            on production. No answer → no number. */}
        <footer className="colophon" data-part="colophon">
          <span className="u" data-part="place-count"><b>店家</b>衛福部 食品業者登錄
            {places && <>{' '}{places.count.toLocaleString('en-US')} 家（{places.asOf}）</>}
          </span>
          <span className="u"><b>天氣</b>中央氣象署 開放資料</span>
          <span className="u"><b>招牌與品牌</b>臺北市政府 開放資料</span>
          <span className="u"><b>營業狀態</b>經濟部 商工登記</span>
        </footer>
      </section>
    </>
  )
}
