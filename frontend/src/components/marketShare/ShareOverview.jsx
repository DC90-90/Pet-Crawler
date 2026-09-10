import { useEffect, useState } from "react";
import api from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { Badge } from "@/components/ui/badge";
import { AlertTriangle, Database, Store as StoreIcon, TrendingUp, PackageX } from "lucide-react";
import { SourceChip, ConfidenceBadge, fmtMoney, fmtNum, fmtPct, TrendCell } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");

export default function ShareOverview({ days, includeToday, filters, onPickProduct, onGoto }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    setErr(null);
    api.get("/market-share/overview", { params: { days, include_today: includeToday, ...(filters || {}) } })
      .then((r) => live && setD(r.data))
      .catch((e) => live && setErr(e.response?.data?.detail || "Failed to load overview"));
    return () => { live = false; };
  }, [days, includeToday, filters]);

  if (err) return <p className="text-sm text-[#EF4444]" data-testid="ms-overview-error">{err}</p>;
  if (!d) return <p className="text-sm text-[#A1E4DB]">Loading…</p>;
  const k = d.kpis || {};
  const q = d.data_quality || {};
  const noSales = !k.stores_with_sales_data;

  return (
    <div className="space-y-5" data-testid="ms-overview">
      <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/10">
        <Database className="w-4 h-4 text-[#1E988E] mt-0.5 shrink-0" />
        <p className="text-[11px] text-[#A1E4DB]" data-testid="ms-tracked-market-note">
          Market share is based on tracked measured data inside Daleel, not the total Saudi
          market ({d.window?.date_from} → {d.window?.date_to}).{" "}
          {d.filtered && (
            <span className="text-[#5FD3C7]" data-testid="ms-overview-filtered">
              These KPIs cover only the filtered selection.{" "}
            </span>
          )}
          {k.stores_with_sales_data} of {k.tracked_stores} tracked stores currently
          publish data we can measure sales from. Share percentages count only the{" "}
          <span className="text-white">{fmtNum(k.products_contested)}</span> product(s) where at
          least one other tracked seller's sales are measurable — the{" "}
          <span className="text-white">{fmtNum(k.products_sole_seller)}</span> product(s) only we
          sell are reported separately so they cannot inflate the headline.
        </p>
      </div>

      {noSales && (
        <div className="flex items-start gap-2 px-3 py-2.5 rounded-xl bg-[#F59E0B]/10 border border-[#F59E0B]/25"
          data-testid="ms-no-sales-banner">
          <AlertTriangle className="w-4 h-4 text-[#F59E0B] mt-0.5 shrink-0" />
          <div className="text-[11px] text-[#F59E0B]">
            <p className="font-semibold">No measurable sales in this window yet — shares are withheld, not zeroed.</p>
            <p className="mt-0.5">
              Units are derived by comparing two crawls of the same product. Every store below shows
              how many days it was observed; a store needs at least two before any sales figure can exist.
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          ["My revenue share", k.my_revenue_share_pct === null || k.my_revenue_share_pct === undefined
            ? "Unavailable" : fmtPct(k.my_revenue_share_pct), k.my_units_source, "ms-kpi-revenue-share"],
          ["My unit share", k.my_unit_share_pct === null || k.my_unit_share_pct === undefined
            ? "Unavailable" : fmtPct(k.my_unit_share_pct), k.my_units_source, "ms-kpi-unit-share"],
          ["Tracked market revenue", k.market_revenue === null || k.market_revenue === undefined
            ? "Unavailable" : fmtMoney(k.market_revenue), null, "ms-kpi-market-revenue"],
          ["My measured revenue", k.my_revenue === null || k.my_revenue === undefined
            ? "Unavailable" : fmtMoney(k.my_revenue), k.my_units_source, "ms-kpi-my-revenue"],
        ].map(([label, value, source, tid]) => (
          <div key={label} className="kpi-card" data-testid={tid}>
            <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p>
            <p className={`text-xl font-bold mt-1 ${value === "Unavailable" ? "text-[#F59E0B]" : "text-white"}`} dir="ltr">
              {value}
            </p>
            {source && <div className="mt-1.5"><SourceChip source={source} compact /></div>}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          ["Products in my catalog", fmtNum(k.my_catalog_products), "ms-kpi-catalog"],
          ["…with a tracked competitor", fmtNum(k.products_with_tracked_competitor), "ms-kpi-with-competitor"],
          ["…contested (share is comparable)", fmtNum(k.products_contested), "ms-kpi-contested"],
          ["Only I sell it (excluded from share)", fmtNum(k.products_sole_seller), "ms-kpi-sole"],
        ].map(([label, value, tid]) => (
          <div key={label} className="kpi-card !p-3" data-testid={tid}>
            <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p>
            <p className="text-lg font-bold text-white mt-0.5" dir="ltr">{value}</p>
          </div>
        ))}
      </div>

      <div className="glass-card p-4">
        <div className="flex items-center gap-2 mb-3">
          <StoreIcon className="w-4 h-4 text-[#1E988E]" />
          <h3 className="text-sm font-semibold text-white">Tracked stores — what we can measure</h3>
        </div>
        <div className="rounded-md border border-white/10 divide-y divide-white/5">
          {(d.stores || []).map((s, i) => (
            <div key={s.store_id} className="flex items-center justify-between px-3 py-2"
              data-testid={`ms-store-row-${i}`}>
              <div className="flex items-center gap-2 min-w-0">
                <span className="text-xs text-white truncate">{s.store_name}</span>
                {s.is_own && <Badge className="text-[9px] bg-[#FF3B30]/15 text-[#FF3B30] border-[#FF3B30]/25">Mine</Badge>}
                <span className="text-[10px] text-[#A1E4DB] uppercase">{s.platform}</span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <span className="text-[10px] text-[#A1E4DB]" dir="ltr">{s.days_observed} day(s) observed</span>
                <SourceChip compact source={
                  s.sales_data_available
                    ? (s.sales_signal === "counter" ? "sold_counter_diff" : "stock_depletion")
                    : "unavailable"} />
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="glass-card p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-[#10B981]" />
              <h3 className="text-sm font-semibold text-white">Where I hold the most share</h3>
            </div>
            <button onClick={() => onGoto("my-products")}
              className="text-[10px] text-[#1E988E] hover:underline" data-testid="ms-goto-my-products">
              All products →
            </button>
          </div>
          {(d.top_share || []).length === 0 ? (
            <p className="text-[11px] text-[#F59E0B]" data-testid="ms-top-share-empty">
              No product has a measurable share in this window
            </p>
          ) : (
            <div className="space-y-1.5">
              {(d.top_share || []).map((r, i) => (
                <button key={r.sku} onClick={() => onPickProduct(r)}
                  className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-md hover:bg-white/5 text-start"
                  data-testid={`ms-top-share-${i}`}>
                  <span className="text-xs text-white truncate">{r.name}</span>
                  <span className="text-xs font-semibold text-[#10B981] shrink-0" dir="ltr">
                    {fmtPct(r.revenue_share_pct)}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="glass-card p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <PackageX className="w-4 h-4 text-[#F59E0B]" />
              <h3 className="text-sm font-semibold text-white">Biggest gaps in my catalog</h3>
            </div>
            <button onClick={() => onGoto("missing")}
              className="text-[10px] text-[#1E988E] hover:underline" data-testid="ms-goto-missing">
              All opportunities →
            </button>
          </div>
          {(d.top_opportunities || []).length === 0 ? (
            <p className="text-[11px] text-[#A1E4DB]">No products outside my catalog are tracked yet</p>
          ) : (
            <div className="space-y-1.5">
              {(d.top_opportunities || []).map((r, i) => (
                <button key={r.canonical_key} onClick={() => onPickProduct(r)}
                  className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-md hover:bg-white/5 text-start"
                  data-testid={`ms-top-opp-${i}`}>
                  <div className="min-w-0">
                    <p className="text-xs text-white truncate">{r.name}</p>
                    <p className="text-[10px] text-[#A1E4DB]">
                      {r.competitor_count} seller(s) · {catLabel(r.category)}
                    </p>
                  </div>
                  <div className="text-end shrink-0">
                    <p className="text-xs font-semibold text-[#F59E0B]" dir="ltr">{r.opportunity_score}</p>
                    <p className="text-[9px] text-[#A1E4DB]">score</p>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="glass-card p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Top brands in the tracked market</h3>
          <div className="space-y-1.5">
            {(d.top_brands || []).map((b, i) => (
              <div key={b.brand} className="flex items-center justify-between" data-testid={`ms-overview-brand-${i}`}>
                <span className="text-xs text-white truncate">{b.brand}</span>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtMoney(b.revenue)}</span>
                  <ConfidenceBadge level={b.confidence} reason={b.coverage} />
                </div>
              </div>
            ))}
            {(d.top_brands || []).length === 0 && (
              <p className="text-[11px] text-[#A1E4DB]">No brand could be resolved from the tracked catalog</p>
            )}
          </div>
        </div>
        <div className="glass-card p-4">
          <h3 className="text-sm font-semibold text-white mb-3">Top categories</h3>
          <div className="space-y-1.5">
            {(d.top_categories || []).map((c, i) => (
              <div key={c.category} className="flex items-center justify-between" data-testid={`ms-overview-cat-${i}`}>
                <span className="text-xs text-white truncate">{catLabel(c.category)}</span>
                <div className="flex items-center gap-2 shrink-0">
                  <span className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtMoney(c.revenue)}</span>
                  <ConfidenceBadge level={c.confidence} reason={c.coverage} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="glass-card p-4" data-testid="ms-data-quality">
        <h3 className="text-sm font-semibold text-white mb-3">Data quality in this window</h3>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            ["High confidence rows", q.rows_high_confidence],
            ["Medium", q.rows_medium_confidence],
            ["Low", q.rows_low_confidence],
            ["Unavailable", q.rows_unavailable],
          ].map(([l, v]) => (
            <div key={l}>
              <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{l}</p>
              <p className="text-base font-bold text-white mt-0.5" dir="ltr">{fmtNum(v)}</p>
            </div>
          ))}
        </div>
        <div className="mt-3 grid sm:grid-cols-2 gap-x-6 gap-y-1 text-[11px] text-[#A1E4DB]">
          <p>Own orders ledger: {q.own_orders_ledger_connected
            ? <span className="text-[#10B981]">connected — my units are invoiced</span>
            : <span className="text-[#F59E0B]">not connected — my units fall back to stock depletion</span>}</p>
          <p>Brands resolved: {fmtNum(q.my_products_with_brand)} ({fmtNum(q.my_products_brand_derived)} derived from product names)</p>
          <p>Categories present: {fmtNum(q.my_products_with_category)}</p>
          <p>Sellers excluded as a different pack size: {fmtNum(q.sellers_excluded_pack_mismatch)}</p>
        </div>
      </div>
    </div>
  );
}
