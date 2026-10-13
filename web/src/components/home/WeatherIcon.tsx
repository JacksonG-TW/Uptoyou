/**
 * The condition icon — five states keyed to the CWA codes our forecast data actually contains
 * (01 晴 · 04 多雲 · 07 陰 · 08 短暫陣雨 · 15 雷雨), verified against the current publication.
 *
 * Driven by `weather_code` and never by `weather_text`, and that is not a preference: code 15
 * publishes under two different strings (短暫陣雨或雷雨 and 午後短暫雷陣雨), so a text map is
 * many-to-one and open-ended while a code map is one-to-one and closed at five. 15 is also the
 * most common condition in the current publication.
 *
 * `code` is string | null | undefined by design — the forecast half carries the key (a value or
 * null), the observation half has no code element at all, so the key is absent. All three render
 * nothing and the box holds its size; the strip's icon box is a sized element, not a shrink-wrap.
 */
export default function WeatherIcon({ code }: { code?: string | null }) {
  return (
    <span className="wxicon" aria-hidden="true">
      {code === '01' && (
        <svg viewBox="0 0 64 64">
          <circle className="halo" cx="32" cy="32" r="22" fill="var(--color-sun)" opacity=".5" />
          <g className="rays" stroke="var(--color-sun)" strokeWidth="3.5" strokeLinecap="round">
            <line x1="32" y1="2" x2="32" y2="10" /><line x1="32" y1="54" x2="32" y2="62" />
            <line x1="2" y1="32" x2="10" y2="32" /><line x1="54" y1="32" x2="62" y2="32" />
            <line x1="11" y1="11" x2="16.6" y2="16.6" /><line x1="47.4" y1="47.4" x2="53" y2="53" />
            <line x1="11" y1="53" x2="16.6" y2="47.4" /><line x1="47.4" y1="16.6" x2="53" y2="11" />
          </g>
          <circle cx="32" cy="32" r="13" fill="var(--color-sun)" stroke="var(--color-ink)" strokeWidth="2.5" />
        </svg>
      )}
      {code === '04' && (
        <svg viewBox="0 0 64 64">
          <g className="rays" stroke="var(--color-sun)" strokeWidth="3" strokeLinecap="round"
             style={{ transformOrigin: '24px 24px' }}>
            <line x1="24" y1="2" x2="24" y2="8" /><line x1="2" y1="24" x2="8" y2="24" />
            <line x1="8" y1="8" x2="12.5" y2="12.5" /><line x1="40" y1="8" x2="35.5" y2="12.5" />
          </g>
          <circle cx="24" cy="24" r="11" fill="var(--color-sun)" stroke="var(--color-ink)" strokeWidth="2.5" />
          <g className="cloud"><Cloud /></g>
        </svg>
      )}
      {code === '07' && (
        <svg viewBox="0 0 64 64">
          <g className="cloud2" opacity=".55">
            <path d="M14 36c-4 0-7.5-3.4-7.5-7.5S10 21 14 21c1-4.2 4.8-7 9.2-7 5.2 0 9.5 4 9.8 9.1 3.4.5 6 3.4 6 6.9 0 3.9-3.2 6.9-7 6.9H14z"
                  fill="var(--color-muted)" stroke="var(--color-ink)" strokeWidth="2.5" strokeLinejoin="round" />
          </g>
          <g className="cloud">
            <path d="M22 50c-5.5 0-10-4.5-10-9.5s4.5-9.5 10-9.5c1.3-5.5 6.3-9.5 12.2-9.5 6.9 0 12.6 5.3 13 12.1 4.4.7 8 4.5 8 9 0 5.2-4.2 9.4-9.4 9.4H22z"
                  fill="var(--color-paper)" stroke="var(--color-ink)" strokeWidth="2.5" strokeLinejoin="round" />
          </g>
        </svg>
      )}
      {code === '08' && (
        <svg viewBox="0 0 64 64">
          <g className="cloud"><Cloud /></g>
          <g stroke="var(--color-cobalt)" strokeWidth="3" strokeLinecap="round">
            <line className="drop" x1="23" y1="46" x2="21" y2="52" />
            <line className="drop" x1="33" y1="46" x2="31" y2="52" />
            <line className="drop" x1="43" y1="46" x2="41" y2="52" />
          </g>
        </svg>
      )}
      {code === '15' && (
        <svg viewBox="0 0 64 64">
          <g className="cloud"><Cloud /></g>
          <g stroke="var(--color-cobalt)" strokeWidth="3" strokeLinecap="round">
            <line className="drop" x1="22" y1="44" x2="20" y2="50" />
            <line className="drop" x1="44" y1="44" x2="42" y2="50" />
          </g>
          <path className="bolt" d="M34 40l-7 11h6l-2 9 9-12h-6l2-8z" fill="var(--color-sun)"
                stroke="var(--color-ink)" strokeWidth="2" strokeLinejoin="round" />
        </svg>
      )}
    </span>
  )
}

function Cloud() {
  return (
    <path d="M20 46c-5 0-9-4-9-8.5s4-8.5 9-8.5c1.2-5 5.7-8.5 11-8.5 6.2 0 11.3 4.8 11.7 10.9 4 .6 7.3 4 7.3 8.1 0 4.7-3.8 8.5-8.5 8.5H20z"
          fill="var(--color-paper)" stroke="var(--color-ink)" strokeWidth="2.5" strokeLinejoin="round" />
  )
}
