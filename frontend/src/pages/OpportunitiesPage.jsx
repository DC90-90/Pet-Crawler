/**
 * Opportunities (15 Oct 2026) — what to add or restock, each list once:
 *   Products I don't sell   → Market Share's missing-products list (one count;
 *                              the Price Intel "Product gaps" card counted 5,320
 *                              while Market Share counted 22,044 for the same idea)
 *   Market best sellers      → /insights/top-sellers
 *   Restock opportunities    → /insights/restock-opportunities
 */
import { useMemo, useState } from "react";
import { SalesPeriod } from "@/components/SalesPeriod";
import { SectionTabs } from "@/components/SectionTabs";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PackageSearch, TrendingUp, PackageCheck, Boxes } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth, canAccessPage } from "@/App";
import { Button } from "@/components/ui/button";
import { RequestError } from "@/components/RequestError";
import { ComparisonScope, useComparisonScope } from "@/components/ComparisonScope";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import MissingProducts from "@/components/marketShare/MissingProducts";
import ProductBreakdown from "@/components/marketShare/ProductBreakdown";
import { FacetTabs, StoreTabs, facetCounts, facetMatch, storesOf } from "@/components/MarketTabs";
import { StoreLogo } from "@/components/StoreLogo";
import StockPlanner from "@/components/StockPlanner";
import DataTable from "@/components/DataTable";

const RANGES = [7, 14, 30, 90];

// Every field a best-seller row carries (27 Oct 2026 — filter on every column).
function bestColumns(isRTL) {
  return [
    { id: "rank", label: "#", type: "number", width: 60, align: "end" },
    { id: "name", label: isRTL ? "المنتج" : "Product", type: "text", width: 300, always: true, get: (s) => [s.name_ar, s.name_en],
      render: (s) => (
        <div className="flex items-start gap-2">
          <div className="w-10 h-10 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
            {s.image_url ? <img src={s.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : null}
          </div>
          <div className="min-w-0"><p className="text-white inline-flex items-center gap-1.5"><MineBadge sku={s.sku} />{s.name_ar || s.name_en}</p>
            {s.name_en && s.name_ar && s.name_en !== s.name_ar && <p className="text-xs text-[#A1E4DB]">{s.name_en}</p>}</div>
        </div>) },
    { id: "store_name", label: isRTL ? "المتجر" : "Store", type: "text", width: 140,
      render: (s) => <span className="inline-flex items-center gap-1.5"><StoreLogo storeId={s.store_id} name={s.store_name} size={14} />{s.store_name}</span> },
    { id: "category", label: isRTL ? "الفئة" : "Category", type: "text", width: 120 },
    { id: "sku", label: "SKU", type: "text", width: 130, render: (s) => <SkuLine sku={s.sku} barcode={s.barcode} /> },
    { id: "units", label: isRTL ? "الوحدات المباعة (تقدير)" : "Units sold (est.)", type: "number", width: 110, align: "end",
      render: (s) => (s.units ?? 0).toLocaleString() },
    { id: "revenue_est", label: isRTL ? "الإيراد (تقدير، ريال)" : "Revenue (est., SAR)", type: "number", width: 120, align: "end",
      render: (s) => (s.revenue_est ?? 0).toLocaleString() },
    { id: "avg_price", label: isRTL ? "متوسط السعر (ريال)" : "Average price (SAR)", type: "number", width: 110, align: "end" },
    { id: "price", label: isRTL ? "السعر الحالي (ريال)" : "Current price (SAR)", type: "number", width: 110, align: "end", hidden: true },
    { id: "velocity", label: isRTL ? "وحدات في اليوم" : "Units per day", type: "number", width: 100, align: "end", hidden: true },
    { id: "num_sellers", label: isRTL ? "عدد البائعين" : "Sellers", type: "number", width: 90, align: "end" },
    { id: "basis", label: isRTL ? "المصدر" : "Basis", type: "text", width: 140, hidden: true },
    { id: "barcode", label: isRTL ? "الباركود" : "Barcode", type: "text", width: 140, hidden: true },
  ];
}

function BestSellers({ days }) {
  const { t, isRTL } = useI18n();
  const [store, setStore] = useState("all");
  const [animal, setAnimal] = useState("all");
  const [ptype, setPtype] = useState("all");
  const q = useQuery({ queryKey: ["opps", "top-sellers", days], queryFn: async () => (await api.get("/insights/top-sellers", { params: { days } })).data });
  const all = useMemo(() => q.data || [], [q.data]);
  const inStore = useMemo(() => all.filter((r) => store === "all" || r.store_id === store), [all, store]);
  const rows = useMemo(() => inStore.filter((r) => facetMatch(r, animal, ptype)), [inStore, animal, ptype]);
  // Rank by units in the current selection, so the rank column stays meaningful when re-sorted.
  const ranked = useMemo(() => [...rows].sort((a, b) => (b.units_sold ?? b.qty_sold_est ?? 0) - (a.units_sold ?? a.qty_sold_est ?? 0))
    .map((r, i) => ({ ...r, rank: i + 1, units: r.units_sold ?? r.qty_sold_est })), [rows]);
  if (q.isError) return <RequestError id="best-sellers-request" error={q.error} onRetry={() => q.refetch()} />;
  return (
    <div className="glass-card rounded-md p-5 space-y-3" data-testid="opps-best-sellers">
      <p className="text-xs text-[#A1E4DB]">
        {isRTL ? `المنتجات الأكثر مبيعاً في المتاجر المتتبعة خلال آخر ${days} يوماً (لكل متجر على حدة). المبيعات تقديرية من حركة المخزون أو عدّاد المبيعات.`
          : `Products with the most observed sales in tracked stores over the last ${days} days, per store. Sales are estimated from stock movement or the public sold counter.`}
      </p>
      <SalesPeriod days={days} />
      {all.length > 0 && <StoreTabs stores={storesOf(all)} value={store} onChange={setStore} prefix="opps-best-store" />}
      {all.length > 0 && <FacetTabs counts={facetCounts(inStore)} animal={animal} ptype={ptype} onAnimal={setAnimal} onType={setPtype} prefix="opps-best" />}
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">{t("loading")}</p> : (
        <DataTable columns={bestColumns(isRTL)} rows={ranked} storageKey="opps-best-sellers" exportName="daleel-market-best-sellers"
          rowKey={(s) => `${s.offer_id || s.sku}-${s.store_id}`} initialSort={{ id: "rank", dir: "asc" }} />
      )}
    </div>
  );
}

function Restock() {
  const { t } = useI18n();
  const q = useQuery({ queryKey: ["opps", "restock"], queryFn: async () => (await api.get("/insights/restock-opportunities")).data });
  if (q.isError) return <RequestError id="restock-request" error={q.error} onRetry={() => q.refetch()} />;
  const rows = q.data || [];
  return (
    <div className="glass-card rounded-md p-5" data-testid="opps-restock">
      <p className="text-xs text-[#A1E4DB] mb-3">Products some competitors have run out of while others still sell them — a chance to win their buyers.</p>
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">{t("loading")}</p> : rows.length === 0 ? <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p> : (
        <div className="divide-y divide-white/5">
          {rows.map((r) => (
            <div key={r.sku} className="py-2">
              <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={r.sku} />{r.name_ar}</p>
              <SkuLine sku={r.sku} barcode={r.barcode} />
              <p className="text-[10px] text-red-400 mt-0.5">Out of stock at: {(r.oos_stores || []).join(", ")}</p>
              <p className="text-[10px] text-green-500">In stock at: {(r.in_stock_stores || []).map((s) => s.store).join(", ")}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function OpportunitiesPage() {
  const { t, isRTL } = useI18n();
  const { user } = useAuth();
  const scope = useComparisonScope();
  const [params, setParams] = useSearchParams();
  const [days, setDays] = useState(30);
  const [picked, setPicked] = useState(null);
  const intel = canAccessPage(user, "opportunities");
  const tabs = useMemo(() => [
    { id: "missing", label: isRTL ? "منتجات لا أبيعها" : "Products I don't sell", icon: PackageSearch, show: intel },
    { id: "best-sellers", label: isRTL ? "الأكثر مبيعاً في السوق" : "Market best sellers", icon: TrendingUp, show: intel },
    { id: "restock", label: isRTL ? "فرص إعادة التخزين" : "Restock opportunities", icon: PackageCheck, show: intel },
    { id: "stock-planner", label: isRTL ? "مخطط مخزوني" : "My stock planner", icon: Boxes, show: intel },
  ].filter((x) => x.show), [intel, isRTL]);
  const tab = tabs.some((x) => x.id === params.get("tab")) ? params.get("tab") : tabs[0]?.id;
  const filters = useMemo(() => ({ ...scope.params }), [scope.params]);

  return (
    <div className="p-6 space-y-5" data-testid="opportunities-page">
      <SectionTabs section="market" />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_opportunities")}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "ما يمكنك إضافته أو إعادة تخزينه" : "What you could add or restock"}</p>
        </div>
        {tab !== "restock" && tab !== "stock-planner" && (
          <div className="flex gap-1" data-testid="opps-range">
            {RANGES.map((d) => (
              <Button key={d} size="sm" variant={days === d ? "default" : "outline"} onClick={() => setDays(d)}
                className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#1E988E] text-white" : ""}`} data-testid={`opps-range-${d}`}>{d}D</Button>
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-1 glass-card p-1.5 flex-wrap" data-testid="opps-tabs">
        {tabs.map((x) => (
          <button key={x.id} onClick={() => setParams({ tab: x.id }, { replace: true })} data-testid={`opps-tab-${x.id}`}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === x.id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:text-white hover:bg-white/5"}`}>
            <x.icon className="w-4 h-4" />{x.label}
          </button>
        ))}
      </div>
      {tab === "missing" && (
        <>
          <ComparisonScope scope={scope} prefix="opps" />
          <MissingProducts days={days} includeToday={false} filters={filters} onPickProduct={(row) => setPicked(row.sku || row.canonical_key)} />
          <ProductBreakdown productKey={picked} days={days} includeToday={false} scopeParams={scope.params}
            open={!!picked} onClose={() => setPicked(null)} />
        </>
      )}
      {tab === "best-sellers" && <BestSellers days={days} />}
      {tab === "restock" && <Restock />}
      {tab === "stock-planner" && <StockPlanner />}
    </div>
  );
}
