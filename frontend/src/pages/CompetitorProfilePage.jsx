import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { ArrowLeft, Store } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, PieChart, Pie, Cell, Legend, ReferenceLine, ReferenceArea } from "recharts";
import { useSeasonalEvents, SeasonalToggle, SeasonalChartElements } from "@/components/SeasonalAnnotations";

const PIE_COLORS = ["#002DF5", "#00C853", "#FF3B30", "#FFB300", "#8B5CF6", "#EC4899", "#06B6D4", "#F97316", "#6366F1", "#84CC16"];

export default function CompetitorProfilePage() {
  const { storeId } = useParams();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [chartMode, setChartMode] = useState("weekly"); // weekly or daily
  const seasonal = useSeasonalEvents();

  useEffect(() => {
    if (!storeId) return;
    setLoading(true);
    api.get(`/stores/${storeId}/profile`)
      .then((r) => setData(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [storeId]);

  if (loading) return <div className="p-6 text-sm text-[#9CA3AF]">{t("loading")}</div>;
  if (!data) return <div className="p-6 text-sm text-[#9CA3AF]">Store not found</div>;

  const { store, kpis, revenue_trend_weekly, revenue_trend_daily, top_products, category_distribution, new_arrivals, recently_oos } = data;
  const chartData = chartMode === "weekly" ? revenue_trend_weekly : revenue_trend_daily;

  return (
    <div className="p-6 space-y-5" data-testid="competitor-profile-page">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" onClick={() => navigate("/stores")} className="h-8 w-8 p-0 rounded-md" data-testid="back-btn">
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-[#00D4B4] text-white text-sm font-bold rounded-md flex items-center justify-center">
            {store.name?.[0]?.toUpperCase()}
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white">{store.name}</h1>
            <p className="text-sm text-[#9CA3AF]">{store.domain} - <span className="capitalize">{store.platform}</span></p>
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        {[
          { label: "Catalog Size", val: kpis.catalog_size },
          { label: "Active SKUs", val: kpis.active_skus },
          { label: "Est. Monthly Revenue", val: `${(kpis.est_monthly_revenue || 0).toLocaleString()} SAR` },
          { label: "Avg Discount Rate", val: `${kpis.avg_discount_rate}%` },
          { label: "Last Crawled", val: kpis.last_crawled ? new Date(kpis.last_crawled).toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) : "-" },
        ].map((k) => (
          <div key={k.label} className="kpi-card" data-testid={`profile-kpi-${k.label}`}>
            <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">{k.label}</p>
            <p className="text-lg font-bold tracking-tighter text-white mt-1">{k.val}</p>
          </div>
        ))}
      </div>

      {/* Revenue Trend Chart */}
      <div className="glass-card rounded-md p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">Revenue Trend (90 days)</h3>
          <div className="flex gap-2 items-center">
            <SeasonalToggle show={seasonal.show} toggle={seasonal.toggle} />
            {["weekly", "daily"].map((m) => (
              <Button key={m} size="sm" variant={chartMode === m ? "default" : "outline"}
                onClick={() => setChartMode(m)}
                className={`text-xs rounded-md h-7 px-3 capitalize ${chartMode === m ? "bg-[#00D4B4] text-white" : ""}`}
                data-testid={`chart-mode-${m}`}>{m}</Button>
            ))}
          </div>
        </div>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey={chartMode === "weekly" ? "week" : "date"} tick={{ fontSize: 9, fill: "#9CA3AF" }} tickFormatter={(v) => v.slice(-6)} />
              <YAxis tick={{ fontSize: 9, fill: "#9CA3AF" }} tickFormatter={(v) => `${(v / 1000).toFixed(0)}K`} />
              <Tooltip formatter={(v) => [`${v.toLocaleString()} SAR`, "Revenue"]} contentStyle={{ background: "#1F2937", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#9CA3AF" }} />
              <SeasonalChartElements show={seasonal.show} />
              <Bar dataKey="revenue" fill="#00D4B4" radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : <p className="text-xs text-[#9CA3AF] py-8 text-center">{t("no_data")}</p>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Top 10 Products */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Top 10 Products</h3>
          <div className="space-y-2">
            {top_products.map((p, i) => (
              <div key={p.sku} className="flex items-center gap-3 py-1.5 border-b border-white/5 last:border-0" data-testid={`top-product-${i}`}>
                <span className={`w-6 h-6 rounded text-[10px] font-bold flex items-center justify-center ${i < 3 ? "bg-[#00D4B4] text-white" : "bg-[#111827]/80/5 text-[#9CA3AF]"}`}>{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-white truncate">{p.name_ar}</p>
                  <p className="text-[10px] text-[#9CA3AF]">{p.brand} - {p.category}</p>
                </div>
                <span className="text-xs font-bold text-white">{p.units_sold} sold</span>
              </div>
            ))}
            {top_products.length === 0 && <p className="text-xs text-[#9CA3AF]">{t("no_data")}</p>}
          </div>
        </div>

        {/* Category Distribution Pie */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Category Distribution</h3>
          {category_distribution.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <PieChart>
                <Pie data={category_distribution} dataKey="count" nameKey="category" cx="50%" cy="50%" outerRadius={80} label={({ category, percent }) => `${category} ${(percent * 100).toFixed(0)}%`} labelLine={false}>
                  {category_distribution.map((cat) => <Cell key={cat.category} fill={PIE_COLORS[category_distribution.indexOf(cat) % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "#1F2937", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#9CA3AF" }} />
              </PieChart>
            </ResponsiveContainer>
          ) : <p className="text-xs text-[#9CA3AF] py-8 text-center">{t("no_data")}</p>}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* New Arrivals */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">New Arrivals (Last 7 Days)</h3>
          {new_arrivals.length > 0 ? (
            <div className="space-y-2">
              {new_arrivals.map((p) => (
                <div key={p.sku} className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0">
                  <div>
                    <p className="text-xs font-medium text-white">{p.name_ar}</p>
                    <p className="text-[10px] text-[#9CA3AF] font-mono">{p.sku}</p>
                  </div>
                  <Badge variant="secondary" className="text-[10px]">{p.category}</Badge>
                </div>
              ))}
            </div>
          ) : <p className="text-xs text-[#9CA3AF]">No new products in the last 7 days</p>}
        </div>

        {/* Recently OOS */}
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Recently Out of Stock</h3>
          {recently_oos.length > 0 ? (
            <div className="space-y-2">
              {recently_oos.map((p) => (
                <div key={p.sku} className="flex items-center justify-between py-1.5 border-b border-white/5 last:border-0">
                  <div>
                    <p className="text-xs font-medium text-white">{p.name_ar}</p>
                    <p className="text-[10px] text-[#9CA3AF] font-mono">{p.sku}</p>
                  </div>
                  <Badge variant="outline" className="text-[10px] bg-red-50 text-red-600 border-red-200">OOS</Badge>
                </div>
              ))}
            </div>
          ) : <p className="text-xs text-[#9CA3AF]">No out of stock products</p>}
        </div>
      </div>
    </div>
  );
}
