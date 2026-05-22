/**
 * MarketPosition — two presentation components:
 *  • <MarketPositionBadge mp={...} />   small pill, used in lists/tables
 *  • <MarketPositionBar mp={...} />     full visual range with median + my marker
 *
 * Both expect the same `market_position` object the backend returns:
 *   { rank, total_sellers, my_price, min_price, max_price, median_price,
 *     percentile, is_cheapest, is_most_expensive, below_median, above_median,
 *     tag, sellers: [{store_name, price, is_mine, rank}, ...] }
 *
 * Color/tag mapping (per spec):
 *   - cheapest         → teal/green
 *   - below_median     → teal/green
 *   - median           → neutral
 *   - above_median     → amber/warning
 *   - most_expensive   → amber/warning (darker)
 */

const TAG_STYLES = {
  cheapest: { bg: "rgba(16,185,129,0.18)", border: "rgba(16,185,129,0.55)", color: "#10B981", label: "Cheapest" },
  below_median: { bg: "rgba(30,152,142,0.16)", border: "rgba(30,152,142,0.5)", color: "#6AC1B5", label: "Below median" },
  median: { bg: "rgba(161,228,219,0.10)", border: "rgba(161,228,219,0.35)", color: "#A1E4DB", label: "At median" },
  above_median: { bg: "rgba(251,191,36,0.16)", border: "rgba(251,191,36,0.5)", color: "#FBBF24", label: "Above median" },
  most_expensive: { bg: "rgba(245,158,11,0.20)", border: "rgba(245,158,11,0.6)", color: "#F59E0B", label: "Most expensive" },
};

function ordinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

export function MarketPositionBadge({ mp, className = "", testIdPrefix = "market-pos" }) {
  if (!mp || !mp.total_sellers || mp.total_sellers < 2) return null;
  const style = TAG_STYLES[mp.tag] || TAG_STYLES.median;
  let label;
  if (mp.is_cheapest) label = `Cheapest of ${mp.total_sellers}`;
  else if (mp.is_most_expensive) label = `Most expensive of ${mp.total_sellers}`;
  else label = `${ordinal(mp.rank)} of ${mp.total_sellers}`;
  return (
    <span
      data-testid={`${testIdPrefix}-${mp.tag}`}
      data-tag={mp.tag}
      data-rank={mp.rank}
      title={`You: ${mp.my_price} SAR · Market range ${mp.min_price}–${mp.max_price} SAR · Median ${mp.median_price} SAR · Percentile ${mp.percentile}%`}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold tracking-wider uppercase whitespace-nowrap ${className}`}
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        color: style.color,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: style.color }} />
      {label}
    </span>
  );
}

export function MarketPositionBar({ mp, className = "" }) {
  if (!mp || !mp.total_sellers || mp.total_sellers < 2) return null;
  const range = mp.max_price - mp.min_price || 1;
  const pct = (p) => Math.max(0, Math.min(100, ((p - mp.min_price) / range) * 100));
  const myPct = pct(mp.my_price);
  const medianPct = pct(mp.median_price);
  const tagStyle = TAG_STYLES[mp.tag] || TAG_STYLES.median;

  return (
    <div className={`p-4 rounded glass-card ${className}`} data-testid="market-position-bar">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">Market Position</p>
          <p className="text-sm text-white mt-0.5">
            <span style={{ color: tagStyle.color, fontFamily: "'JetBrains Mono', monospace" }}>
              {mp.is_cheapest ? `Cheapest of ${mp.total_sellers}` : mp.is_most_expensive ? `Most expensive of ${mp.total_sellers}` : `${ordinal(mp.rank)} of ${mp.total_sellers}`}
            </span>
            <span className="text-[10px] text-[#A1E4DB] opacity-70 ms-2">(percentile {mp.percentile}%)</span>
          </p>
        </div>
        <MarketPositionBadge mp={mp} testIdPrefix="market-pos-bar" />
      </div>

      {/* Range bar */}
      <div className="relative pt-6 pb-8" data-testid="market-position-track">
        {/* Track */}
        <div
          className="relative h-2 rounded-full"
          style={{ background: "linear-gradient(90deg, rgba(16,185,129,0.35) 0%, rgba(161,228,219,0.25) 50%, rgba(245,158,11,0.35) 100%)" }}
        >
          {/* Other competitor markers (smaller dots) */}
          {(mp.sellers || [])
            .filter((s) => !s.is_mine)
            .map((s, i) => (
              <div
                key={`${s.store_name}-${i}`}
                className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2"
                style={{ left: `${pct(s.price)}%` }}
                title={`${s.store_name}: ${s.price} SAR (rank ${s.rank})`}
              >
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ background: "rgba(161,228,219,0.7)", border: "1px solid rgba(255,255,255,0.4)" }}
                />
              </div>
            ))}

          {/* Median marker (vertical line + label) */}
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 flex flex-col items-center"
            style={{ left: `${medianPct}%` }}
            data-testid="median-marker"
          >
            <div className="w-0.5 h-6 -mt-2" style={{ background: "rgba(161,228,219,0.5)" }} />
            <span
              className="text-[9px] mt-1 px-1.5 py-0.5 rounded whitespace-nowrap uppercase tracking-wider"
              style={{ color: "#A1E4DB", background: "rgba(161,228,219,0.1)", border: "1px solid rgba(161,228,219,0.25)", fontFamily: "'JetBrains Mono', monospace" }}
            >
              Median {mp.median_price}
            </span>
          </div>

          {/* My marker (large filled diamond) */}
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 flex flex-col items-center"
            style={{ left: `${myPct}%` }}
            data-testid="my-marker"
          >
            <span
              className="text-[10px] mb-1 px-1.5 py-0.5 rounded font-semibold uppercase tracking-wider whitespace-nowrap"
              style={{ color: tagStyle.color, background: tagStyle.bg, border: `1px solid ${tagStyle.border}`, fontFamily: "'JetBrains Mono', monospace" }}
            >
              You · {mp.my_price}
            </span>
            <div
              className="w-3 h-3 rotate-45"
              style={{ background: tagStyle.color, boxShadow: `0 0 8px ${tagStyle.color}` }}
            />
          </div>
        </div>

        {/* Min/max anchor labels */}
        <div className="flex justify-between text-[10px] mt-3" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>
          <span>{mp.min_price} SAR <span className="opacity-60">(lowest)</span></span>
          <span>{mp.max_price} SAR <span className="opacity-60">(highest)</span></span>
        </div>
      </div>
    </div>
  );
}

export default MarketPositionBadge;
