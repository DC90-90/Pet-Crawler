/**
 * SalesInsights — additive "Product Sales Insights" block on the Insights page.
 *
 * Renders summary KPIs, Top Brands table, and per-product sales table for the
 * selected date window. Reuses the existing global date filter (props from
 * InsightsPage). Manages its own local search + sort state.
 *
 * Data source: GET /api/insights/sales — a thin server wrapper around the
 * existing my_products() sales-estimation logic. No new estimation is done
 * here or on the server.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SkuLine } from "@/components/SkuLine";
import { MineBadge } from "@/components/MineBadge";

const STOCK_TONE = {
  HIGH:   { bg: "rgba(16,185,129,0.12)",  border: "rgba(16,185,129,0.45)", color: "#10B981" },
  MEDIUM: { bg: "rgba(251,191,36,0.12)",  border: "rgba(251,191,36,0.45)", color: "#FBBF24" },
  LOW:    { bg: "rgba(245,158,11,0.14)",  border: "rgba(245,158,11,0.5)",  color: "#F59E0B" },
  OOS:    { bg: "rgba(239,68,68,0.14)",   border: "rgba(239,68,68,0.5)",   color: "#EF4444" },
};

function fmtSar(n) {
  if (n == null || isNaN(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export default function SalesInsights({ days, dateFrom, dateTo }) {
  const { t, isRTL } = useI18n();
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState("revenue_desc");

  // 300ms debounce on search to keep the API quiet
  const [debouncedSearch, setDebouncedSearch] = useState("");
  useMemo(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  const params = useMemo(() => {
    const p = { sort };
    if (dateFrom && dateTo) {
      p.date_from = dateFrom;
      p.date_to = dateTo;
    } else {
      p.days = days;
    }
    if (debouncedSearch) p.search = debouncedSearch;
    return p;
  }, [days, dateFrom, dateTo, sort, debouncedSearch]);

  const { data, isLoading } = useQuery({
    queryKey: ["insights", "sales", params],
    queryFn: async () => {
      const { data } = await api.get("/insights/sales", { params });
      return data;
    },
    staleTime: 60_000,
  });

  const kpis = data?.kpis || {};
  const products = data?.products || [];
  const topBrands = data?.top_brands || [];

  const sortOptions = [
    { value: "revenue_desc", label: t("si_sort_revenue_desc") },
    { value: "revenue_asc",  label: t("si_sort_revenue_asc")  },
    { value: "sales_desc",   label: t("si_sort_sales_desc")   },
    { value: "sales_asc",    label: t("si_sort_sales_asc")    },
  ];

  return (
    <section className="space-y-4" data-testid="sales-insights-section">
      <div>
        <h2 className="text-lg font-semibold text-white tracking-tight">{t("sales_insights_title")}</h2>
        <p className="text-xs text-[#A1E4DB] mt-0.5">{t("sales_insights_subtitle")}</p>
      </div>

      {/* Summary KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="sales-insights-kpis">
        {[
          { key: "total_units",   label: t("si_kpi_total_units"),   val: (kpis.total_units_sold || 0).toLocaleString() },
          { key: "total_revenue", label: t("si_kpi_total_revenue"), val: `${fmtSar(kpis.total_revenue || 0)} ${t("sar")}` },
          { key: "avg_revenue",   label: t("si_kpi_avg_revenue"),   val: `${fmtSar(kpis.avg_revenue_per_product || 0)} ${t("sar")}` },
          { key: "top_brand",     label: t("si_kpi_top_brand"),     val: kpis.top_brand || "—" },
        ].map((k) => (
          <div key={k.key} className="kpi-card" data-testid={`si-kpi-${k.key}`}>
            <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{k.label}</p>
            <p className="text-xl font-bold tracking-tighter text-white mt-1 truncate" title={k.val}>{k.val}</p>
          </div>
        ))}
      </div>

      {/* Top Brands table */}
      <div className="glass-card rounded-md p-5" data-testid="si-top-brands">
        <h3 className="text-sm font-semibold text-white mb-3">{t("si_top_brands")}</h3>
        {topBrands.length === 0 ? (
          <p className="text-xs text-[#A1E4DB] opacity-70 py-3">{isLoading ? t("loading") : t("si_no_data")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="border-b border-white/5">
                <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB]">{t("si_col_brand")}</TableHead>
                <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB]">{t("si_col_units")}</TableHead>
                <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB]">{t("si_col_revenue")}</TableHead>
                <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] w-[40%]">{t("si_col_share")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {topBrands.slice(0, 10).map((b, i) => (
                <TableRow key={b.brand} className="border-b border-white/5 hover:bg-white/[0.02]" data-testid={`si-brand-row-${i}`}>
                  <TableCell className="text-sm text-white font-medium" data-testid={`si-brand-name-${i}`}>{b.brand}</TableCell>
                  <TableCell className="text-sm text-white font-mono">{(b.units_sold || 0).toLocaleString()}</TableCell>
                  <TableCell className="text-sm text-white font-mono">{fmtSar(b.revenue_est)} {t("sar")}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden">
                        <div className="h-full rounded-full" style={{
                          width: `${Math.min(100, b.market_share_pct)}%`,
                          background: "linear-gradient(90deg, #1E988E 0%, #6AC1B5 100%)",
                          transition: "width 400ms ease",
                        }} />
                      </div>
                      <span className="text-xs text-[#A1E4DB] font-mono w-12 text-end" data-testid={`si-brand-share-${i}`}>{b.market_share_pct}%</span>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Per-product sales table with search + sort */}
      <div className="glass-card rounded-md p-5" data-testid="si-products-table">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
          <h3 className="text-sm font-semibold text-white">{t("sales_insights_title")}</h3>
          <div className="flex gap-2 items-center" data-testid="si-controls">
            <Input
              type="text"
              placeholder={t("si_search_placeholder")}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 text-xs w-56"
              data-testid="si-search-input"
            />
            <Select value={sort} onValueChange={setSort}>
              <SelectTrigger className="h-8 text-xs w-44" data-testid="si-sort-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {sortOptions.map((o) => (
                  <SelectItem key={o.value} value={o.value} data-testid={`si-sort-opt-${o.value}`}>{o.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {isLoading ? (
          <p className="text-xs text-[#A1E4DB] py-3" data-testid="si-products-loading">{t("loading")}</p>
        ) : products.length === 0 ? (
          <p className="text-xs text-[#A1E4DB] opacity-70 py-3" data-testid="si-products-empty">{t("si_no_data")}</p>
        ) : (
          <div className="max-h-[520px] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow className="border-b border-white/5 sticky top-0 bg-[#0A2728]/95 backdrop-blur">
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB]">{t("col_product")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB]">{t("si_col_brand")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] text-end">{t("col_sales")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] text-end">{t("col_revenue")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] text-end">{t("si_col_avg_price")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] text-center">{t("col_sellers")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] text-center">{t("col_stock")}</TableHead>
                  <TableHead className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] text-end">{t("col_confidence")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {products.map((p, i) => {
                  const stockKey = (p.stock_signal || "").toUpperCase();
                  const tone = STOCK_TONE[stockKey] || STOCK_TONE.MEDIUM;
                  const name = isRTL ? (p.name_ar || p.name_en) : (p.name_en || p.name_ar);
                  return (
                    <TableRow key={p.sku} className="border-b border-white/5 hover:bg-white/[0.02]" data-testid={`si-product-row-${i}`}>
                      <TableCell className="max-w-[280px]">
                        <p className="text-sm text-white font-medium truncate inline-flex items-center gap-1.5"><MineBadge sku={p.sku} />{name}</p>
                        <SkuLine sku={p.sku} />
                      </TableCell>
                      <TableCell className="text-sm text-[#A1E4DB]" data-testid={`si-product-brand-${i}`}>{p.brand || "—"}</TableCell>
                      <TableCell className="text-sm text-white font-mono text-end" data-testid={`si-product-sales-${i}`}>{(p.qty_sold_est || 0).toLocaleString()}</TableCell>
                      <TableCell className="text-sm text-white font-mono text-end" data-testid={`si-product-revenue-${i}`}>{fmtSar(p.revenue_est)} {t("sar")}</TableCell>
                      <TableCell className="text-sm text-white font-mono text-end">{(p.avg_price || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</TableCell>
                      <TableCell className="text-sm text-[#A1E4DB] font-mono text-center">{p.num_sellers || 0}</TableCell>
                      <TableCell className="text-center">
                        <Badge
                          variant="outline"
                          className="text-[10px] tracking-wider"
                          style={{ background: tone.bg, border: `1px solid ${tone.border}`, color: tone.color, fontFamily: "'JetBrains Mono', monospace" }}
                          data-testid={`si-product-stock-${i}`}
                        >
                          {t(`stock_${stockKey.toLowerCase()}`) || stockKey || "—"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-sm text-[#A1E4DB] font-mono text-end">{p.confidence_score || 0}%</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </section>
  );
}
