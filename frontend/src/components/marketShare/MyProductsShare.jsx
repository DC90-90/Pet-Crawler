import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import DataTable from "@/components/DataTable";
import { SourceChip, SOURCE_META, ConfidenceBadge, Unavailable, TrendCell, fmtMoney, fmtNum, fmtPct, REASON_TEXT } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");
const LIMIT = 100;
const dash = <span className="text-[#A1E4DB]/60">—</span>;

// Every field a row carries, as a column (27 Oct 2026 — filter on every
// column, all the data visible).
const COLUMNS = [
  { id: "name", label: "Product", type: "text", width: 260, always: true, get: (r) => [r.name, r.name_ar],
    render: (r) => (<><p className="text-white">{r.name}</p>{r.name_ar && r.name_ar !== r.name && <p className="text-xs text-[#A1E4DB]">{r.name_ar}</p>}</>) },
  { id: "brand", label: "Brand", type: "text", width: 130,
    render: (r) => r.brand ? <>{r.brand}{r.brand_source === "derived_from_name" && <span title="Read from the product name" className="ms-1 text-[#5FD3C7]">~</span>}</> : <span className="text-[#F59E0B]">unknown</span> },
  { id: "category", label: "Category", type: "text", width: 120, render: (r) => catLabel(r.category) },
  { id: "sku", label: "SKU", type: "text", width: 130, render: (r) => <span dir="ltr">{r.sku}</span> },
  { id: "barcode", label: "Barcode", type: "text", width: 140, hidden: true, render: (r) => <span dir="ltr">{r.barcode || "—"}</span> },
  { id: "my_price", label: "My price (SAR)", type: "number", width: 110, align: "end", render: (r) => fmtMoney(r.my_price) },
  { id: "my_units", label: "My units", type: "number", width: 100, align: "end",
    render: (r) => (r.my_units == null ? <Unavailable reason={r.my_unavailable_reason} /> : fmtNum(r.my_units)) },
  { id: "my_revenue", label: "My value (SAR)", type: "number", width: 120, align: "end",
    render: (r) => (r.my_revenue == null ? <Unavailable reason={r.my_unavailable_reason} /> : fmtMoney(r.my_revenue)) },
  { id: "my_units_source", label: "My figures from", type: "enum", width: 140, options: Object.entries(SOURCE_META).map(([k, m]) => [k, m.label]),
    render: (r) => r.my_units_source ? <SourceChip source={r.my_units_source} compact /> : dash },
  { id: "market_units", label: "Tracked movement (units)", type: "number", width: 120, align: "end",
    render: (r) => (r.market_units == null ? <Unavailable reason={r.unavailable_reason} /> : fmtNum(r.market_units)) },
  { id: "market_revenue", label: "Shelf-value proxy (SAR)", type: "number", width: 130, align: "end",
    render: (r) => (r.market_revenue == null ? <Unavailable reason={r.unavailable_reason} /> : fmtMoney(r.market_revenue)) },
  { id: "unit_share_pct", label: "My unit share (%)", type: "number", width: 110, align: "end",
    render: (r) => (r.unit_share_pct == null ? dash : <span className="font-semibold text-[#5FD3C7]">{fmtPct(r.unit_share_pct)}</span>) },
  { id: "revenue_share_pct", label: "My value share (%)", type: "number", width: 110, align: "end",
    render: (r) => (r.revenue_share_pct == null ? dash : <span className="font-semibold text-[#10B981]">{fmtPct(r.revenue_share_pct)}</span>) },
  { id: "sellers_total", label: "Stores carrying (me included)", type: "number", width: 120, align: "end",
    render: (r) => <>{r.sellers_total}<span className="block text-xs text-[#A1E4DB]">{r.competitor_count} competitor{r.competitor_count === 1 ? "" : "s"} + me</span></> },
  { id: "competitor_count", label: "Competitors", type: "number", width: 100, align: "end", hidden: true },
  { id: "sellers_with_sales", label: "Stores with a sales signal", type: "number", width: 120, align: "end",
    render: (r) => <>
      <span className={r.sellers_with_sales ? "text-white" : "text-[#F59E0B]"}>{r.sellers_with_sales} of {r.sellers_total}</span>
      {r.sole_seller && <span className="block text-xs text-[#F59E0B]">only I can be measured</span>}
    </> },
  { id: "market_units_sources", label: "Market figures from", type: "enum", width: 170, hidden: true,
    options: Object.entries(SOURCE_META).map(([k, m]) => [k, m.label]),
    render: (r) => <div className="flex flex-wrap gap-1">{(r.market_units_sources || []).map((s) => <SourceChip key={s} source={s} compact />)}</div> },
  { id: "top_competitor", field: "top_competitor.store_name", label: "Top competitor", type: "text", width: 140,
    get: (r) => r.top_competitor?.store_name,
    render: (r) => r.top_competitor ? <>{r.top_competitor.store_name}{r.top_competitor.units != null && <span className="block text-xs text-[#A1E4DB]">{fmtNum(r.top_competitor.units)} units</span>}</> : "—" },
  { id: "competitor_price_min", label: "Lowest competitor price (SAR)", type: "number", width: 120, align: "end", render: (r) => fmtMoney(r.competitor_price_min) },
  { id: "competitor_price_avg", label: "Average competitor price (SAR)", type: "number", width: 120, align: "end", hidden: true, render: (r) => fmtMoney(r.competitor_price_avg) },
  { id: "competitor_price_max", label: "Highest competitor price (SAR)", type: "number", width: 120, align: "end", render: (r) => fmtMoney(r.competitor_price_max) },
  { id: "price_spread_ratio", label: "Highest ÷ lowest", type: "number", width: 100, align: "end", hidden: true,
    render: (r) => r.price_spread_ratio == null ? dash : <>{r.price_spread_ratio}×{r.price_spread_warning && <span className="block text-xs text-[#F59E0B]" title={r.price_spread_warning}>check pack size</span>}</> },
  { id: "price_rank", label: "My price rank (1 = cheapest)", type: "number", width: 120, align: "end",
    render: (r) => r.price_rank ? <Badge className={`border ${r.price_rank === 1 ? "bg-[#10B981]/12 text-[#10B981] border-[#10B981]/25" : "bg-white/5 text-[#A1E4DB] border-white/15"}`}>#{r.price_rank} of {r.price_rank_of}</Badge> : dash },
  { id: "units_rank", label: "My units rank", type: "number", width: 110, align: "end", hidden: true,
    render: (r) => r.units_rank ? `#${r.units_rank} of ${r.units_rank_of}` : dash },
  { id: "trend_rev", field: "trend.revenue_pct", label: "Value trend vs previous period (%)", type: "number", width: 130, align: "end",
    get: (r) => r.trend?.revenue_pct, render: (r) => <TrendCell pct={r.trend?.revenue_pct} /> },
  { id: "trend_units", field: "trend.units_pct", label: "Movement trend vs previous period (%)", type: "number", width: 130, align: "end", hidden: true,
    get: (r) => r.trend?.units_pct, render: (r) => <TrendCell pct={r.trend?.units_pct} /> },
  { id: "confidence", label: "Confidence", type: "enum", width: 150, options: [["high", "High"], ["medium", "Medium"], ["low", "Low"], ["unavailable", "Unavailable"]],
    render: (r) => <div className="flex flex-col gap-1 items-start">
      <ConfidenceBadge level={r.confidence} reason={r.confidence_reason} />
      {r.unavailable_reason && <span className="text-xs text-[#F59E0B]">{REASON_TEXT[r.unavailable_reason] || r.unavailable_reason}</span>}
    </div> },
];

export default function MyProductsShare({ days, includeToday, filters, onPickProduct }) {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState(null);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  const params = useCallback((q, offset, limit) => ({ days, include_today: includeToday, limit, offset, ...filters, ...(q || {}) }),
    [days, includeToday, filters]);

  useEffect(() => { setPage(0); }, [filters, days, query]);

  useEffect(() => {
    if (query === null) return;
    let live = true;
    setLoading(true); setError(false);
    api.get("/market-share/my-products", { params: params(query, page * LIMIT, LIMIT) })
      .then((r) => live && setData(r.data))
      .catch((failure) => live && setError(failure))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [query, page, params, retry]);

  const fetchAll = async (q) => {
    const out = [];
    for (let offset = 0; offset < 20000; offset += 500) {
      const r = await api.get("/market-share/my-products", { params: params(q, offset, 500), timeout: 60000 });
      out.push(...(r.data.rows || []));
      if (out.length >= (r.data.total || 0) || !(r.data.rows || []).length) break;
    }
    return out;
  };

  if (error) return <RequestError id="ms-products" error={error} onRetry={() => setRetry((n) => n + 1)} />;
  const total = data?.total || 0;
  return (
    <div className="space-y-3" data-testid="ms-my-products">
      <p className="text-sm text-[#A1E4DB]" data-testid="ms-my-products-count">
        My observed value <span dir="ltr">{fmtMoney(data?.totals?.my_revenue)}</span> of{" "}
        <span dir="ltr">{fmtMoney(data?.totals?.market_revenue)}</span> tracked, on the rows that match the filters
      </p>
      <DataTable columns={COLUMNS} rows={data?.rows || []} total={total} loading={loading && !data}
        storageKey="ms-my-products" exportName="daleel-market-share-my-products" rowKey={(r) => r.sku}
        onRowClick={onPickProduct} onQuery={setQuery} fetchAll={fetchAll}
        initialSort={{ id: "market_revenue", dir: "desc" }} />
      {total > LIMIT && (
        <div className="flex items-center justify-between">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-prev-page">Previous</Button>
          <span className="text-sm text-[#A1E4DB]" dir="ltr">{page * LIMIT + 1}–{Math.min((page + 1) * LIMIT, total)} of {fmtNum(total)}</span>
          <Button variant="outline" size="sm" disabled={(page + 1) * LIMIT >= total} onClick={() => setPage((p) => p + 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-next-page">Next</Button>
        </div>
      )}
    </div>
  );
}
