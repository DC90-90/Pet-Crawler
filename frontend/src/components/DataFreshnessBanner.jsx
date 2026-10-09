/**
 * DataFreshnessBanner — page-level banner showing crawl-data freshness state.
 *
 * Surfaces to the user:
 *   • Overall freshness state (green = today, yellow = this week, faded = this month, red = stale)
 *   • Latest competitor crawl + next scheduled run
 *   • Expandable per-store breakdown so the user can see which stores are dragging the cohort down
 *
 * Mounted at the top of My Products, Price Intel, and Price Scanner pages so the
 * user understands at a glance whether dashboard numbers reflect today's market
 * or last month's snapshot.
 */
import { useEffect, useState } from "react";
import { useRelease } from "@/contexts/ReleaseContext";
import { ObservationNotice } from "@/components/ReleaseBoundary";
import { ChevronDown, ChevronUp, Clock, RefreshCw, AlertTriangle, CheckCircle2 } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const BUCKET_STYLES = {
  today: {
    bg: "rgba(16, 185, 129, 0.10)",
    border: "rgba(16, 185, 129, 0.35)",
    color: "#10B981",
    Icon: CheckCircle2,
  },
  this_week: {
    bg: "rgba(251, 191, 36, 0.10)",
    border: "rgba(251, 191, 36, 0.35)",
    color: "#FBBF24",
    Icon: Clock,
  },
  this_month: {
    bg: "rgba(161, 228, 219, 0.06)",
    border: "rgba(161, 228, 219, 0.25)",
    color: "#A1E4DB",
    Icon: Clock,
  },
  stale: {
    bg: "rgba(239, 68, 68, 0.10)",
    border: "rgba(239, 68, 68, 0.45)",
    color: "#EF4444",
    Icon: AlertTriangle,
  },
  no_data: {
    bg: "rgba(161, 228, 219, 0.06)",
    border: "rgba(161, 228, 219, 0.2)",
    color: "#A1E4DB",
    Icon: Clock,
  },
};

function formatRelative(iso, isRTL) {
  if (!iso) return isRTL ? "—" : "—";
  const t = new Date(iso).getTime();
  if (!Number.isFinite(t)) return "—";
  const ageMs = Date.now() - t;
  const day = 24 * 60 * 60 * 1000;
  const hr = 60 * 60 * 1000;
  if (ageMs < 0) {
    // Future — used for next-run
    const m = Math.round(Math.abs(ageMs) / (60 * 1000));
    if (m < 60) return isRTL ? `بعد ${m} دقيقة` : `in ${m} min`;
    const h = Math.round(Math.abs(ageMs) / hr);
    if (h < 24) return isRTL ? `بعد ${h} ساعة` : `in ${h} hr${h === 1 ? "" : "s"}`;
    const d = Math.floor(Math.abs(ageMs) / day);
    return isRTL ? `بعد ${d} يوم` : `in ${d} day${d === 1 ? "" : "s"}`;
  }
  if (ageMs < hr) {
    const m = Math.max(1, Math.round(ageMs / (60 * 1000)));
    return isRTL ? `قبل ${m} دقيقة` : `${m} min ago`;
  }
  if (ageMs < day) {
    const h = Math.round(ageMs / hr);
    return isRTL ? `قبل ${h} ساعة` : `${h} hr${h === 1 ? "" : "s"} ago`;
  }
  const d = Math.floor(ageMs / day);
  return isRTL ? `قبل ${d} يوم` : `${d} day${d === 1 ? "" : "s"} ago`;
}

const MESSAGE = {
  today: { en: "Data is fresh — last competitor crawl was within the last 24h.", ar: "البيانات حديثة — تم آخر سحب من المنافسين خلال 24 ساعة." },
  this_week: { en: "Data is moderately fresh — last competitor crawl was within the last 7 days.", ar: "البيانات متوسطة الحداثة — تم آخر سحب من المنافسين خلال 7 أيام." },
  this_month: { en: "Data is aging — last competitor crawl was within the last 30 days. Some dashboards may understate today's market.", ar: "البيانات في طور التقادم — تم آخر سحب من المنافسين خلال 30 يومًا. قد لا تعكس بعض اللوحات السوق الحالي." },
  stale: { en: "Data is stale — the oldest competitor crawl is more than 30 days old. Default 30-day dashboards will appear empty; use the 90D filter for matched data.", ar: "البيانات قديمة — أقدم سحب من المنافسين أكبر من 30 يومًا. لوحات الـ30 يومًا الافتراضية قد تبدو فارغة؛ استخدم فلتر 90 يومًا." },
  no_data: { en: "No competitor crawl data available yet.", ar: "لا توجد بيانات سحب من المنافسين بعد." },
};

export default function DataFreshnessBanner({ className = "" }) {
  const release = useRelease();
  return release?.price_comparison_only ? <ObservationNotice /> : <LegacyFreshnessBanner className={className} />;
}

function LegacyFreshnessBanner({ className = "" }) {
  const { isRTL } = useI18n();
  const [data, setData] = useState(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    try {
      setLoading(true);
      setError(null);
      const r = await api.get("/data-freshness");
      setData(r.data);
    } catch (e) {
      setError(e?.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (loading && !data) {
    return (
      <div
        data-testid="data-freshness-banner-loading"
        className={`glass-card rounded-md p-3 text-xs text-[#A1E4DB]/70 ${className}`}
      >
        {isRTL ? "جارٍ التحقق من حداثة البيانات…" : "Checking data freshness…"}
      </div>
    );
  }
  if (error || !data) {
    return null; // Fail silently — banner is informational, not blocking
  }

  const { overall, stores = [], next_run, crawl_paused, sync_health } = data;
  const bucket = overall?.bucket || "no_data";
  const baseStyle = BUCKET_STYLES[bucket];
  // sync_health.alarm overrides the bucket color — silent-failure alarms must
  // always be visible regardless of how recent the crawl data is.
  const syncAlarm = sync_health?.alarm || null;
  const style = syncAlarm ? BUCKET_STYLES.stale : baseStyle;
  const Icon = style.Icon;
  const message = syncAlarm
    ? (isRTL ? `تنبيه المزامنة: ${syncAlarm}` : `Sync alarm: ${syncAlarm}`)
    : (MESSAGE[bucket]?.[isRTL ? "ar" : "en"] || "");

  // Count problem stores
  const staleCount = stores.filter((s) => !s.is_own_store && s.bucket === "stale").length;
  const totalCompetitors = stores.filter((s) => !s.is_own_store).length;

  return (
    <div
      data-testid="data-freshness-banner"
      data-freshness-bucket={bucket}
      className={`rounded-md ${className}`}
      style={{
        background: style.bg,
        border: `1px solid ${style.border}`,
      }}
    >
      <div className="flex items-center gap-2 px-4 py-2.5 rounded-md">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex-1 flex items-center gap-3 text-start cursor-pointer hover:bg-white/[0.02] transition-colors py-0.5 rounded-md min-w-0"
          data-testid="data-freshness-toggle"
          aria-expanded={expanded}
        >
          <Icon className="w-4 h-4 flex-shrink-0" style={{ color: style.color }} />
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2 flex-wrap">
              <span className="text-xs font-semibold tracking-wider uppercase" style={{ color: style.color, fontFamily: "'JetBrains Mono', monospace" }}>
                {isRTL ? "حداثة البيانات" : "Data Freshness"}
              </span>
              <span className="text-xs text-white/85">{message}</span>
            </div>
            <div className="text-[11px] text-[#A1E4DB]/80 mt-0.5 flex items-center gap-3 flex-wrap">
              {overall?.oldest_competitor_crawl && (
                <span data-testid="freshness-oldest">
                  {isRTL ? "أقدم سحب: " : "Oldest competitor crawl: "}
                  <span className="font-mono">{formatRelative(overall.oldest_competitor_crawl, isRTL)}</span>
                </span>
              )}
              {overall?.latest_competitor_crawl && (
                <span data-testid="freshness-newest">
                  {isRTL ? "أحدث سحب: " : "Newest: "}
                  <span className="font-mono">{formatRelative(overall.latest_competitor_crawl, isRTL)}</span>
                </span>
              )}
              {staleCount > 0 && (
                <span data-testid="freshness-stale-count" style={{ color: "#EF4444" }}>
                  {staleCount}/{totalCompetitors} {isRTL ? "متاجر قديمة" : "stores stale"}
                </span>
              )}
              {next_run && !crawl_paused && (
                <span data-testid="freshness-next-run">
                  {isRTL ? "السحب القادم: " : "Next crawl: "}
                  <span className="font-mono">{formatRelative(next_run, isRTL)}</span>
                </span>
              )}
              {crawl_paused && (
                <span data-testid="freshness-paused" style={{ color: "#FBBF24" }}>
                  {isRTL ? "السحب موقوف" : "Crawls paused"}
                </span>
              )}
              {sync_health?.last_run && (
                <span data-testid="freshness-sync-last-run">
                  {isRTL ? "آخر مزامنة: " : "Last sync: "}
                  <span className="font-mono">{formatRelative(sync_health.last_run, isRTL)}</span>
                  {sync_health.last_sync_status === "error" && (
                    <span className="ms-1" style={{ color: "#EF4444" }} data-testid="freshness-sync-sync-error">⚠ sync</span>
                  )}
                  {sync_health.last_match_status === "error" && (
                    <span className="ms-1" style={{ color: "#EF4444" }} data-testid="freshness-sync-match-error">⚠ match</span>
                  )}
                </span>
              )}
              {sync_health?.scheduler_running === false && (
                <span data-testid="freshness-scheduler-dead" style={{ color: "#EF4444" }}>
                  {isRTL ? "المجدول متوقف" : "Scheduler stopped"}
                </span>
              )}
            </div>
          </div>
          {expanded ? (
            <ChevronUp className="w-4 h-4 text-[#A1E4DB] flex-shrink-0" />
          ) : (
            <ChevronDown className="w-4 h-4 text-[#A1E4DB] flex-shrink-0" />
          )}
        </button>
        <button
          type="button"
          onClick={load}
          className="p-1.5 rounded-md hover:bg-white/10 transition-colors flex-shrink-0"
          title={isRTL ? "تحديث" : "Refresh"}
          data-testid="freshness-refresh-btn"
          aria-label={isRTL ? "تحديث حداثة البيانات" : "Refresh data freshness"}
        >
          <RefreshCw className={`w-3.5 h-3.5 text-[#A1E4DB] ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {expanded && (
        <div className="border-t border-white/5 px-4 py-3 space-y-1.5" data-testid="freshness-store-list">
          {stores.length === 0 ? (
            <div className="text-xs text-[#A1E4DB]/70">{isRTL ? "لا توجد بيانات" : "No store data"}</div>
          ) : (
            stores.map((s) => {
              const sStyle = BUCKET_STYLES[s.bucket] || BUCKET_STYLES.no_data;
              return (
                <div
                  key={s.store_id}
                  className="flex items-center justify-between gap-3 py-1 text-xs"
                  data-testid={`freshness-store-${s.store_id}`}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                      style={{ background: sStyle.color }}
                    />
                    <span className="text-white truncate">{s.store_name || "—"}</span>
                    {s.is_own_store && (
                      <span className="px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider font-semibold" style={{ background: "rgba(30, 152, 142, 0.18)", color: "#6AC1B5" }}>
                        {isRTL ? "متجري" : "Mine"}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 text-[11px] flex-shrink-0">
                    <span className="text-[#A1E4DB]/70 font-mono">
                      {s.last_crawled_at ? formatRelative(s.last_crawled_at, isRTL) : (isRTL ? "لا توجد بيانات" : "no data")}
                    </span>
                    <span
                      className="px-1.5 py-0.5 rounded uppercase tracking-wider font-semibold text-[9px]"
                      style={{
                        background: sStyle.bg,
                        border: `1px solid ${sStyle.border}`,
                        color: sStyle.color,
                        fontFamily: "'JetBrains Mono', monospace",
                      }}
                    >
                      {s.bucket === "no_data" ? (isRTL ? "—" : "—") : s.bucket.replace("_", " ")}
                    </span>
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
