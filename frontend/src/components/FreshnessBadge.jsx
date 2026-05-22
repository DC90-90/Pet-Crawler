/**
 * FreshnessBadge — single source of truth for displaying data-freshness state.
 *
 * Tiers (per spec):
 *   • < 24h            → "Today"        green
 *   • 1–7 days         → "X days ago"   yellow
 *   • 7–30 days        → "X days ago"   muted/faded
 *   • > 30 days        → "Stale"        red, faded
 *
 * Also exposes:
 *   - getFreshnessBucket(iso) → "today" | "this_week" | "this_month" | "stale" | "unknown"
 *   - isStale(iso)            → true when row should be faded out
 */
import { useMemo } from "react";

export function getFreshnessBucket(iso) {
  if (!iso) return "unknown";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "unknown";
  const ageMs = Date.now() - t;
  const day = 24 * 60 * 60 * 1000;
  if (ageMs < day) return "today";
  if (ageMs < 7 * day) return "this_week";
  if (ageMs < 30 * day) return "this_month";
  return "stale";
}

export function isStale(iso) {
  return getFreshnessBucket(iso) === "stale";
}

const TIER_STYLES = {
  today: {
    bg: "rgba(16, 185, 129, 0.15)",
    border: "rgba(16, 185, 129, 0.45)",
    color: "#10B981",
    label: "Today",
  },
  this_week: {
    bg: "rgba(251, 191, 36, 0.15)",
    border: "rgba(251, 191, 36, 0.45)",
    color: "#FBBF24",
    label: "{n}d ago",
  },
  this_month: {
    bg: "rgba(161, 228, 219, 0.08)",
    border: "rgba(161, 228, 219, 0.25)",
    color: "#A1E4DB",
    label: "{n}d ago",
    faded: true,
  },
  stale: {
    bg: "rgba(239, 68, 68, 0.15)",
    border: "rgba(239, 68, 68, 0.45)",
    color: "#EF4444",
    label: "Stale",
    faded: true,
  },
  unknown: {
    bg: "rgba(161, 228, 219, 0.06)",
    border: "rgba(161, 228, 219, 0.2)",
    color: "#A1E4DB",
    label: "—",
  },
};

function formatTooltip(iso) {
  if (!iso) return "Last crawl time unknown";
  const d = new Date(iso);
  if (!Number.isFinite(d.getTime())) return "Last crawl time unknown";
  const ksa = new Date(d.getTime() + 3 * 60 * 60 * 1000);
  const hh = String(ksa.getUTCHours()).padStart(2, "0");
  const mm = String(ksa.getUTCMinutes()).padStart(2, "0");
  const datePart = ksa.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
  const ageMs = Date.now() - d.getTime();
  const day = 24 * 60 * 60 * 1000;
  const hr = 60 * 60 * 1000;
  let relative;
  if (ageMs < hr) relative = `${Math.max(1, Math.round(ageMs / (60 * 1000)))} min ago`;
  else if (ageMs < day) relative = `${Math.round(ageMs / hr)} hr${Math.round(ageMs / hr) === 1 ? "" : "s"} ago`;
  else relative = `${Math.floor(ageMs / day)} day${Math.floor(ageMs / day) === 1 ? "" : "s"} ago`;
  return `Last crawled ${relative} (${datePart} ${hh}:${mm} KSA)`;
}

export default function FreshnessBadge({ crawledAt, className = "", testIdPrefix = "freshness" }) {
  const { bucket, label, style, tooltip, daysAgo } = useMemo(() => {
    const b = getFreshnessBucket(crawledAt);
    const s = TIER_STYLES[b];
    let d = 0;
    if (crawledAt) {
      const ageMs = Date.now() - new Date(crawledAt).getTime();
      d = Math.max(1, Math.floor(ageMs / (24 * 60 * 60 * 1000)));
    }
    const finalLabel = s.label.replace("{n}", String(d));
    return { bucket: b, label: finalLabel, style: s, tooltip: formatTooltip(crawledAt), daysAgo: d };
  }, [crawledAt]);

  return (
    <span
      title={tooltip}
      data-testid={`${testIdPrefix}-${bucket}`}
      data-freshness-bucket={bucket}
      data-days-ago={daysAgo}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium tracking-wider uppercase whitespace-nowrap ${className}`}
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
        color: style.color,
        opacity: style.faded ? 0.85 : 1,
        fontFamily: "'JetBrains Mono', monospace",
      }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: style.color, opacity: bucket === "today" ? 1 : 0.7 }}
      />
      {label}
    </span>
  );
}
