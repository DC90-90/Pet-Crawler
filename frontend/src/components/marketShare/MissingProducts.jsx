import { useCallback, useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { FacetTabs } from "@/components/MarketTabs";
import DataTable from "@/components/DataTable";
import { ConfidenceBadge, Unavailable, TrendCell, SourceChip, SOURCE_META, fmtMoney, fmtNum, REASON_TEXT } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");
const LIMIT = 100;
// A row without a barcode carries its internal grouping key there ("offer:…").
const cleanBarcode = (b) => { const m = /^gtin:(\d+)/.exec(b || ""); return m ? m[1] : /^\d{8,14}$/.test(b || "") ? b : null; };

// Every field a row carries, as a column; the less used start hidden and are
// one click away in Columns (27 Oct 2026 — "display all the data").
const COLUMNS = [
  { id: "name", label: "Product", type: "text", width: 260, always: true, get: (r) => [r.name, r.name_ar],
    render: (r) => (<><p className="text-white">{r.name}</p>{r.name_ar && r.name_ar !== r.name && <p className="text-xs text-[#A1E4DB]">{r.name_ar}</p>}</>) },
  { id: "brand", label: "Brand", type: "text", width: 130 },
  { id: "category", label: "Category", type: "text", width: 120, render: (r) => catLabel(r.category) },
  { id: "barcode", label: "Barcode", type: "text", width: 140, get: (r) => cleanBarcode(r.barcode),
    render: (r) => <span dir="ltr">{cleanBarcode(r.barcode) || "—"}</span> },
  { id: "sku", label: "SKU", type: "text", width: 140, hidden: true, render: (r) => <span dir="ltr">{r.sku}</span> },
  { id: "competitor_count", label: "Stores selling it", type: "number", width: 110, align: "end" },
  { id: "in_stock_sellers", label: "Stores with stock", type: "number", width: 110, align: "end" },
  { id: "competitors", label: "Competitors", type: "text", width: 200, get: (r) => r.competitors,
    render: (r) => (r.competitors || []).join(", ") || "—" },
  { id: "sellers", field: "sellers.store_name", label: "Every seller: price · stock · movement", type: "text", width: 320,
    get: (r) => (r.sellers || []).map((s) => s.store_name),
    exportValue: (r) => (r.sellers || []).map((s) => `${s.store_name} ${s.price ?? "—"} SAR ${s.in_stock === false ? "out of stock" : s.in_stock ? "in stock" : "stock unknown"} ${s.units ?? "—"} units`),
    render: (r) => (
      <div className="space-y-0.5">
        {(r.sellers || []).map((s) => (
          <p key={s.store_id || s.store_name} className="text-xs">
            <span className="text-white">{s.store_name}</span>
            <span className="text-[#A1E4DB]"> · {s.price != null ? fmtMoney(s.price) : "—"}</span>
            <span className={s.in_stock === false ? "text-[#F59E0B]" : "text-[#A1E4DB]"}> · {s.in_stock === false ? "out of stock" : s.in_stock ? "in stock" : "stock unknown"}</span>
            <span className="text-[#A1E4DB]"> · {s.units != null ? `${fmtNum(s.units)} units` : "no signal"}</span>
          </p>
        ))}
      </div>) },
  { id: "market_units", label: "Tracked movement (units)", type: "number", width: 120, align: "end",
    render: (r) => (r.market_units === null ? <Unavailable reason={r.unavailable_reason} /> : fmtNum(r.market_units)) },
  { id: "units_basis", label: "Basis", type: "enum", width: 170,
    options: Object.entries(SOURCE_META).map(([k, m]) => [k, m.label]),
    render: (r) => (
      <div className="flex flex-wrap gap-1">
        {(r.units_basis || []).length === 0 ? <SourceChip source="unavailable" compact /> : r.units_basis.map((b) => <SourceChip key={b} source={b} compact />)}
        {r.sellers_without_signal > 0 && <span className="text-xs text-[#A1E4DB]">+{r.sellers_without_signal} with no signal</span>}
      </div>) },
  { id: "sellers_without_signal", label: "Stores without a sales signal", type: "number", width: 120, align: "end", hidden: true },
  { id: "market_revenue", label: "Shelf-value proxy (SAR)", type: "number", width: 130, align: "end",
    render: (r) => (r.market_revenue === null ? <Unavailable reason={r.unavailable_reason} /> : fmtMoney(r.market_revenue)) },
  { id: "top_competitor", field: "top_competitor.store_name", label: "Top competitor", type: "text", width: 140,
    get: (r) => r.top_competitor?.store_name,
    render: (r) => r.top_competitor ? <>{r.top_competitor.store_name}<span className="block text-xs text-[#A1E4DB]">{fmtNum(r.top_competitor.units)} units</span></> : "—" },
  { id: "avg_price", label: "Avg price (SAR)", type: "number", width: 110, align: "end", render: (r) => fmtMoney(r.avg_price) },
  { id: "min_price", label: "Lowest price (SAR)", type: "number", width: 110, align: "end", render: (r) => fmtMoney(r.min_price) },
  { id: "max_price", label: "Highest price (SAR)", type: "number", width: 110, align: "end", render: (r) => fmtMoney(r.max_price) },
  { id: "price_spread_ratio", label: "Highest ÷ lowest", type: "number", width: 100, align: "end", hidden: true },
  { id: "trend_rev", field: "trend.revenue_pct", label: "Value trend vs previous period (%)", type: "number", width: 130, align: "end",
    get: (r) => r.trend?.revenue_pct, render: (r) => <TrendCell pct={r.trend?.revenue_pct} /> },
  { id: "trend_units", field: "trend.units_pct", label: "Movement trend vs previous period (%)", type: "number", width: 130, align: "end", hidden: true,
    get: (r) => r.trend?.units_pct, render: (r) => <TrendCell pct={r.trend?.units_pct} /> },
  { id: "opportunity_score", label: "Opportunity (0–100)", type: "number", width: 110, align: "end",
    render: (r) => <span className="font-bold text-[#F59E0B]" title={r.opportunity_formula}>{r.opportunity_score}</span> },
  { id: "confidence", label: "Confidence", type: "enum", width: 120, options: [["high", "High"], ["medium", "Medium"], ["low", "Low"], ["unavailable", "Unavailable"]],
    render: (r) => <ConfidenceBadge level={r.confidence} reason={REASON_TEXT[r.unavailable_reason]} /> },
  { id: "recommended_action", label: "Recommended action", type: "text", width: 260, render: (r) => <span className="text-[#5FD3C7]">{r.recommended_action}</span> },
];

export default function MissingProducts({ days, includeToday, filters, onPickProduct }) {
  const [data, setData] = useState(null);
  const [query, setQuery] = useState(null);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [animal, setAnimal] = useState("all");
  const [ptype, setPtype] = useState("all");
  const [facets, setFacets] = useState(null);

  const params = useCallback((q, offset, limit) => {
    const { catalog, min_confidence, ...rest } = filters || {};
    return { days, include_today: includeToday, limit, offset, ...rest, ...(q || {}),
             animal: animal === "all" ? undefined : animal, ptype: ptype === "all" ? undefined : ptype };
  }, [days, includeToday, filters, animal, ptype]);

  useEffect(() => { setPage(0); }, [filters, days, animal, ptype, query]);

  useEffect(() => {
    if (query === null) return;
    let live = true;
    setLoading(true); setError(false);
    api.get("/market-share/missing-products", { params: params(query, page * LIMIT, LIMIT) })
      .then((r) => { if (live) { setData(r.data); setFacets(r.data.facets || null); } })
      .catch((failure) => live && setError(failure))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [query, page, params, retry]);

  // Export: every filtered row, 500 at a time.
  const fetchAll = async (q) => {
    const out = [];
    for (let offset = 0; offset < 50000; offset += 500) {
      const r = await api.get("/market-share/missing-products", { params: params(q, offset, 500), timeout: 60000 });
      out.push(...(r.data.rows || []));
      if (out.length >= (r.data.total || 0) || !(r.data.rows || []).length) break;
    }
    return out;
  };

  if (error) return <RequestError id="ms-missing" error={error} onRetry={() => setRetry((n) => n + 1)} />;
  const total = data?.total || 0;
  return (
    <div className="space-y-3" data-testid="ms-missing-products">
      {facets && <FacetTabs counts={facets} animal={animal} ptype={ptype} onAnimal={setAnimal} onType={setPtype} prefix="ms-missing" />}
      <p className="text-sm text-[#A1E4DB]" data-testid="ms-missing-count">
        {fmtNum(data?.total_untruncated ?? total)} products competitors sell that I don't
        {data?.total_untruncated > total && ` · ${fmtNum(total)} match the filters`}
        {" · shelf-value proxy "}<span dir="ltr">{fmtMoney(data?.opportunity_value)}</span>
        {" · my share of every row is 0% (not in my catalogue)"}
      </p>
      <DataTable columns={COLUMNS} rows={data?.rows || []} total={total} allTotal={data?.total_untruncated ?? total} loading={loading && !data}
        storageKey="ms-missing" exportName="daleel-products-i-dont-sell" rowKey={(r) => r.canonical_key}
        onRowClick={onPickProduct} onQuery={setQuery} fetchAll={fetchAll}
        initialSort={{ id: "opportunity_score", dir: "desc" }} />
      {total > LIMIT && (
        <div className="flex items-center justify-between">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-missing-prev">Previous</Button>
          <span className="text-sm text-[#A1E4DB]" dir="ltr">{page * LIMIT + 1}–{Math.min((page + 1) * LIMIT, total)} of {fmtNum(total)}</span>
          <Button variant="outline" size="sm" disabled={(page + 1) * LIMIT >= total} onClick={() => setPage((p) => p + 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-missing-next">Next</Button>
        </div>
      )}
    </div>
  );
}
