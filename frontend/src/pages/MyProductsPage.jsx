import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api, { API_BASE } from "@/lib/api";
import { Search, Download, ArrowUpDown, ArrowUp, ArrowDown, TrendingUp, TrendingDown, ExternalLink, RefreshCw } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import ProductDetailPanel from "@/components/ProductDetailPanel";
import { MineBadge } from "@/components/MineBadge";
import { MarketPositionBadge } from "@/components/MarketPosition";
import { SkuLine } from "@/components/SkuLine";
import DataFreshnessBanner from "@/components/DataFreshnessBanner";

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
  // Auto-sync from pets-houses.com (Feb 2026)
  const [syncing, setSyncing] = useState(false);
  const [syncMsg, setSyncMsg] = useState("");

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
    window.open(`${API_BASE}/export/products?days=${days}`, "_blank");
  };

  // Trigger an on-demand sync from pets-houses.com (Zid public crawl).
  // Re-fetches the product table after a short delay so any newly discovered
  // SKUs become visible without a hard refresh.
  const handleSyncFromStore = async () => {
    if (syncing) return;
    setSyncing(true);
    setSyncMsg(isRTL ? "بدأت المزامنة من المتجر..." : "Sync started from your store…");
    try {
      const { data } = await api.post("/import/sync-own-store");
      setSyncMsg(
        isRTL
          ? `جاري المزامنة من ${data.domain || "pets-houses.com"} — قد يستغرق حتى دقيقتين`
          : `Syncing from ${data.domain || "pets-houses.com"} — this can take up to ~2 min`
      );
      // Poll once after 20s and again after 60s to refresh the table when sync completes
      setTimeout(fetchData, 20_000);
      setTimeout(() => { fetchData(); setSyncMsg(isRTL ? "اكتملت المزامنة" : "Sync complete"); setSyncing(false); }, 60_000);
    } catch (e) {
      setSyncMsg((isRTL ? "فشل في المزامنة: " : "Sync failed: ") + (e?.response?.data?.detail || e?.message || "unknown"));
      setSyncing(false);
    }
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
        <div className="flex items-center gap-2">
          <button
            onClick={handleSyncFromStore}
            disabled={syncing}
            className="rounded-full bg-transparent border border-[#1E988E]/40 text-[#6AC1B5] hover:bg-[#1E988E]/10 disabled:opacity-50 disabled:cursor-not-allowed transition-all px-4 py-2 text-xs font-medium flex items-center gap-1.5"
            data-testid="sync-from-store-btn"
            title={isRTL ? "سحب فوري لقائمة منتجاتك من متجرك على Zid" : "Pull your current product list from your Zid store"}
          >
            <RefreshCw className={`w-3.5 h-3.5 ${syncing ? "animate-spin" : ""}`} />
            {syncing ? (isRTL ? "تتم المزامنة..." : "Syncing…") : (isRTL ? "مزامنة من المتجر" : "Sync from Store")}
          </button>
          <button onClick={handleExport} className="rounded-full bg-transparent border border-white/10 text-white hover:bg-white/5 transition-all px-4 py-2 text-xs font-medium flex items-center gap-1.5" data-testid="export-csv-btn">
            <Download className="w-3.5 h-3.5" />{t("btn_export")}
          </button>
        </div>
      </div>
      {syncMsg && (
        <div className="text-xs text-[#A1E4DB] -mt-2" data-testid="sync-status-msg">{syncMsg}</div>
      )}

      {/* Data Freshness Banner (Feb 2026) — surfaces crawl-staleness so the user
         knows whether the dashboard reflects today's market or last month's snapshot. */}
      <DataFreshnessBanner />

      {/* KPI Cards (Feb 2026 — revenue split into two cards so the user can
         see BOTH what the market earns and what they actually take home.
         Sixth card added: Market Coverage = matched products / total — surfaces
         the data-quality bar so a low avg_market_share isn't read as "we're losing"
         when the truth is "we don't have competitor data on most of the catalogue") */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { key: "kpi_products", val: kpis.total_products ?? "-", icon: TrendingUp, accent: "#1E988E" },
          { key: "kpi_units_sold", val: (kpis.total_units_sold ?? 0).toLocaleString(), icon: TrendingUp, accent: "#10B981" },
          { key: "kpi_mkt_revenue", val: `${(kpis.market_revenue ?? 0).toLocaleString()} ${t("sar")}`, icon: TrendingUp, accent: "#1E988E" },
          { key: "kpi_my_revenue", val: `${(kpis.my_revenue ?? 0).toLocaleString()} ${t("sar")}`, icon: TrendingUp, accent: "#10B981" },
          { key: "kpi_market_share", val: `${kpis.avg_market_share ?? 0}%`, sub: kpis.share_sample_size != null ? `${isRTL ? "عبر" : "across"} ${kpis.share_sample_size} ${isRTL ? "منتج" : "products"}` : null, icon: TrendingDown, accent: "#F59E0B" },
          { key: "kpi_market_coverage", val: `${kpis.market_coverage_pct ?? 0}%`, sub: `${kpis.matched_products ?? 0} / ${kpis.total_products ?? 0}`, icon: TrendingUp, accent: (kpis.market_coverage_pct ?? 0) < 20 ? "#EF4444" : "#10B981" },
        ].map((k, i) => (
          <div key={k.key} className="kpi-card animate-fadeIn" style={{ animationDelay: `${i * 80}ms` }} data-testid={`kpi-${k.key}`}>
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{t(k.key)}</p>
              <k.icon className="w-4 h-4" style={{ color: k.accent }} />
            </div>
            <p className="text-2xl font-bold tracking-tighter text-white metric-number animate-countUp">{k.val}</p>
            {k.sub && <p className="text-[11px] text-[#A1E4DB] font-mono mt-0.5" data-testid={`kpi-${k.key}-sub`}>{k.sub}</p>}
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
                { key: "vs_my_price_pct", label: "col_vs_low", sortable: true },
                { key: "qty_sold_est", label: "col_sales", sortable: true },
                { key: "revenue_est", label: "col_revenue", sortable: true },
                { key: "num_competitors", label: "col_sellers", sortable: true },
                { key: "my_stock_signal", label: "col_stock", sortable: false },
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
              data.products.map((p) => {
                const isMine = p.is_my_product;
                return (
                <TableRow
                  key={p.sku}
                  className={`cursor-pointer hover:bg-[#104745]/40 ${isMine ? "bg-[#1E988E]/[0.06] border-s-2 border-s-[#1E988E]" : ""}`}
                  onClick={() => setSelectedSku(p.sku)}
                  data-testid={`product-row-${p.sku}`}
                  data-is-mine={isMine ? "true" : "false"}
                >
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
                            <p className="text-sm font-medium text-white leading-tight inline-flex items-center gap-1.5">
                              <MineBadge sku={p.sku} />
                              {p.name_ar}
                              <ExternalLink className="w-3 h-3 opacity-60 flex-shrink-0" />
                            </p>
                            <p className="text-[11px] text-[#A1E4DB]">{p.name_en}</p>
                            <SkuLine sku={p.sku} barcode={p.barcode} className="mt-0.5" />
                            {p.present_on_store === false && (
                              <span className="inline-block mt-1 text-[9px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30" data-testid={`archived-badge-${p.sku}`}>
                                {isRTL ? "غير موجود في المتجر" : "Not on store"}
                              </span>
                            )}
                            {p.discovered_via === "auto_sync" && p.present_on_store !== false && (
                              <span className="inline-block mt-1 ms-1 text-[9px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded-full bg-[#1E988E]/15 text-[#6AC1B5] border border-[#1E988E]/30" title={isRTL ? "تمت إضافته تلقائيًا من متجرك" : "Auto-discovered from your store"} data-testid={`autosynced-badge-${p.sku}`}>
                                {isRTL ? "تمت المزامنة" : "Auto-synced"}
                              </span>
                            )}
                            {p.market_position && (
                              <div className="mt-1">
                                <MarketPositionBadge mp={p.market_position} testIdPrefix={`mp-${p.sku}`} />
                              </div>
                            )}
                          </a>
                        ) : (
                          <>
                            <p className="text-sm font-medium text-white leading-tight inline-flex items-center gap-1.5">
                              <MineBadge sku={p.sku} />
                              {p.name_ar}
                            </p>
                            <p className="text-[11px] text-[#A1E4DB]">{p.name_en}</p>
                            <SkuLine sku={p.sku} barcode={p.barcode} className="mt-0.5" />
                            {p.present_on_store === false && (
                              <span className="inline-block mt-1 text-[9px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-300 border border-amber-500/30" data-testid={`archived-badge-${p.sku}`}>
                                {isRTL ? "غير موجود في المتجر" : "Not on store"}
                              </span>
                            )}
                            {p.discovered_via === "auto_sync" && p.present_on_store !== false && (
                              <span className="inline-block mt-1 ms-1 text-[9px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded-full bg-[#1E988E]/15 text-[#6AC1B5] border border-[#1E988E]/30" title={isRTL ? "تمت إضافته تلقائيًا من متجرك" : "Auto-discovered from your store"} data-testid={`autosynced-badge-${p.sku}`}>
                                {isRTL ? "تمت المزامنة" : "Auto-synced"}
                              </span>
                            )}
                            {p.market_position && (
                              <div className="mt-1">
                                <MarketPositionBadge mp={p.market_position} testIdPrefix={`mp-${p.sku}`} />
                              </div>
                            )}
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
                      {p.competitor_min_price != null && p.competitor_max_price != null && p.competitor_min_price !== p.competitor_max_price && (
                        <p className="text-[10px] text-[#A1E4DB]" title={isRTL ? "نطاق سعر المنافسين" : "Competitor price range"}>
                          {isRTL ? "السوق" : "Mkt"}: {p.competitor_min_price}–{p.competitor_max_price}
                        </p>
                      )}
                      {p.competitor_min_price != null && p.competitor_max_price === p.competitor_min_price && (
                        <p className="text-[10px] text-[#A1E4DB]">
                          {isRTL ? "السوق" : "Mkt"}: {p.competitor_min_price}
                        </p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {p.vs_my_price_pct == null ? (
                      <span className="text-xs text-[#A1E4DB] opacity-60" title={isRTL ? "لا توجد بيانات منافس" : "No competitor data"}>—</span>
                    ) : (
                      <span
                        className={`text-xs font-semibold ${p.vs_my_price_pct >= 0 ? "text-[#10B981]" : "text-[#EF4444]"}`}
                        title={p.vs_my_price_pct >= 0 ? (isRTL ? "سعرك أقل من أرخص منافس" : "Your price is below the cheapest competitor") : (isRTL ? "هناك منافس يقدم سعرًا أقل منك" : "A competitor is undercutting you")}
                        data-testid={`vs-my-price-${p.sku}`}
                      >
                        {p.vs_my_price_pct > 0 ? "+" : ""}{p.vs_my_price_pct}%
                      </span>
                    )}
                  </TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number" title={isRTL ? "تقدير مبيعات السوق" : "Market-wide sales estimate"}>{p.qty_sold_est.toLocaleString()}</span></TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number" title={isRTL ? "تقدير إيرادات السوق" : "Market-wide revenue estimate"}>{p.revenue_est.toLocaleString()} {t("sar")}</span></TableCell>
                  <TableCell><Badge className="text-[11px] rounded-full bg-white/5 border-white/10 text-[#A1E4DB]" title={isRTL ? "عدد المنافسين الذين يبيعون نفس المنتج" : "Number of competitors selling this product"}>{p.num_competitors != null ? p.num_competitors : Math.max(0, (p.num_sellers || 0) - 1)}</Badge></TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-0.5">
                      <StockBadge signal={p.my_stock_signal || p.stock_signal} />
                      {p.my_quantity != null && (
                        <span className="text-[10px] text-[#A1E4DB] font-mono" data-testid={`my-stock-qty-${p.sku}`}>
                          {p.my_quantity} {isRTL ? "متوفر" : "in stock"}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell><ConfBadge tier={p.source_tier} score={p.confidence_score} /></TableCell>
                </TableRow>
                );
              })
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
