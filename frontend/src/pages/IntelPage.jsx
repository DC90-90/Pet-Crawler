/**
 * IntelPage — merged Price Intel + Insights (Feb 2026).
 *
 * Single source of truth for everything price + market intelligence:
 *   1. KPI band (blended: My SKUs · Matched · Price Drops · Product Gaps · Confidence)
 *   2. Data Freshness banner (rich)
 *   3. Market Position — unified card (verdict + 4 tiles)
 *   4. Market Strength Ranking + Your Store Performance (side-by-side)
 *   5. Revenue Leaderboard chart
 *   6. Action row — Confidence Distribution | Price Wars | Restock
 *   7. Top Sellers | Trending by Category
 *   8. Operational tabs — Action / Advantages / Full / Unverified / Gaps
 *   9. Product Sales Insights table
 *
 * Data-fetch strategy: ALL endpoints fanned out via useQueries in parallel,
 * with React Query's 60s stale-while-revalidate cache. Each card renders as
 * soon as its own query resolves — no page-blocking spinner.
 *
 * Backward compat: `/insights` and `/price-intel` both mount this page.
 */
import { useState, useEffect, useRef } from "react";
import { useRelease } from "@/contexts/ReleaseContext";
import PriceComparisonPage from "@/pages/PriceComparisonPage";
import { ComparisonScope, useComparisonScope } from "@/components/ComparisonScope";
import { RequestError } from "@/components/RequestError";
import { useNavigate } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { useI18n, catLabel } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { AlertTriangle, Award, ShoppingCart, AlertCircle, PackageSearch, BarChart3 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { useSeasonalEvents, SeasonalToggle } from "@/components/SeasonalAnnotations";
import DigestModal from "@/components/DigestModal";
import DataFreshnessBanner from "@/components/DataFreshnessBanner";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import { CardPeriod } from "@/components/CardPeriod";
import SalesInsights from "@/components/SalesInsights";
import {
  ConfidenceDistribution,
  ConfidenceGuidePanel,
  StoreRankingCard,
} from "@/components/priceIntel/PriceIntelHeader";
import { PriceIntelTabContent } from "@/components/priceIntel/PriceIntelTabs";
import { PriceIntelDetailSheet } from "@/components/priceIntel/PriceIntelDetailSheet";

const RANGE_OPTIONS = [7, 14, 30, 90];

// Shared fetch helper that also captures the x-cache-computed-at header
const fetchIntel = (path, params) => async () => {
  try {
    const res = await api.get(path, { params });
    const data = res.data;
    if (data && typeof data === "object" && !Array.isArray(data)) {
      const ca = res.headers?.["x-cache-computed-at"];
      if (ca) data._cache_computed_at = ca;
    }
    return data;
  } catch (error) {
    throw error;
  }
};

export default function IntelPage() {
  const release = useRelease();
  return release?.price_comparison_only ? <PriceComparisonPage /> : <FullIntelPage />;
}

function FullIntelPage() {
  const scope = useComparisonScope();
  const [detailError, setDetailError] = useState(false);
  const detailRequest = useRef(0);
  const { t, isRTL } = useI18n();
  const navigate = useNavigate();

  const [days, setDays] = useState(30);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [digestOpen, setDigestOpen] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const [tab, setTab] = useState("action");
  const [selectedSku, setSelectedSku] = useState(null);
  const [detail, setDetail] = useState(null);
  const seasonal = useSeasonalEvents();
  useEffect(() => { detailRequest.current += 1; setSelectedSku(null); setDetail(null); setDetailError(false); }, [scope.params]);

  // All endpoints parallelised — cards render individually as they resolve.
  const results = useQueries({
    queries: [
      { queryKey: ["intel", "insights-summary", days], queryFn: fetchIntel("/insights/summary", { days }) },
      { queryKey: ["intel", "leaderboard", days],      queryFn: fetchIntel("/insights/leaderboard", { days }) },
      { queryKey: ["intel", "top-sellers", days],      queryFn: fetchIntel("/insights/top-sellers", { days }) },
      { queryKey: ["intel", "trending", days],         queryFn: fetchIntel("/insights/trending", { days }) },
      { queryKey: ["intel", "gaps"],                   queryFn: fetchIntel("/insights/gaps") },
      { queryKey: ["intel", "price-wars"],             queryFn: fetchIntel("/insights/price-wars") },
      { queryKey: ["intel", "restock"],                queryFn: fetchIntel("/insights/restock-opportunities") },
      { queryKey: ["intel", "pi-dashboard", scope.params], queryFn: fetchIntel("/price-intel/dashboard", scope.params), retry: false },
      { queryKey: ["intel", "pi-store-ranking"],       queryFn: fetchIntel("/price-intel/store-ranking") },
      { queryKey: ["intel", "catalog-gaps"],           queryFn: fetchIntel("/baseline/catalog-gaps") },
      { queryKey: ["intel", "my-products", 14],        queryFn: fetchIntel("/my-products", { days: 14, limit: 1 }) },
      { queryKey: ["intel", "insights-summary", 14],   queryFn: fetchIntel("/insights/summary", { days: 14 }) },
    ],
  });

  const [
    sQ, lQ, tsQ, trQ, gapsQ, pwQ, rsQ,
    piQ, rkQ, cgQ, myQ, sum14Q,
  ] = results;

  const summary     = sQ.data;
  const leaderboard = lQ.data || [];
  const topSellers  = tsQ.data || [];
  const trending    = trQ.data || [];
  const gaps        = gapsQ.data || [];
  const priceWars   = pwQ.data || [];
  const restock     = rsQ.data || [];
  const piData      = piQ.data;                          // price-intel/dashboard
  const ranking     = rkQ.data;                          // price-intel/store-ranking
  const catalogGaps = cgQ.data || [];
  const myKpis      = myQ.data?.kpis || null;
  const summary14   = sum14Q.data || null;

  const cacheComputedAt = summary?._cache_computed_at || piData?._cache_computed_at || null;
  const rankingComputedAt = ranking?._cache_computed_at || null;

  // Only the two "core" queries block the initial paint. Everything else fills in.
  const initialLoading = sQ.isLoading && piQ.isLoading;
  if (initialLoading) {
    return (
      <div className="flex items-center justify-center h-96" data-testid="intel-loading">
        <div className="w-8 h-8 rounded-full border-2 border-[#1E988E] border-t-transparent animate-spin" />
      </div>
    );
  }

  // ── Operational-tab helpers ──────────────────────────────────────────────
  const openDetail = async (sku) => {
    const request = ++detailRequest.current;
    setSelectedSku(sku);
    setDetail(null); setDetailError(false);
    try {
      const r = await api.get(`/price-intel/product/${encodeURIComponent(sku)}`, { params: scope.params, timeout: 45000 });
      if (request === detailRequest.current) setDetail(r.data);
    } catch { if (request === detailRequest.current) setDetailError(true); }
  };
  const closeDetail = () => { detailRequest.current += 1; setSelectedSku(null); setDetail(null); setDetailError(false); };
  const confirmMatch = async (m) => {
    try {
      await api.post("/price-intel/confirm-match", { my_sku: m.my_sku, competitor_sku: m.competitor_sku, competitor_store_id: m.competitor_store_id, competitor_offer_id: m.competitor_offer_id });
      toast.success("Match confirmed (confidence → 100)");
      if (selectedSku) openDetail(selectedSku);
      piQ.refetch();
    } catch { toast.error("Failed"); }
  };
  const rejectMatch = async (m) => {
    try {
      await api.post("/price-intel/reject-match", { my_sku: m.my_sku, competitor_sku: m.competitor_sku, competitor_store_id: m.competitor_store_id, competitor_offer_id: m.competitor_offer_id });
      toast.success("Match rejected and blacklisted");
      if (selectedSku) openDetail(selectedSku);
      piQ.refetch();
    } catch { toast.error("Failed"); }
  };

  const piSummary = piData?.summary || {};
  const kpiTiles = [
    { key: "my_skus",    label: isRTL ? "منتجاتي" : "My SKUs",         val: piSummary.total_products ?? summary?.total_skus ?? "—" },
    { key: "matched",    label: isRTL ? "متطابق"   : "Matched",          val: piSummary.matched_products ?? "—" },
    { key: "drops",      label: isRTL ? "انخفاضات" : "Price Drops",      val: summary?.price_drops ?? "—" },
    { key: "gaps",       label: isRTL ? "فجوات"    : "Product Gaps",     val: summary?.product_gaps ?? "—" },
    { key: "confidence", label: isRTL ? "الثقة"    : "Avg. Confidence",  val: summary?.avg_confidence != null ? `${summary.avg_confidence}%` : "—" },
  ];

  const opTabs = piData ? [
    { id: "action",     label: isRTL ? "إجراء مطلوب"    : "Action Required",   count: piData.action_required?.length ?? 0, icon: AlertTriangle },
    { id: "advantage",  label: isRTL ? "مزاياي"         : "My Advantages",     count: piData.my_advantages?.length ?? 0,   icon: Award },
    { id: "full",       label: isRTL ? "المقارنة الكاملة" : "Full Comparison", count: piData.full_table?.length ?? 0,       icon: ShoppingCart },
    { id: "unverified", label: isRTL ? "غير مؤكد"       : "Unverified",        count: (piData.unverified || []).length,     icon: AlertCircle },
    { id: "gaps",       label: isRTL ? "فجوات الكتالوج" : "Catalog Gaps",      count: catalogGaps.length,                    icon: PackageSearch },
  ] : [];

  if (results[7].isError) return <div className="p-6" data-testid="intel-page"><RequestError id="intel-request" onRetry={() => results[7].refetch()} /></div>;

  return (
    <div className="p-6 space-y-5" data-testid="intel-page">
      {results.some(q => q.isError) && <RequestError id="intel-request" onRetry={() => results.filter(q => q.isError).forEach(q => q.refetch())} />}
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_intel")}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">
            {isRTL ? "استخبارات الأسعار والسوق في مكان واحد" : "Price & market intelligence in one place"}
          </p>
          {cacheComputedAt && (
            <p className="text-[11px] text-[#6AC1B5] mt-0.5 font-mono" data-testid="intel-cache-freshness">
              {isRTL ? "وقت حساب المؤشرات" : "Metrics computed"}{" "}
              {new Date(cacheComputedAt).toLocaleString(isRTL ? "ar-SA" : "en-GB", { dateStyle: "medium", timeStyle: "short" })}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2 items-center" data-testid="intel-date-range">
          <Button variant="outline" size="sm" onClick={() => setDigestOpen(true)} className="rounded-md text-xs h-7" data-testid="digest-btn">
            <BarChart3 className="w-3 h-3 me-1" />Last Digest
          </Button>
          <SeasonalToggle show={seasonal.show} toggle={seasonal.toggle} />
          {RANGE_OPTIONS.map((d) => (
            <Button
              key={d}
              size="sm"
              variant={days === d ? "default" : "outline"}
              onClick={() => setDays(d)}
              className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#1E988E] text-[#090E1C]" : ""}`}
              data-testid={`range-${d}`}
            >
              {t(`d${d}`)}
            </Button>
          ))}
          <div className="flex items-center gap-1 ms-2" data-testid="intel-custom-range">
            <span className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] opacity-70">{t("si_date_from")}</span>
            <input
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => setDateFrom(e.target.value)}
              className="bg-[#0A2728] border border-white/10 rounded text-xs text-white h-7 px-2"
              data-testid="intel-date-from"
            />
            <span className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] opacity-70">{t("si_date_to")}</span>
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => setDateTo(e.target.value)}
              className="bg-[#0A2728] border border-white/10 rounded text-xs text-white h-7 px-2"
              data-testid="intel-date-to"
            />
            {(dateFrom || dateTo) && (
              <Button size="sm" variant="outline" onClick={() => { setDateFrom(""); setDateTo(""); }} className="text-xs h-7 px-2" data-testid="intel-date-clear">
                {t("si_clear_range")}
              </Button>
            )}
          </div>
        </div>
      </div>

      <ComparisonScope scope={scope} prefix="intel" />
      <p className="text-xs text-[#A1E4DB]" data-testid="intel-scope-coverage">Comparison scope: Matched, Action Required, My Advantages, Full Comparison and product details. Store-wide insights below remain all tracked stores.</p>
      {/* ── Row 1: KPI band (blended) ────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="intel-kpi-band">
        {kpiTiles.map((k) => (
          <div key={k.key} className="kpi-card" data-testid={`intel-kpi-${k.key}`}>
            <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{k.label}</p>
            <p className="text-xl font-bold tracking-tighter text-white mt-1 metric-number">{k.val}</p>
          </div>
        ))}
      </div>

      {/* ── Row 2: Rich Data Freshness banner ────────────────────────────── */}
      <DataFreshnessBanner />

      {/* ── Row 3: Unified Market Position card ──────────────────────────── */}
      {summary?.market_position_summary && summary.market_position_summary.ranked_products > 0 && (() => {
        const m = summary.market_position_summary;
        const pct = m.avg_percentile != null ? m.avg_percentile : null;
        const verdict = pct == null
          ? ""
          : pct < 33 ? `cheaper than most — you're typically at the ${pct}th percentile`
          : pct < 50 ? `mostly below the market median (${pct}th percentile)`
          : pct < 66 ? `mostly above the market median (${pct}th percentile)`
          : `expensive vs the market — you're typically at the ${pct}th percentile`;
        const tone = pct == null ? "#A1E4DB" : pct < 50 ? "#6AC1B5" : pct < 66 ? "#A1E4DB" : "#FBBF24";
        const tiles = [
          { key: "cheapest",       count: m.cheapest_count,       label: "Cheapest seller",     color: "#10B981", filter: "cheapest" },
          { key: "below_median",   count: m.below_median_count,   label: "Below market median", color: "#6AC1B5", filter: "below_median" },
          { key: "above_median",   count: m.above_median_count,   label: "Above market median", color: "#FBBF24", filter: "above_median" },
          { key: "most_expensive", count: m.most_expensive_count, label: "Most expensive",      color: "#F59E0B", filter: "most_expensive" },
        ];
        return (
          <div className="glass-card rounded-md p-4" data-testid="market-position-card">
            <div className="flex items-baseline justify-between mb-3">
              <div>
                <h3 className="text-xs uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">Market Position</h3>
                <p className="text-[10px] text-[#A1E4DB] opacity-70 mt-0.5">
                  {m.ranked_products.toLocaleString()} of {m.total_my_products.toLocaleString()} products ranked against competitors
                </p>
              </div>
              {pct != null && (
                <p className="text-xs" style={{ color: tone, fontFamily: "'JetBrains Mono', monospace" }} data-testid="market-pos-verdict">
                  You&apos;re {verdict}
                </p>
              )}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {tiles.map((tile) => (
                <button
                  key={tile.key}
                  type="button"
                  onClick={() => navigate(`/?market_filter=${tile.filter}`)}
                  className="text-left p-3 rounded transition-all hover:bg-[#104745]/40 active:scale-[0.98]"
                  style={{ border: `1px solid rgba(255,255,255,0.06)`, background: "rgba(0,0,0,0.15)" }}
                  data-testid={`mp-tile-${tile.key}`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span className="w-2 h-2 rounded-full" style={{ background: tile.color }} />
                    <span className="text-[10px] uppercase tracking-[0.1em] font-semibold" style={{ color: tile.color }}>{tile.label}</span>
                  </div>
                  <p className="text-xl font-bold text-white">{tile.count.toLocaleString()}</p>
                  <p className="text-[9px] text-[#A1E4DB] opacity-60 mt-0.5">products</p>
                </button>
              ))}
            </div>
          </div>
        );
      })()}

      {/* ── Row 4: Market Strength Ranking + Store Performance ───────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4" data-testid="intel-market-row">
        <StoreRankingCard ranking={ranking} computedAt={rankingComputedAt} isRTL={isRTL} />
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{isRTL ? "أداء متجرك (14 يوم)" : "Your Store Performance (14d)"}</h3>
          <div className="grid grid-cols-2 gap-4" data-testid="pi-store-performance-live">
            {(() => {
              const isLedger = myKpis?.my_revenue_source === "zid_orders";
              return (
                <>
                  <div>
                    <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">
                      {isLedger ? (isRTL ? "الإيرادات (14 يوم)" : "Revenue (14d)") : (isRTL ? "الإيرادات المقدرة (14 يوم)" : "Est. Revenue (14d)")}
                    </p>
                    <p className="text-xl font-bold text-[#1E988E] metric-number">
                      {myKpis?.my_revenue != null ? `${myKpis.my_revenue.toLocaleString()} SAR` : "—"}
                    </p>
                    {isLedger && myKpis?.my_orders_count != null && (
                      <p className="text-[9px] text-[#6AC1B5]">{myKpis.my_orders_count.toLocaleString()} {isRTL ? "طلب · سجل زد" : "orders · Zid ledger"}</p>
                    )}
                  </div>
                  <div>
                    <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">
                      {isLedger ? (isRTL ? "الوحدات المباعة" : "Units Sold") : (isRTL ? "الوحدات المباعة (تقديري)" : "Est. Units Sold")}
                    </p>
                    <p className="text-xl font-bold text-white metric-number">{myKpis?.my_units_sold != null ? myKpis.my_units_sold.toLocaleString() : "—"}</p>
                  </div>
                  <div>
                    <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">{isRTL ? "المنتجات النشطة" : "Active Products"}</p>
                    <p className="text-xl font-bold text-white metric-number">{myKpis?.total_products != null ? myKpis.total_products.toLocaleString() : "—"}</p>
                  </div>
                  <div>
                    <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">{isRTL ? "وسيط فرق السعر" : "Median Price Spread"}</p>
                    <p className="text-xl font-bold text-[#F59E0B] metric-number">{summary14?.median_spread != null ? `${summary14.median_spread.toLocaleString()} SAR` : "—"}</p>
                  </div>
                </>
              );
            })()}
          </div>
        </div>
      </div>

      {/* ── Row 5: Revenue Leaderboard chart ─────────────────────────────── */}
      <div className="glass-card rounded-md p-5" data-testid="revenue-leaderboard">
        <h3 className="text-sm font-semibold text-white mb-3">{t("chart_leaderboard")}</h3>
        <CardPeriod window={days} testId="leaderboard-period" />
        {(() => {
          // iter73t (Aug 8 2026) — Salla stores now come back with
          // `revenue_status: "measured_approx"` from the shared badge-diff
          // helper, matching what the Market Strength Ranking reads for
          // the same store. Include both `computed` (Zid exact) and
          // `measured_approx` (Salla) on the chart — that's what makes
          // this card equal the Ranking's numbers by construction.
          const computed     = (leaderboard || []).filter((r) => r.revenue_status === "computed" || r.revenue_status === "measured_approx");
          const accumulating = (leaderboard || []).filter((r) => r.revenue_status === "insufficient_history");
          const unavailable  = (leaderboard || []).filter((r) => r.revenue_status === "sales_data_unavailable");
          return (
            <>
              {computed.length > 0 ? (
                <ResponsiveContainer width="100%" height={Math.max(220, computed.length * 36)}>
                  <BarChart data={computed} layout="vertical" margin={{ left: 10, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis type="number" tickFormatter={(v) => v >= 1000000 ? `${(v / 1000000).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v} tick={{ fontSize: 10, fill: "#A1E4DB" }} />
                    <YAxis type="category" dataKey="store" width={120} tick={{ fontSize: 11, fill: "#A1E4DB" }} />
                    <Tooltip formatter={(v, _n, p) => {
                      const tag = p?.payload?.revenue_status === "measured_approx"
                        ? " (measured ~ from Salla sold-count)" : "";
                      return [`${v.toLocaleString()} SAR${tag}`, "Est. Revenue"];
                    }} contentStyle={{ background: "#104745", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#A1E4DB" }} itemStyle={{ color: "#1E988E" }} />
                    <Bar dataKey="revenue_est" fill="#1E988E" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-xs text-[#A1E4DB] py-4 text-center" data-testid="leaderboard-no-computed">
                  No store has enough multi-snapshot history to compute revenue yet.
                </p>
              )}
              {(accumulating.length > 0 || unavailable.length > 0) && (
                <div className="mt-5 pt-4 border-t border-white/5 space-y-2">
                  {accumulating.map((r) => (
                    <div key={r.store_id} className="flex items-center justify-between text-xs" title="Sales data is available but needs more days of crawl history to compute reliable estimates" data-testid={`accumulating-${r.store_id}`}>
                      <span className="text-[#A1E4DB]">{r.store}</span>
                      <span className="text-[#FBBF24] tracking-wider text-[10px]">Tracked — accumulating history</span>
                    </div>
                  ))}
                  {unavailable.map((r) => (
                    <div key={r.store_id} className="flex items-center justify-between text-xs" title="This store's public API does not expose sales count (Salla limitation). Product catalog and prices are still tracked." data-testid={`unavailable-${r.store_id}`}>
                      <span className="text-[#A1E4DB]">{r.store} <span className="text-[10px] text-[#A1E4DB] opacity-60">({r.products} products)</span></span>
                      <span className="text-[#6AC1B5] tracking-wider text-[10px]">Tracked — sales data unavailable (Salla limitation)</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          );
        })()}
      </div>

      {/* ── Row 6: Confidence Distribution + Price Wars + Restock ────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4" data-testid="intel-action-row">
        <ConfidenceDistribution
          distribution={piData?.confidence_distribution}
          isRTL={isRTL}
          showGuide={showGuide}
          onToggleGuide={() => setShowGuide(!showGuide)}
        />
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_price_wars")}</h3>
          <CardPeriod window="current" testId="price-wars-period" />
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {priceWars.map((w) => (
              <div key={w.sku} className="py-2 border-b border-white/5 last:border-0">
                <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={w.sku} />{w.name_ar}</p>
                <SkuLine sku={w.sku} barcode={w.barcode} />
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="outline" className="text-[10px] border-[#EF4444]/30 text-[#EF4444] bg-[#EF4444]/10">{w.spread_sar} SAR spread</Badge>
                  <span className="text-[10px] text-[#A1E4DB]">{w.spread_pct}%</span>
                </div>
              </div>
            ))}
            {priceWars.length === 0 && <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>}
          </div>
        </div>
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_restock")}</h3>
          <CardPeriod window="current" testId="restock-period" />
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {restock.map((r) => (
              <div key={r.sku} className="py-2 border-b border-white/5 last:border-0">
                <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={r.sku} />{r.name_ar}</p>
                <SkuLine sku={r.sku} barcode={r.barcode} />
                <p className="text-[10px] text-red-500 mt-0.5">OOS at: {r.oos_stores.join(", ")}</p>
                <p className="text-[10px] text-green-600">In stock at: {r.in_stock_stores.map((s) => s.store).join(", ")}</p>
              </div>
            ))}
            {restock.length === 0 && <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>}
          </div>
        </div>
      </div>

      {/* Confidence Guide panel (toggle from ConfidenceDistribution) */}
      {showGuide && <ConfidenceGuidePanel isRTL={isRTL} />}

      {/* ── Row 7: Top Sellers + Trending ────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_top_sellers")}</h3>
          <CardPeriod window={days} testId="top-sellers-period" />
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {topSellers.slice(0, 10).map((s, i) => (
              <div key={s.sku} className="flex items-center gap-3 py-1.5 border-b border-white/5 last:border-0" data-testid={`top-seller-${i}`}>
                <span className={`w-6 h-6 rounded text-[10px] font-bold flex items-center justify-center ${i < 3 ? "bg-[#1E988E] text-[#090E1C]" : "bg-white/5 text-[#A1E4DB]"}`}>{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={s.sku} />{s.name_ar}</p>
                  <SkuLine sku={s.sku} barcode={s.barcode} />
                  <p className="text-[10px] text-[#A1E4DB]">{s.brand} - {s.category}</p>
                </div>
                <div className="text-end">
                  <p className="text-xs font-bold text-white">{s.units_sold} units</p>
                  <p className="text-[10px] text-[#A1E4DB]">{s.revenue_est.toLocaleString()} SAR</p>
                </div>
              </div>
            ))}
            {topSellers.length === 0 && <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>}
          </div>
        </div>
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_trending")}</h3>
          <CardPeriod window={days} testId="trending-period" />
          {trending.length > 0 ? (
            <Tabs defaultValue={trending[0]?.category || "cat_food"} className="w-full">
              <TabsList className="flex flex-wrap gap-1 bg-transparent h-auto p-0 mb-3">
                {trending.slice(0, 9).map((c) => (
                  <TabsTrigger key={c.category} value={c.category} className="text-[10px] px-2 py-1 rounded-md data-[state=active]:bg-[#1E988E] data-[state=active]:text-[#090E1C]">
                    {catLabel(c.category, isRTL) || c.category_label}
                  </TabsTrigger>
                ))}
              </TabsList>
              {trending.slice(0, 9).map((c) => (
                <TabsContent key={c.category} value={c.category} className="mt-0">
                  <p className="text-xs text-[#A1E4DB] mb-2">Observed movement: {c.total_sales} units</p>
                  <div className="space-y-1.5">
                    {c.top_products.map((p) => (
                      <div key={p.sku} className="flex items-center justify-between text-xs py-1 border-b border-white/5">
                        <div className="flex-1 min-w-0">
                          <span className="text-[#A1E4DB] truncate inline-flex items-center gap-1.5"><MineBadge sku={p.sku} />{p.name_ar}</span>
                          <SkuLine sku={p.sku} barcode={p.barcode} />
                        </div>
                        <span className="font-bold text-white ms-2">{p.units_sold}</span>
                      </div>
                    ))}
                  </div>
                </TabsContent>
              ))}
            </Tabs>
          ) : (
            <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>
          )}
        </div>
      </div>

      {/* ── Row 8: Product Gaps (Insights standalone card) ───────────────── */}
      <div className="glass-card rounded-md p-5">
        <h3 className="text-sm font-semibold text-white mb-3">{t("chart_gaps")}</h3>
        <CardPeriod window="current" testId="gaps-period" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2 max-h-[300px] overflow-y-auto">
          {gaps.map((g) => (
            <div key={g.sku} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={g.sku} />{g.name_ar}</p>
                <SkuLine sku={g.sku} barcode={g.barcode} />
                <p className="text-[10px] text-[#A1E4DB]">{g.num_stores} verified sellers · not in my saved catalogue</p>
              </div>
              <Badge className="text-[10px] bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" variant="outline">
                {g.opportunity_score == null ? "Unranked" : `${g.opportunity_score}%`}
              </Badge>
            </div>
          ))}
          {gaps.length === 0 && <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>}
        </div>
      </div>

      {/* ── Row 9: Operational tabs (Price Intel drilldown workspace) ────── */}
      {piData && (
        <div className="space-y-3" data-testid="intel-op-tabs">
          <div className="flex gap-1 glass-card p-1.5 flex-wrap">
            {opTabs.map((ot) => (
              <button
                key={ot.id}
                onClick={() => setTab(ot.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === ot.id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:text-white hover:bg-white/5"}`}
                data-testid={`tab-${ot.id}`}
              >
                <ot.icon className="w-4 h-4" />{ot.label}
                <Badge className="text-[10px] bg-white/10 border-0 text-[#A1E4DB]">{ot.count}</Badge>
              </button>
            ))}
          </div>
          <PriceIntelTabContent
            tab={tab}
            data={piData}
            catalogGaps={catalogGaps}
            isRTL={isRTL}
            onOpen={openDetail}
          />
        </div>
      )}

      {/* ── Row 10: Product-level Sales Insights table ───────────────────── */}
      <SalesInsights days={days} dateFrom={dateFrom && dateTo ? dateFrom : ""} dateTo={dateFrom && dateTo ? dateTo : ""} />

      {/* Overlays */}
      <DigestModal open={digestOpen} onClose={() => setDigestOpen(false)} />
      <PriceIntelDetailSheet
        error={detailError} onRetry={() => openDetail(selectedSku)}
        selectedSku={selectedSku}
        detail={detail}
        onClose={closeDetail}
        onConfirm={confirmMatch}
        onReject={rejectMatch}
      />
    </div>
  );
}
