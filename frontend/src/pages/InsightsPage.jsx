import { useEffect, useState } from "react";
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

const RANGE_OPTIONS = [7, 14, 30, 90];

export default function InsightsPage() {
  const { t } = useI18n();
  const [days, setDays] = useState(30);
  const [summary, setSummary] = useState(null);
  const [leaderboard, setLeaderboard] = useState([]);
  const [topSellers, setTopSellers] = useState([]);
  const [trending, setTrending] = useState([]);
  const [gaps, setGaps] = useState([]);
  const [priceWars, setPriceWars] = useState([]);
  const [restock, setRestock] = useState([]);
  const [loading, setLoading] = useState(true);
  const [digestOpen, setDigestOpen] = useState(false);
  const seasonal = useSeasonalEvents();

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get("/insights/summary", { params: { days } }),
      api.get("/insights/leaderboard", { params: { days } }),
      api.get("/insights/top-sellers", { params: { days } }),
      api.get("/insights/trending", { params: { days } }),
      api.get("/insights/gaps"),
      api.get("/insights/price-wars"),
      api.get("/insights/restock-opportunities"),
    ]).then(([s, l, ts, tr, g, pw, rs]) => {
      setSummary(s.data);
      setLeaderboard(l.data);
      setTopSellers(ts.data);
      setTrending(tr.data);
      setGaps(g.data);
      setPriceWars(pw.data);
      setRestock(rs.data);
    }).catch(console.error).finally(() => setLoading(false));
  }, [days]);

  if (loading) return <div className="p-6 text-sm text-[#9CA3AF]" data-testid="insights-loading">{t("loading")}</div>;

  return (
    <div className="p-6 space-y-5" data-testid="insights-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0A0A0A]">{t("nav_insights")}</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">{t("subtitle")}</p>
        </div>
        <div className="flex gap-2 items-center" data-testid="insights-date-range">
          <Button variant="outline" size="sm" onClick={() => setDigestOpen(true)} className="rounded-md text-xs h-7" data-testid="digest-btn">
            <BarChart3 className="w-3 h-3 me-1" />Last Digest
          </Button>
          <SeasonalToggle show={seasonal.show} toggle={seasonal.toggle} />
          {RANGE_OPTIONS.map((d) => (
            <Button key={d} size="sm" variant={days === d ? "default" : "outline"}
              onClick={() => setDays(d)}
              className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#002DF5] text-white" : ""}`}>{t(`d${d}`)}</Button>
          ))}
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
              <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">{t(k.key)}</p>
              <p className="text-xl font-bold tracking-tighter text-[#0A0A0A] mt-1">{k.val}</p>
            </div>
          ))}
        </div>
      )}

      {/* Revenue Leaderboard Chart */}
      <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
        <h3 className="text-sm font-semibold text-[#0A0A0A] mb-4">{t("chart_leaderboard")}</h3>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={leaderboard} layout="vertical" margin={{ left: 0, right: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
            <XAxis type="number" tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`} tick={{ fontSize: 11 }} />
            <YAxis type="category" dataKey="store" width={100} tick={{ fontSize: 11 }} />
            <Tooltip formatter={(v) => [`${v.toLocaleString()} SAR`, "Revenue"]} />
            <Bar dataKey="revenue_est" fill="#002DF5" radius={[0, 4, 4, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Top Sellers + Trending side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top Sellers */}
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">{t("chart_top_sellers")}</h3>
          <div className="space-y-2 max-h-[300px] overflow-y-auto">
            {topSellers.slice(0, 10).map((s, i) => (
              <div key={s.sku} className="flex items-center gap-3 py-1.5 border-b border-[#F3F4F6] last:border-0" data-testid={`top-seller-${i}`}>
                <span className={`w-6 h-6 rounded text-[10px] font-bold flex items-center justify-center ${i < 3 ? "bg-[#002DF5] text-white" : "bg-[#F3F4F6] text-[#4B5563]"}`}>{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-[#0A0A0A] truncate">{s.name_ar}</p>
                  <p className="text-[10px] text-[#9CA3AF]">{s.brand} - {s.category}</p>
                </div>
                <div className="text-end">
                  <p className="text-xs font-bold text-[#0A0A0A]">{s.units_sold} units</p>
                  <p className="text-[10px] text-[#9CA3AF]">{s.revenue_est.toLocaleString()} SAR</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Trending by Category */}
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">{t("chart_trending")}</h3>
          <Tabs defaultValue={trending[0]?.category || "cat_food"} className="w-full">
            <TabsList className="flex flex-wrap gap-1 bg-transparent h-auto p-0 mb-3">
              {trending.slice(0, 6).map((c) => (
                <TabsTrigger key={c.category} value={c.category} className="text-[10px] px-2 py-1 rounded-md data-[state=active]:bg-[#002DF5] data-[state=active]:text-white">
                  {c.category_label}
                </TabsTrigger>
              ))}
            </TabsList>
            {trending.slice(0, 6).map((c) => (
              <TabsContent key={c.category} value={c.category} className="mt-0">
                <p className="text-xs text-[#4B5563] mb-2">Total: {c.total_sales} units sold</p>
                <div className="space-y-1.5">
                  {c.top_products.map((p) => (
                    <div key={p.sku} className="flex items-center justify-between text-xs py-1 border-b border-[#F9FAFB]">
                      <span className="text-[#0A0A0A] truncate flex-1">{p.name_ar}</span>
                      <span className="font-bold text-[#0A0A0A] ms-2">{p.units_sold}</span>
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
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">{t("chart_price_wars")}</h3>
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {priceWars.map((w) => (
              <div key={w.sku} className="py-2 border-b border-[#F3F4F6] last:border-0">
                <p className="text-xs font-medium text-[#0A0A0A] truncate">{w.name_ar}</p>
                <div className="flex items-center gap-2 mt-1">
                  <Badge variant="outline" className="text-[10px] border-red-200 text-red-600">{w.spread_sar} SAR spread</Badge>
                  <span className="text-[10px] text-[#9CA3AF]">{w.spread_pct}%</span>
                </div>
              </div>
            ))}
            {priceWars.length === 0 && <p className="text-xs text-[#9CA3AF]">{t("no_data")}</p>}
          </div>
        </div>

        {/* Restock Opportunities */}
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">{t("chart_restock")}</h3>
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {restock.map((r) => (
              <div key={r.sku} className="py-2 border-b border-[#F3F4F6] last:border-0">
                <p className="text-xs font-medium text-[#0A0A0A] truncate">{r.name_ar}</p>
                <p className="text-[10px] text-red-500 mt-0.5">OOS at: {r.oos_stores.join(", ")}</p>
                <p className="text-[10px] text-green-600">In stock at: {r.in_stock_stores.map((s) => s.store).join(", ")}</p>
              </div>
            ))}
            {restock.length === 0 && <p className="text-xs text-[#9CA3AF]">{t("no_data")}</p>}
          </div>
        </div>

        {/* Product Gaps */}
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">{t("chart_gaps")}</h3>
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {gaps.map((g) => (
              <div key={g.sku} className="flex items-center justify-between py-2 border-b border-[#F3F4F6] last:border-0">
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-medium text-[#0A0A0A] truncate">{g.name_ar}</p>
                  <p className="text-[10px] text-[#9CA3AF]">{g.num_stores} stores / {g.missing_count} missing</p>
                </div>
                <Badge className="text-[10px] bg-amber-50 text-amber-700 border-amber-200" variant="outline">
                  {g.opportunity_score}%
                </Badge>
              </div>
            ))}
            {gaps.length === 0 && <p className="text-xs text-[#9CA3AF]">{t("no_data")}</p>}
          </div>
        </div>
      </div>

      <DigestModal open={digestOpen} onClose={() => setDigestOpen(false)} />
    </div>
  );
}
