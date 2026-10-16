/**
 * Opportunities (15 Oct 2026) — what to add or restock, each list once:
 *   Products I don't sell   → Market Share's missing-products list (one count;
 *                              the Price Intel "Product gaps" card counted 5,320
 *                              while Market Share counted 22,044 for the same idea)
 *   Market best sellers      → /insights/top-sellers
 *   Restock opportunities    → /insights/restock-opportunities
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { PackageSearch, TrendingUp, PackageCheck } from "lucide-react";
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

const RANGES = [7, 14, 30, 90];

function BestSellers({ days }) {
  const { t, isRTL } = useI18n();
  const [store, setStore] = useState("all");
  const [animal, setAnimal] = useState("all");
  const [ptype, setPtype] = useState("all");
  const [shown, setShown] = useState(50);
  const q = useQuery({ queryKey: ["opps", "top-sellers", days], queryFn: async () => (await api.get("/insights/top-sellers", { params: { days } })).data });
  const all = useMemo(() => q.data || [], [q.data]);
  const inStore = useMemo(() => all.filter((r) => store === "all" || r.store_id === store), [all, store]);
  const rows = useMemo(() => inStore.filter((r) => facetMatch(r, animal, ptype)), [inStore, animal, ptype]);
  useEffect(() => { setShown(50); }, [store, animal, ptype, days]);
  if (q.isError) return <RequestError id="best-sellers-request" error={q.error} onRetry={() => q.refetch()} />;
  return (
    <div className="glass-card rounded-md p-5 space-y-3" data-testid="opps-best-sellers">
      <p className="text-xs text-[#A1E4DB]">
        {isRTL ? `المنتجات الأكثر مبيعاً في المتاجر المتتبعة خلال آخر ${days} يوماً (لكل متجر على حدة). المبيعات تقديرية من حركة المخزون أو عدّاد المبيعات.`
          : `Products with the most observed sales in tracked stores over the last ${days} days, per store. Sales are estimated from stock movement or the public sold counter.`}
      </p>
      {all.length > 0 && <StoreTabs stores={storesOf(all)} value={store} onChange={setStore} prefix="opps-best-store" />}
      {all.length > 0 && <FacetTabs counts={facetCounts(inStore)} animal={animal} ptype={ptype} onAnimal={setAnimal} onType={setPtype} prefix="opps-best" />}
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">{t("loading")}</p> : rows.length === 0 ? <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p> : (
        <div className="divide-y divide-white/5">
          {rows.slice(0, shown).map((s, i) => (
            <div key={`${s.offer_id || s.sku}-${s.store_id || i}`} className="flex items-center gap-3 py-2" data-testid={`opps-best-${i}`}>
              <span className={`w-6 h-6 shrink-0 rounded text-[10px] font-bold flex items-center justify-center ${i < 3 ? "bg-[#1E988E] text-[#090E1C]" : "bg-white/5 text-[#A1E4DB]"}`}>{i + 1}</span>
              <div className="w-10 h-10 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
                {s.image_url ? <img src={s.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : null}
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={s.sku} />{s.name_ar || s.name_en}</p>
                <SkuLine sku={s.sku} barcode={s.barcode} />
                {s.store_name && <p className="text-[10px] text-[#A1E4DB] inline-flex items-center gap-1"><StoreLogo storeId={s.store_id} name={s.store_name} size={12} />{s.store_name}{s.avg_price != null && ` · ${s.avg_price} SAR`}</p>}
              </div>
              <div className="text-end shrink-0">
                <p className="text-xs font-bold text-white">{(s.units_sold ?? s.qty_sold_est ?? 0).toLocaleString()} {isRTL ? "وحدة" : "units"}</p>
                <p className="text-[10px] text-[#A1E4DB]">{(s.revenue_est ?? 0).toLocaleString()} SAR</p>
              </div>
            </div>
          ))}
        </div>
      )}
      {rows.length > shown && (
        <button onClick={() => setShown((n) => n + 50)} className="text-xs text-[#6AC1B5] hover:text-white" data-testid="opps-best-more">
          {isRTL ? `عرض المزيد (${rows.length - shown})` : `Show more (${rows.length - shown})`}
        </button>
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
  const intel = ["insights", "price_intel"].some((k) => canAccessPage(user, k));
  const tabs = useMemo(() => [
    { id: "missing", label: isRTL ? "منتجات لا أبيعها" : "Products I don't sell", icon: PackageSearch, show: canAccessPage(user, "market_share") },
    { id: "best-sellers", label: isRTL ? "الأكثر مبيعاً في السوق" : "Market best sellers", icon: TrendingUp, show: intel },
    { id: "restock", label: isRTL ? "فرص إعادة التخزين" : "Restock opportunities", icon: PackageCheck, show: intel },
  ].filter((x) => x.show), [user, intel, isRTL]);
  const tab = tabs.some((x) => x.id === params.get("tab")) ? params.get("tab") : tabs[0]?.id;
  const filters = useMemo(() => ({ ...scope.params }), [scope.params]);

  return (
    <div className="p-6 space-y-5" data-testid="opportunities-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_opportunities")}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "ما يمكنك إضافته أو إعادة تخزينه" : "What you could add or restock"}</p>
        </div>
        {tab !== "restock" && (
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
    </div>
  );
}
