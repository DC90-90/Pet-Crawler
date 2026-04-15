import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Search, Download, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import ProductDetailPanel from "@/components/ProductDetailPanel";

const RANGE_OPTIONS = [7, 14, 30, 90];

function StockBadge({ signal }) {
  const cls = { HIGH: "stock-high", MEDIUM: "stock-medium", LOW: "stock-low", OOS: "stock-oos" };
  return <span className={`text-xs font-bold ${cls[signal] || ""}`}>{signal}</span>;
}

function ConfBadge({ tier, score }) {
  const cls = { 1: "tier-1", 2: "tier-2", 3: "tier-3" };
  return (
    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded ${cls[tier] || "tier-2"}`}>
      T{tier} {score}%
    </span>
  );
}

function SortIcon({ field, sortBy, sortOrder }) {
  if (sortBy !== field) return <ArrowUpDown className="w-3 h-3 ms-1 opacity-30" />;
  return sortOrder === "asc" ? <ArrowUp className="w-3 h-3 ms-1 text-[#002DF5]" /> : <ArrowDown className="w-3 h-3 ms-1 text-[#002DF5]" />;
}

export default function MyProductsPage() {
  const { t } = useI18n();
  const [data, setData] = useState({ kpis: {}, products: [] });
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const [sortBy, setSortBy] = useState("revenue_est");
  const [sortOrder, setSortOrder] = useState("desc");
  const [selectedSku, setSelectedSku] = useState(null);

  const categories = [...new Set(data.products.map((p) => p.category))].sort();

  const fetchData = useCallback(() => {
    setLoading(true);
    api.get("/my-products", { params: { days, search: search || undefined, category: category !== "all" ? category : undefined, sort_by: sortBy, sort_order: sortOrder } })
      .then((r) => setData(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [days, search, category, sortBy, sortOrder]);

  useEffect(() => { fetchData(); }, [fetchData]);

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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0A0A0A]">{t("nav_products")}</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">{t("subtitle")}</p>
        </div>
        <Button variant="outline" size="sm" onClick={handleExport} className="rounded-md text-xs" data-testid="export-csv-btn">
          <Download className="w-3.5 h-3.5 me-1.5" />{t("btn_export")}
        </Button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { key: "kpi_products", val: kpis.total_products ?? "-", color: "#002DF5" },
          { key: "kpi_units_sold", val: (kpis.total_units_sold ?? 0).toLocaleString(), color: "#00C853" },
          { key: "kpi_revenue", val: `${(kpis.total_revenue ?? 0).toLocaleString()} ${t("sar")}`, color: "#002DF5" },
          { key: "kpi_market_share", val: `${kpis.avg_market_share ?? 0}%`, color: "#FFB300" },
        ].map((k) => (
          <div key={k.key} className="kpi-card" data-testid={`kpi-${k.key}`}>
            <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">{t(k.key)}</p>
            <p className="text-2xl font-bold tracking-tighter text-[#0A0A0A] mt-1">{k.val}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 bg-white border border-[#E5E7EB] rounded-md p-3">
        <div className="flex gap-1" data-testid="date-range-picker">
          {RANGE_OPTIONS.map((d) => (
            <Button key={d} size="sm" variant={days === d ? "default" : "outline"}
              onClick={() => setDays(d)}
              className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#002DF5] text-white" : ""}`}
              data-testid={`range-${d}d`}>{t(`d${d}`)}</Button>
          ))}
        </div>
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute start-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#9CA3AF]" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("search")}
            className="ps-8 h-8 text-sm rounded-md" data-testid="product-search-input" />
        </div>
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger className="w-[150px] h-8 text-xs rounded-md" data-testid="filter-category">
            <SelectValue placeholder={t("all_categories")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t("all_categories")}</SelectItem>
            {categories.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="bg-white border border-[#E5E7EB] rounded-md overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-[#F9FAFB]">
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
                  className={`text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF] ${col.sortable ? "cursor-pointer select-none hover:bg-[#F3F4F6]" : ""}`}
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
              <TableRow><TableCell colSpan={9} className="text-center py-16 text-[#9CA3AF] text-sm">{t("loading")}</TableCell></TableRow>
            ) : data.products.length === 0 ? (
              <TableRow><TableCell colSpan={9} className="text-center py-16 text-[#9CA3AF] text-sm">{t("no_data")}</TableCell></TableRow>
            ) : (
              data.products.map((p) => (
                <TableRow key={p.sku} className="cursor-pointer hover:bg-[#F9FAFB] transition-colors" onClick={() => setSelectedSku(p.sku)} data-testid={`product-row-${p.sku}`}>
                  <TableCell>
                    <div>
                      <p className="text-sm font-medium text-[#0A0A0A] leading-tight">{p.name_ar}</p>
                      <p className="text-[11px] text-[#9CA3AF]">{p.name_en}</p>
                    </div>
                  </TableCell>
                  <TableCell><span className="text-xs font-mono text-[#4B5563]">{p.sku}</span></TableCell>
                  <TableCell>
                    <div>
                      <span className="text-sm font-semibold">{p.price} {t("sar")}</span>
                      {p.min_price !== p.max_price && (
                        <p className="text-[10px] text-[#9CA3AF]">{p.min_price}-{p.max_price}</p>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className={`text-xs font-semibold ${p.vs_lowest_pct > 0 ? "text-red-500" : "text-green-600"}`}>
                      {p.vs_lowest_pct > 0 ? "+" : ""}{p.vs_lowest_pct}%
                    </span>
                  </TableCell>
                  <TableCell><span className="text-sm font-semibold">{p.qty_sold_est.toLocaleString()}</span></TableCell>
                  <TableCell><span className="text-sm font-semibold">{p.revenue_est.toLocaleString()} {t("sar")}</span></TableCell>
                  <TableCell><Badge variant="secondary" className="text-[11px] rounded-md">{p.num_sellers}</Badge></TableCell>
                  <TableCell><StockBadge signal={p.stock_signal} /></TableCell>
                  <TableCell><ConfBadge tier={p.source_tier} score={p.confidence_score} /></TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Product Detail Panel */}
      <ProductDetailPanel sku={selectedSku} onClose={() => setSelectedSku(null)} />
    </div>
  );
}
