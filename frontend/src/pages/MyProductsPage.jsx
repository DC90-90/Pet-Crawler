import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Search, Download, ArrowUpDown, ArrowUp, ArrowDown, TrendingUp, TrendingDown, ExternalLink } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import ProductDetailPanel from "@/components/ProductDetailPanel";

const RANGE_OPTIONS = [7, 14, 30, 90];

function StockBadge({ signal }) {
  const cls = { HIGH: "stock-high", MEDIUM: "stock-medium", LOW: "stock-low", OOS: "stock-oos", AVAIL: "stock-high" };
  const labelMap = { AVAIL: "IN STOCK" };
  return <span className={`text-xs font-bold ${cls[signal] || ""}`}>{labelMap[signal] || signal}</span>;
}

function ConfBadge({ tier, score }) {
  const cls = { 1: "tier-1", 2: "tier-2", 3: "tier-3", 4: "bg-[#1E988E]/15 text-[#1E988E]" };
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${cls[tier] || "tier-2"}`}>
      T{tier} {score}%
    </span>
  );
}

function SortIcon({ field, sortBy, sortOrder }) {
  if (sortBy !== field) return <ArrowUpDown className="w-3 h-3 ms-1 opacity-30" />;
  return sortOrder === "asc" ? <ArrowUp className="w-3 h-3 ms-1 text-[#1E988E]" /> : <ArrowDown className="w-3 h-3 ms-1 text-[#1E988E]" />;
}

export default function MyProductsPage() {
  const { t, isRTL } = useI18n();
  const [data, setData] = useState({ kpis: {}, products: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [onDate, setOnDate] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [sortBy, setSortBy] = useState("revenue_est");
  const [sortOrder, setSortOrder] = useState("desc");
  const [selectedSku, setSelectedSku] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);

  const categories = data.categories || [...new Set(data.products.map((p) => p.category))].sort();

  const fetchData = useCallback(() => {
    setLoading(true);
    const offset = (page - 1) * pageSize;
    const params = {
      search: debouncedSearch || undefined,
      category: category !== "all" ? category : undefined,
      sort_by: sortBy, sort_order: sortOrder,
      limit: pageSize, offset,
    };
    if (onDate) params.on_date = onDate;
    else params.days = days;
    api.get("/my-products", { params })
      .then((r) => setData(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [days, onDate, debouncedSearch, category, sortBy, sortOrder, page, pageSize]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // 300ms search debounce — avoids hammering the API on every keystroke
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(id);
  }, [search]);

  // Reset to first page when filters change
  useEffect(() => { setPage(1); }, [days, onDate, debouncedSearch, category, sortBy, sortOrder, pageSize]);

  const handleSort = (field) => {
    if (sortBy === field) setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    else { setSortBy(field); setSortOrder("desc"); }
  };

  const handleExport = () => {
    window.open(`${process.env.REACT_APP_BACKEND_URL}/api/export/products?days=${days}`, "_blank");
  };

  const kpis = data.kpis || {};

  return (
    <div className="p-6 space-y-5" data-testid="my-products-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-white">{t("nav_products")}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "السوق السعودي، مفكّك" : "Saudi Market, Decoded"}</p>
        </div>
        <button onClick={handleExport} className="rounded-full bg-transparent border border-white/10 text-white hover:bg-white/5 transition-all px-4 py-2 text-xs font-medium flex items-center gap-1.5" data-testid="export-csv-btn">
          <Download className="w-3.5 h-3.5" />{t("btn_export")}
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { key: "kpi_products", val: kpis.total_products ?? "-", icon: TrendingUp, accent: "#1E988E" },
          { key: "kpi_units_sold", val: (kpis.total_units_sold ?? 0).toLocaleString(), icon: TrendingUp, accent: "#10B981" },
          { key: "kpi_revenue", val: `${(kpis.total_revenue ?? 0).toLocaleString()} ${t("sar")}`, icon: TrendingUp, accent: "#1E988E" },
          { key: "kpi_market_share", val: `${kpis.avg_market_share ?? 0}%`, icon: TrendingDown, accent: "#F59E0B" },
        ].map((k, i) => (
          <div key={k.key} className="kpi-card animate-fadeIn" style={{ animationDelay: `${i * 80}ms` }} data-testid={`kpi-${k.key}`}>
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{t(k.key)}</p>
              <k.icon className="w-4 h-4" style={{ color: k.accent }} />
            </div>
            <p className="text-2xl font-bold tracking-tighter text-white metric-number animate-countUp">{k.val}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 glass-card p-3">
        <div className="flex gap-1" data-testid="date-range-picker">
          {RANGE_OPTIONS.map((d) => (
            <button key={d}
              onClick={() => { setDays(d); setOnDate(""); }}
              className={`text-xs rounded-full h-7 px-3 font-medium transition-all ${!onDate && days === d ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:text-white hover:bg-white/5"}`}
              data-testid={`range-${d}d`}>{t(`d${d}`)}</button>
          ))}
        </div>
        <div className="flex items-center gap-2 ms-2 ps-2 border-s border-[#13625F]" data-testid="date-day-picker">
          <input
            type="date"
            value={onDate}
            onChange={(e) => setOnDate(e.target.value)}
            max={new Date().toISOString().slice(0, 10)}
            className="text-xs h-7 px-2 rounded bg-[#0A2728] border border-[#13625F] text-white focus:outline-none focus:border-[#1E988E]"
            style={{ colorScheme: "dark" }}
            data-testid="day-picker-input"
            title="Filter to a specific day"
          />
          {onDate && (
            <button
              onClick={() => setOnDate("")}
              className="text-[10px] uppercase tracking-wider text-[#A1E4DB] hover:text-white"
              data-testid="day-picker-clear"
            >
              {isRTL ? "إلغاء" : "Clear"}
            </button>
          )}
        </div>
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute start-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#A1E4DB]" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("search")}
            className="ps-9 h-8 text-sm rounded-xl bg-white/5 border-white/10 text-white placeholder:text-[#A1E4DB]/50 focus:border-[#1E988E]/50" data-testid="product-search-input" />
        </div>
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger className="w-[150px] h-8 text-xs rounded-xl bg-white/5 border-white/10 text-white" data-testid="filter-category">
            <SelectValue placeholder={t("all_categories")} />
          </SelectTrigger>
          <SelectContent className="bg-[#104745] border-white/10 text-white">
            <SelectItem value="all">{t("all_categories")}</SelectItem>
            {categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="glass-card overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow>
              {[
                { key: "name_en", label: "col_product", sortable: true },
                { key: "sku", label: "col_sku", sortable: false },
                { key: "price", label: "col_price", sortable: true },
                { key: "vs_lowest_pct", label: "col_vs_low", sortable: true },
                { key: "qty_sold_est", label: "col_sales", sortable: true },
                { key: "revenue_est", label: "col_revenue", sortable: true },
                { key: "num_sellers", label: "col_sellers", sortable: true },
                { key: "stock_signal", label: "col_stock", sortable: false },
                { key: "confidence_score", label: "col_confidence", sortable: true },
              ].map((col) => (
                <TableHead key={col.key}
                  className={`text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB] ${col.sortable ? "cursor-pointer select-none hover:text-white" : ""}`}
                  onClick={() => col.sortable && handleSort(col.key)}>
                  <span className="flex items-center">
                    {t(col.label)}
                    {col.sortable && <SortIcon field={col.key} sortBy={sortBy} sortOrder={sortOrder} />}
                  </span>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow><TableCell colSpan={9} className="text-center py-16 text-[#A1E4DB] text-sm">{t("loading")}</TableCell></TableRow>
            ) : data.products.length === 0 ? (
              <TableRow><TableCell colSpan={9} className="text-center py-16 text-[#A1E4DB] text-sm">{t("no_data")}</TableCell></TableRow>
            ) : (
              data.products.map((p) => (
                <TableRow key={p.sku} className="cursor-pointer hover:bg-[#104745]/40" onClick={() => setSelectedSku(p.sku)} data-testid={`product-row-${p.sku}`}>
                  <TableCell>
                    <div className="flex items-start gap-2">
                      <div className="flex-1 min-w-0">
                        {p.product_url ? (
                          <a
                            href={p.product_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            onClick={(e) => e.stopPropagation()}
                            className="block hover:text-[#6AC1B5] transition-colors"
                            data-testid={`product-link-${p.sku}`}
                            title={p.product_url}
                          >
                            <p className="text-sm font-medium text-white leading-tight inline-flex items-center gap-1">
                              {p.name_ar}
                              <ExternalLink className="w-3 h-3 opacity-60 flex-shrink-0" />
                            </p>
                            <p className="text-[11px] text-[#A1E4DB]">{p.name_en}</p>
                          </a>
                        ) : (
                          <>
                            <p className="text-sm font-medium text-white leading-tight">{p.name_ar}</p>
                            <p className="text-[11px] text-[#A1E4DB]">{p.name_en}</p>
                          </>
                        )}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>
                    {p.product_url ? (
                      <a
                        href={p.product_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="text-xs font-mono text-[#A1E4DB] hover:text-[#6AC1B5]"
                        data-testid={`product-sku-link-${p.sku}`}
                      >
                        {p.sku}
                      </a>
                    ) : (
                      <span className="text-xs font-mono text-[#A1E4DB]">{p.sku}</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div>
                      <span className="text-sm font-semibold text-white metric-number">{p.price} {t("sar")}</span>
                      {p.min_price !== p.max_price && (
                        <p className="text-[10px] text-[#A1E4DB]">{p.min_price}-{p.max_price}</p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className={`text-xs font-semibold ${p.vs_lowest_pct > 0 ? "text-[#EF4444]" : "text-[#10B981]"}`}>
                      {p.vs_lowest_pct > 0 ? "+" : ""}{p.vs_lowest_pct}%
                    </span>
                  </TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number">{p.qty_sold_est.toLocaleString()}</span></TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number">{p.revenue_est.toLocaleString()} {t("sar")}</span></TableCell>
                  <TableCell><Badge className="text-[11px] rounded-full bg-white/5 border-white/10 text-[#A1E4DB]">{p.num_sellers}</Badge></TableCell>
                  <TableCell><StockBadge signal={p.stock_signal} /></TableCell>
                  <TableCell><ConfBadge tier={p.source_tier} score={p.confidence_score} /></TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <ProductDetailPanel sku={selectedSku} onClose={() => setSelectedSku(null)} />

      {/* Pagination */}
      {data.total > pageSize && (
        <div className="flex items-center justify-between px-2" data-testid="pagination">
          <p className="text-xs text-[#A1E4DB]">
            {isRTL
              ? `عرض ${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, data.total)} من ${data.total.toLocaleString()}`
              : `Showing ${((page - 1) * pageSize + 1).toLocaleString()}–${Math.min(page * pageSize, data.total).toLocaleString()} of ${data.total.toLocaleString()}`}
          </p>
          <div className="flex items-center gap-2">
            <Select value={String(pageSize)} onValueChange={(v) => setPageSize(Number(v))}>
              <SelectTrigger className="w-[90px] h-7 text-xs rounded-full bg-white/5 border-white/10 text-white" data-testid="page-size-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#104745] border-white/10 text-white">
                {[50, 100, 200, 500].map((n) => <SelectItem key={n} value={String(n)}>{n} / page</SelectItem>)}
              </SelectContent>
            </Select>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="h-7 px-3 text-xs rounded-full bg-white/5 border border-white/10 text-white hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="page-prev-btn"
            >
              {isRTL ? "التالي" : "Prev"}
            </button>
            <span className="text-xs font-mono text-[#A1E4DB]" data-testid="page-indicator">
              {page} / {Math.max(1, Math.ceil(data.total / pageSize))}
            </span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * pageSize >= data.total}
              className="h-7 px-3 text-xs rounded-full bg-white/5 border border-white/10 text-white hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="page-next-btn"
            >
              {isRTL ? "السابق" : "Next"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
