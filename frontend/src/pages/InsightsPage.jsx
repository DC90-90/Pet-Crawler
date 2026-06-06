import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { useSeasonalEvents, SeasonalToggle, SeasonalChartElements } from "@/components/SeasonalAnnotations";
import DigestModal from "@/components/DigestModal";
import { BarChart3, Bell, Eye } from "lucide-react";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import SalesInsights from "@/components/SalesInsights";

const RANGE_OPTIONS = [7, 14, 30, 90];

// React Query helper — fetches one endpoint, returns the data array/object or empty fallback.
const fetchInsight = (path, params) => async () => {
  try {
    const { data } = await api.get(path, { params });
    return data;
  } catch (_e) {
    return null;
  }
};

export default function InsightsPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [digestOpen, setDigestOpen] = useState(false);
  const seasonal = useSeasonalEvents();

  // Perf sprint Feb 2026 — useQueries fires all 7 insight calls in PARALLEL
  // with shared stale-while-revalidate cache (60s). Tab re-visits within
  // 60s hit the React Query cache and don't trigger any network call at all.
  const results = useQueries({
    queries: [
      { queryKey: ["insights", "summary", days], queryFn: fetchInsight("/insights/summary", { days }) },
      { queryKey: ["insights", "leaderboard", days], queryFn: fetchInsight("/insights/leaderboard", { days }) },
      { queryKey: ["insights", "top-sellers", days], queryFn: fetchInsight("/insights/top-sellers", { days }) },
      { queryKey: ["insights", "trending", days], queryFn: fetchInsight("/insights/trending", { days }) },
      { queryKey: ["insights", "gaps"], queryFn: fetchInsight("/insights/gaps") },
      { queryKey: ["insights", "price-wars"], queryFn: fetchInsight("/insights/price-wars") },
      { queryKey: ["insights", "restock"], queryFn: fetchInsight("/insights/restock-opportunities") },
    ],
  });

  const [sQ, lQ, tsQ, trQ, gQ, pwQ, rsQ] = results;
  const summary = sQ.data;
  const leaderboard = lQ.data || [];
  const topSellers = tsQ.data || [];
  const trending = trQ.data || [];
  const gaps = gQ.data || [];
  const priceWars = pwQ.data || [];
  const restock = rsQ.data || [];
  const loading = results.some((r) => r.isLoading);

  if (loading) return <div className="p-6 text-sm text-[#A1E4DB]" data-testid="insights-loading">{t("loading")}</div>;

  return (
    <div className="p-6 space-y-5" data-testid="insights-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_insights")}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{t("subtitle")}</p>
        </div>
        <div className="flex gap-2 items-center" data-testid="insights-date-range">
          <Button variant="outline" size="sm" onClick={() => setDigestOpen(true)} className="rounded-md text-xs h-7" data-testid="digest-btn">
            <BarChart3 className="w-3 h-3 me-1" />Last Digest
          </Button>
          <SeasonalToggle show={seasonal.show} toggle={seasonal.toggle} />
          {RANGE_OPTIONS.map((d) => (
            <Button key={d} size="sm" variant={days === d ? "default" : "outline"}
              onClick={() => setDays(d)}
              className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#1E988E] text-[#090E1C]" : ""}`}>{t(`d${d}`)}</Button>
          ))}
          {/* Custom date range — only consumed by Sales Insights section below.
              Existing 7/14/30/90D pills above continue to drive every other card on this page. */}
          <div className="flex items-center gap-1 ms-2" data-testid="insights-custom-range">
            <span className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] opacity-70">{t("si_date_from")}</span>
            <input
              type="date"
              value={dateFrom}
              max={dateTo || undefined}
              onChange={(e) => setDateFrom(e.target.value)}
              className="bg-[#0A2728] border border-white/10 rounded text-xs text-white h-7 px-2"
              data-testid="insights-date-from"
            />
            <span className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] opacity-70">{t("si_date_to")}</span>
            <input
              type="date"
              value={dateTo}
              min={dateFrom || undefined}
              onChange={(e) => setDateTo(e.target.value)}
              className="bg-[#0A2728] border border-white/10 rounded text-xs text-white h-7 px-2"
              data-testid="insights-date-to"
            />
            {(dateFrom || dateTo) && (
              <Button size="sm" variant="outline" onClick={() => { setDateFrom(""); setDateTo(""); }} className="text-xs h-7 px-2" data-testid="insights-date-clear">{t("si_clear_range")}</Button>
            )}
          </div>
        </div>
      </div>

      {/* Summary KPIs */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {[
            { key: "kpi_skus", val: summary.total_skus },
            { key: "kpi_drops", val: summary.price_drops },
            { key: "kpi_gaps", val: summary.product_gaps },
            { key: "kpi_spread", val: `${summary.median_spread} ${t("sar")}` },
            { key: "kpi_confidence", val: `${summary.avg_confidence}%` },
          ].map((k) => (
            <div key={k.key} className="kpi-card" data-testid={`insight-${k.key}`}>
              <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{t(k.key)}</p>
              <p className="text-xl font-bold tracking-tighter text-white mt-1">{k.val}</p>
            </div>
          ))}
        </div>
      )}

      {/* Data Freshness header card (Feb 2026 — instant trust signal) */}
      {summary?.freshness_breakdown && (
        <div className="glass-card rounded-md p-4" data-testid="freshness-card">
          <div className="flex items-baseline justify-between mb-3">
            <div>
              <h3 className="text-xs uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">Data Freshness</h3>
              <p className="text-[10px] text-[#A1E4DB] opacity-70 mt-0.5">
                {summary.freshness_breakdown.total_tracked.toLocaleString()} tracked competitor prices across all stores
              </p>
            </div>
          </div>
          {(() => {
            const f = summary.freshness_breakdown;
            const tiers = [
              { key: "today",      label: "Today",       pct: f.today_pct,       count: f.today,       color: "#10B981", bg: "rgba(16,185,129,0.85)" },
              { key: "this_week",  label: "This week",   pct: f.this_week_pct,   count: f.this_week,   color: "#FBBF24", bg: "rgba(251,191,36,0.85)" },
              { key: "this_month", label: "This month",  pct: f.this_month_pct,  count: f.this_month,  color: "#A1E4DB", bg: "rgba(161,228,219,0.55)" },
              { key: "stale",      label: "Stale (>30d)",pct: f.stale_pct,       count: f.stale,       color: "#EF4444", bg: "rgba(239,68,68,0.65)" },
            ];
            return (
              <>
                <div className="flex w-full h-3 rounded overflow-hidden mb-2" data-testid="freshness-bar">
                  {tiers.map((tier) => (
                    <div
                      key={tier.key}
                      style={{ width: `${tier.pct}%`, background: tier.bg, transition: "width 600ms ease" }}
                      title={`${tier.label}: ${tier.pct}% (${tier.count.toLocaleString()} prices)`}
                      data-testid={`freshness-segment-${tier.key}`}
                    />
                  ))}
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-3">
                  {tiers.map((tier) => (
                    <div key={tier.key} className="flex items-center gap-2" data-testid={`freshness-tier-${tier.key}`}>
                      <span className="w-2 h-2 rounded-full" style={{ background: tier.color }} />
                      <div>
                        <p className="text-[10px] uppercase tracking-[0.1em] font-semibold" style={{ color: tier.color }}>{tier.label}</p>
                        <p className="text-sm font-bold text-white">{tier.pct}% <span className="text-[10px] font-normal text-[#A1E4DB] opacity-70">({tier.count.toLocaleString()})</span></p>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            );
          })()}
        </div>
      )}

      {/* Market Position summary card (Feb 2026) */}
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

      {/* Revenue Leaderboard Chart */}
      <div className="glass-card rounded-md p-5" data-testid="revenue-leaderboard">
        <h3 className="text-sm font-semibold text-white mb-4">{t("chart_leaderboard")}</h3>
        {(() => {
          // Feb 2026 — split rows by revenue_status so Salla stores that can
          // never expose sold_count don't appear as visually-identical "0 bars"
          // alongside truly low-revenue stores.
          const computed = (leaderboard || []).filter((r) => r.revenue_status === "computed");
          const accumulating = (leaderboard || []).filter((r) => r.revenue_status === "insufficient_history");
          const unavailable = (leaderboard || []).filter((r) => r.revenue_status === "sales_data_unavailable");
          return (
            <>
              {computed.length > 0 ? (
                <ResponsiveContainer width="100%" height={Math.max(220, computed.length * 36)}>
                  <BarChart data={computed} layout="vertical" margin={{ left: 10, right: 20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" horizontal={false} />
                    <XAxis type="number" tickFormatter={(v) => v >= 1000000 ? `${(v / 1000000).toFixed(1)}M` : v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v} tick={{ fontSize: 10, fill: "#A1E4DB" }} />
                    <YAxis type="category" dataKey="store" width={120} tick={{ fontSize: 11, fill: "#A1E4DB" }} />
                    <Tooltip formatter={(v) => [`${v.toLocaleString()} SAR`, "Est. Revenue"]} contentStyle={{ background: "#104745", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#A1E4DB" }} itemStyle={{ color: "#1E988E" }} />
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

      {/* Top Sellers + Trending side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top Sellers */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_top_sellers")}</h3>
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
          </div>
        </div>

        {/* Trending by Category */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_trending")}</h3>
          <Tabs defaultValue={trending[0]?.category || "cat_food"} className="w-full">
            <TabsList className="flex flex-wrap gap-1 bg-transparent h-auto p-0 mb-3">
              {trending.slice(0, 6).map((c) => (
                <TabsTrigger key={c.category} value={c.category} className="text-[10px] px-2 py-1 rounded-md data-[state=active]:bg-[#1E988E] data-[state=active]:text-[#090E1C]">
                  {c.category_label}
                </TabsTrigger>
              ))}
            </TabsList>
            {trending.slice(0, 6).map((c) => (
              <TabsContent key={c.category} value={c.category} className="mt-0">
                <p className="text-xs text-[#A1E4DB] mb-2">Total: {c.total_sales} units sold</p>
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
        </div>
      </div>

      {/* Price Wars + Restock + Gaps */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Price Wars */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_price_wars")}</h3>
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

        {/* Restock Opportunities */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_restock")}</h3>
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

        {/* Product Gaps */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{t("chart_gaps")}</h3>
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {gaps.map((g) => (
              <div key={g.sku} className="flex items-center justify-between py-2 border-b border-white/5 last:border-0">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={g.sku} />{g.name_ar}</p>
                  <SkuLine sku={g.sku} barcode={g.barcode} />
                  <p className="text-[10px] text-[#A1E4DB]">{g.num_stores} stores / {g.missing_count} missing</p>
                </div>
                <Badge className="text-[10px] bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/30" variant="outline">
                  {g.opportunity_score}%
                </Badge>
              </div>
            ))}
            {gaps.length === 0 && <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>}
          </div>
        </div>
      </div>

      <DigestModal open={digestOpen} onClose={() => setDigestOpen(false)} />

      {/* Product Sales Insights (additive — does not modify any existing card above) */}
      <SalesInsights days={days} dateFrom={dateFrom && dateTo ? dateFrom : ""} dateTo={dateFrom && dateTo ? dateTo : ""} />
    </div>
  );
}
