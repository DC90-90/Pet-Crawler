/**
 * Columns of the Brands and Categories tables (one row per brand or
 * category: market_share.aggregate_groups). Every field a row carries.
 */
import { ConfidenceBadge, TrendCell, fmtMoney, fmtNum, fmtPct } from "./SourceChip";

const dash = <span className="text-[#A1E4DB]/60">—</span>;

export function groupColumns(key, label, format = (v) => v) {
  return [
    { id: key, label, type: "text", width: 170, always: true, get: (r) => format(r[key]),
      render: (r) => <span className="text-white font-medium">{format(r[key])}</span> },
    { id: "units", label: "Tracked movement (units)", type: "number", width: 120, align: "end", render: (r) => fmtNum(r.units) },
    { id: "revenue", label: "Observed value / proxy (SAR)", type: "number", width: 140, align: "end", render: (r) => fmtMoney(r.revenue) },
    { id: "revenue_share_pct", label: "Share of the tracked market (%)", type: "number", width: 120, align: "end",
      render: (r) => (r.revenue_share_pct == null ? dash : <span className="font-semibold text-[#5FD3C7]">{fmtPct(r.revenue_share_pct)}</span>) },
    { id: "my_units", label: "My units", type: "number", width: 100, align: "end", render: (r) => fmtNum(r.my_units) },
    { id: "my_revenue", label: "My value (SAR)", type: "number", width: 120, align: "end", render: (r) => fmtMoney(r.my_revenue) },
    { id: "my_revenue_share_pct", label: `My share of the ${label.toLowerCase()} (%)`, type: "number", width: 120, align: "end",
      render: (r) => (r.my_revenue_share_pct == null ? <span className="text-[#F59E0B]">Unavailable</span> : <span className="font-semibold text-[#10B981]">{fmtPct(r.my_revenue_share_pct)}</span>) },
    { id: "products", label: "Products", type: "number", width: 90, align: "end", render: (r) => fmtNum(r.products) },
    { id: "my_products_count", label: "In my catalogue", type: "number", width: 100, align: "end", render: (r) => fmtNum(r.my_products_count) },
    { id: "missing_products", label: "Products I don't sell", type: "number", width: 110, align: "end", render: (r) => fmtNum(r.missing_products) },
    { id: "missing_opportunity_value", label: "Value of products I don't sell (SAR)", type: "number", width: 140, align: "end",
      render: (r) => fmtMoney(r.missing_opportunity_value) },
    { id: "measured_products", label: "Products with a sales signal", type: "number", width: 120, align: "end", render: (r) => fmtNum(r.measured_products) },
    { id: "top_products", label: "Top products", type: "text", width: 280, get: (r) => (r.top_products || []).map((p) => p.name),
      exportValue: (r) => (r.top_products || []).map((p) => `${p.name} ${p.revenue ?? ""}`),
      render: (r) => (r.top_products || []).length === 0 ? dash : (
        <div className="space-y-0.5">{r.top_products.map((p) => <p key={p.sku} className="text-xs">{p.name} · <span dir="ltr">{fmtMoney(p.revenue)}</span></p>)}</div>) },
    { id: "top_stores", label: "Top stores", type: "text", width: 220, get: (r) => (r.top_stores || []).map((s) => s.store_name),
      exportValue: (r) => (r.top_stores || []).map((s) => `${s.store_name} ${s.revenue ?? ""}`),
      render: (r) => (r.top_stores || []).length === 0 ? dash : (
        <div className="space-y-0.5">{r.top_stores.map((s) => <p key={s.store_name} className="text-xs">{s.store_name} · <span dir="ltr">{fmtMoney(s.revenue)}</span>{s.units != null && ` · ${fmtNum(s.units)} units`}</p>)}</div>) },
    { id: "trend_rev", label: "Value trend vs previous period (%)", type: "number", width: 130, align: "end",
      get: (r) => r.trend?.revenue_pct, render: (r) => <TrendCell pct={r.trend?.revenue_pct} /> },
    { id: "coverage", label: "Coverage", type: "text", width: 200, hidden: true },
    { id: "confidence", label: "Confidence", type: "enum", width: 120, options: [["high", "High"], ["medium", "Medium"], ["low", "Low"], ["unavailable", "Unavailable"]],
      render: (r) => <ConfidenceBadge level={r.confidence} reason={r.coverage} /> },
  ];
}
