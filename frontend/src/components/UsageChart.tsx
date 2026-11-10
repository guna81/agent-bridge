import { useState } from "react";
import { DayUsage, money, num } from "../api";

// Colour follows the provider, never its rank: built-ins have fixed slots, every custom CLI shares "other".
const SLOTS = ["claude", "agy", "codex", "gemini"];
export const seriesOf = (provider: string) => (SLOTS.includes(provider) ? provider : "other");
export const seriesVar = (series: string) => `var(--series-${series === "other" ? 5 : SLOTS.indexOf(series) + 1})`;

const W = 1000;
const H = 230;
const PAD = { l: 52, r: 8, t: 10, b: 26 };

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v) ?? 10 * p;
}

/** Stacked daily spend by provider. One axis (USD); hover or focus a day for the breakdown. */
export default function UsageChart({ days }: { days: DayUsage[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const series = [...SLOTS, "other"].filter((s) => days.some((d) => Object.keys(d.by_provider).some((p) => seriesOf(p) === s)));
  const stacks = days.map((d) => {
    const m: Record<string, number> = {};
    for (const [p, v] of Object.entries(d.by_provider)) m[seriesOf(p)] = (m[seriesOf(p)] ?? 0) + v;
    return m;
  });
  const max = niceMax(Math.max(...days.map((d) => d.cost_usd), 0));
  const iw = W - PAD.l - PAD.r;
  const ih = H - PAD.t - PAD.b;
  const step = iw / Math.max(days.length, 1);
  const bw = Math.min(36, step * 0.62);
  const y = (v: number) => PAD.t + ih - (v / max) * ih;
  const total = days.reduce((a, d) => a + d.cost_usd, 0);
  const label = (iso: string) => new Date(iso + "T00:00:00Z").toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const every = Math.ceil(days.length / 7);
  const h = hover === null ? null : days[hover];

  if (total === 0) return <div className="empty">No billed requests in this period yet.</div>;

  return (
    <div className="chart">
      {series.length > 1 && (
        <div className="legend">
          {series.map((s) => (
            <span key={s}>
              <i style={{ background: seriesVar(s) }} />
              {s === "other" ? "custom CLIs" : s}
            </span>
          ))}
        </div>
      )}
      <div className="chart-plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Daily spend by provider, last ${days.length} days, ${money(total)} in total`}>
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line x1={PAD.l} x2={W - PAD.r} y1={y(max * f)} y2={y(max * f)} className={f === 0 ? "axis" : "grid"} />
              <text x={PAD.l - 6} y={y(max * f) + 4} textAnchor="end" className="tick">
                {money(max * f)}
              </text>
            </g>
          ))}
          {days.map((d, i) => {
            const cx = PAD.l + step * i + step / 2;
            let acc = 0;
            const segs = series.filter((s) => stacks[i][s] > 0);
            return (
              <g key={d.date}>
                {segs.map((s, k) => {
                  const v = stacks[i][s];
                  const y1 = y(acc + v);
                  const hgt = Math.max(1, y(acc) - y1 - (k < segs.length - 1 ? 2 : 0)); // 2px surface gap between segments
                  acc += v;
                  const top = k === segs.length - 1;
                  return top ? (
                    <path key={s} fill={seriesVar(s)} opacity={hover === null || hover === i ? 1 : 0.45}
                      d={`M${cx - bw / 2},${y1 + hgt} v${-(hgt - Math.min(4, hgt))} q0,${-Math.min(4, hgt)} ${Math.min(4, bw / 2)},${-Math.min(4, hgt)} h${bw - 2 * Math.min(4, bw / 2)} q${Math.min(4, bw / 2)},0 ${Math.min(4, bw / 2)},${Math.min(4, hgt)} v${hgt - Math.min(4, hgt)} z`} />
                  ) : (
                    <rect key={s} x={cx - bw / 2} y={y1} width={bw} height={hgt} fill={seriesVar(s)} opacity={hover === null || hover === i ? 1 : 0.45} />
                  );
                })}
                {i % every === 0 && (
                  <text x={cx} y={H - 6} textAnchor="middle" className="tick">
                    {label(d.date)}
                  </text>
                )}
                {/* hit target is the whole column, not just the bar */}
                <rect x={PAD.l + step * i} y={PAD.t} width={step} height={ih} fill="transparent" tabIndex={0}
                  aria-label={`${label(d.date)}: ${money(d.cost_usd)}, ${d.requests} requests`}
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(i)} onBlur={() => setHover(null)} />
              </g>
            );
          })}
        </svg>
        {h && hover !== null && (
          <div className="tip" style={{ left: `${((PAD.l + step * hover + step / 2) / W) * 100}%` }} data-side={hover > days.length / 2 ? "left" : "right"}>
            <strong>{label(h.date)}</strong>
            <span>
              {money(h.cost_usd)} · {num(h.requests)} request{h.requests === 1 ? "" : "s"}
            </span>
            {series.filter((s) => stacks[hover][s] > 0).map((s) => (
              <span key={s} className="tip-row">
                <i style={{ background: seriesVar(s) }} />
                {s === "other" ? "custom CLIs" : s}
                <b>{money(stacks[hover][s])}</b>
              </span>
            ))}
            <span className="muted">
              {num(h.input_tokens)} in / {num(h.output_tokens)} out tokens
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
