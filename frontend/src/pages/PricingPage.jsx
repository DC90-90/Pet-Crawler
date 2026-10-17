/**
 * Pricing (15 Oct 2026) — every price question in one place, each answered once:
 *   Overpriced          → the Scanner (gap to the cheapest seller, price-gap exposure)
 *   My advantages       → cheapest verified seller, or a competitor out of stock
 *   Full comparison     → every matched product, plus match confidence
 *   Price wars          → products where sellers' prices are furthest apart
 *   Discounts           → competitors' current discounts
 * Replaces the Price & Market Intel page's price sections, the Scanner page and
 * the Discounts page, which showed the same overpriced list in three places.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { AlertTriangle, Award, ShoppingCart, Swords, Percent, AlertCircle, Lightbulb, CalendarDays } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth, canAccessPage } from "@/App";
import { useReleaseActions } from "@/lib/releaseActions";
import { Badge } from "@/components/ui/badge";
import { RequestError } from "@/components/RequestError";
import { ComparisonScope, useComparisonScope } from "@/components/ComparisonScope";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import { CardPeriod } from "@/components/CardPeriod";
import { PriceIntelTabContent } from "@/components/priceIntel/PriceIntelTabs";
import { PriceIntelDetailSheet } from "@/components/priceIntel/PriceIntelDetailSheet";
import ScannerPage from "@/pages/ScannerPage";
import DiscountsPage from "@/pages/DiscountsPage";
import PriceRecommendations from "@/components/PriceRecommendations";
import PromotionsCalendar from "@/components/PromotionsCalendar";

const INTEL_KEYS = ["insights", "price_intel"];
const WAR_MAX_PCT = 100;

function usePriceDashboard(scope) {
  return useQuery({
    queryKey: ["pricing", "pi-dashboard", scope.params],
    queryFn: async () => (await api.get("/price-intel/dashboard", { params: scope.params })).data,
    retry: false,
  });
}

function ComparisonPanel({ view }) {
  const { isRTL } = useI18n();
  const { canEdit } = useReleaseActions();
  const scope = useComparisonScope();
  const q = usePriceDashboard(scope);
  const [selectedSku, setSelectedSku] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailError, setDetailError] = useState(false);
  const [sub, setSub] = useState(view);
  const detailRequest = useRef(0);
  useEffect(() => { setSub(view); }, [view]);
  useEffect(() => { detailRequest.current += 1; setSelectedSku(null); setDetail(null); setDetailError(false); }, [scope.params]);

  const openDetail = async (sku) => {
    const request = ++detailRequest.current;
    setSelectedSku(sku); setDetail(null); setDetailError(false);
    try {
      const r = await api.get(`/price-intel/product/${encodeURIComponent(sku)}`, { params: scope.params, timeout: 45000 });
      if (request === detailRequest.current) setDetail(r.data);
    } catch { if (request === detailRequest.current) setDetailError(true); }
  };
  const closeDetail = () => { detailRequest.current += 1; setSelectedSku(null); setDetail(null); setDetailError(false); };
  const decide = (path, message) => async (m) => {
    if (!canEdit) return;
    try {
      await api.post(path, { my_sku: m.my_sku, competitor_sku: m.competitor_sku, competitor_store_id: m.competitor_store_id, competitor_offer_id: m.competitor_offer_id });
      toast.success(message);
      if (selectedSku) openDetail(selectedSku);
      q.refetch();
    } catch { toast.error("Failed"); }
  };

  if (q.isError) return <RequestError id="pricing-request" error={q.error} onRetry={() => q.refetch()} />;
  const data = q.data;
  const unverified = (data?.unverified || []).length;
  return (
    <div className="space-y-4">
      <ComparisonScope scope={scope} prefix="pricing" />
      {!data ? (
        <p className="text-sm text-[#A1E4DB]" data-testid="pricing-loading">{isRTL ? "جارٍ التحميل…" : "Loading…"}</p>
      ) : (
        <>
          {view === "full" && (
            <div className="space-y-3">
              {/* One plain line instead of the confidence chart, whose data was
                  empty ("0 total matches" next to 980 matched products). */}
              <p className="text-xs text-[#A1E4DB]" data-testid="pricing-match-summary">
                {isRTL
                  ? `${(data.summary?.matched_products ?? 0).toLocaleString()} من ${(data.summary?.total_products ?? 0).toLocaleString()} منتجاً مطابَقاً مع منافس بالباركود`
                  : `${(data.summary?.matched_products ?? 0).toLocaleString()} of ${(data.summary?.total_products ?? 0).toLocaleString()} products are matched to a competitor by barcode`}
              </p>
              {unverified > 0 && (
                <div className="flex gap-1">
                  {[["full", isRTL ? "كل المنتجات" : "All matched products", ShoppingCart],
                    ["unverified", isRTL ? "تحتاج مراجعة" : "Needs review", AlertCircle]].map(([id, label, Icon]) => (
                    <button key={id} onClick={() => setSub(id)} data-testid={`pricing-sub-${id}`}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs ${sub === id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:bg-white/5"}`}>
                      <Icon className="w-3.5 h-3.5" />{label}{id === "unverified" && <Badge className="text-[10px] bg-white/10 border-0 text-[#A1E4DB]">{unverified}</Badge>}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
          <PriceIntelTabContent tab={view === "full" ? sub : "advantage"} data={data} catalogGaps={[]} isRTL={isRTL} onOpen={openDetail} />
        </>
      )}
      <PriceIntelDetailSheet readOnly={!canEdit} error={detailError} onRetry={() => openDetail(selectedSku)}
        selectedSku={selectedSku} detail={detail} onClose={closeDetail}
        onConfirm={decide("/price-intel/confirm-match", "Match confirmed (confidence → 100)")}
        onReject={decide("/price-intel/reject-match", "Match rejected and blacklisted")} />
    </div>
  );
}

function PriceWars() {
  const { t } = useI18n();
  const q = useQuery({ queryKey: ["pricing", "price-wars"], queryFn: async () => (await api.get("/insights/price-wars")).data });
  if (q.isError) return <RequestError id="price-wars-request" error={q.error} onRetry={() => q.refetch()} />;
  const all = q.data || [];
  const wars = all.filter((w) => (w.spread_pct ?? 0) <= WAR_MAX_PCT).sort((a, b) => (b.spread_pct ?? 0) - (a.spread_pct ?? 0)).slice(0, 100);
  const packLike = all.length - all.filter((w) => (w.spread_pct ?? 0) <= WAR_MAX_PCT).length;
  return (
    <div className="glass-card rounded-md p-5" data-testid="pricing-price-wars">
      <p className="text-xs text-[#A1E4DB] mb-1">Products where the same item's prices differ the most between sellers — largest gaps first.</p>
      {packLike > 0 && <p className="text-[11px] text-[#F59E0B] mb-1" data-testid="price-wars-pack-note">{packLike} products with gaps above {WAR_MAX_PCT}% are left out: such gaps almost always mean a different pack size, not a price war.</p>}
      <CardPeriod window="current" testId="price-wars-period" />
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">{t("loading")}</p> : wars.length === 0 ? (
        <p className="text-xs text-[#A1E4DB]">{t("no_data")}</p>
      ) : (
        <div className="divide-y divide-white/5">
          {wars.map((w) => (
            <div key={w.sku} className="py-2 flex items-center justify-between gap-3">
              <div className="min-w-0">
                <p className="text-xs font-medium text-white truncate inline-flex items-center gap-1.5"><MineBadge sku={w.sku} />{w.name_ar}</p>
                <SkuLine sku={w.sku} barcode={w.barcode} />
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge variant="outline" className="text-[10px] border-[#EF4444]/30 text-[#EF4444] bg-[#EF4444]/10">{w.spread_sar} SAR spread</Badge>
                <span className="text-[10px] text-[#A1E4DB]">{w.spread_pct}%</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function PricingPage() {
  const { t, isRTL } = useI18n();
  const { user } = useAuth();
  const [params, setParams] = useSearchParams();
  const intel = INTEL_KEYS.some((k) => canAccessPage(user, k));
  const tabs = useMemo(() => [
    { id: "recommendations", label: isRTL ? "توصيات الأسعار" : "Recommendations", icon: Lightbulb, show: intel },
    { id: "overpriced", label: isRTL ? "أسعاري الأعلى" : "Overpriced", icon: AlertTriangle, show: intel || canAccessPage(user, "scanner") },
    { id: "cheapest", label: isRTL ? "مزاياي" : "My advantages", icon: Award, show: intel },
    { id: "full", label: isRTL ? "المقارنة الكاملة" : "Full comparison", icon: ShoppingCart, show: intel },
    { id: "price-wars", label: isRTL ? "حروب الأسعار" : "Price wars", icon: Swords, show: intel },
    { id: "discounts", label: isRTL ? "تخفيضات المنافسين" : "Competitor discounts", icon: Percent, show: canAccessPage(user, "discounts") },
    { id: "promotions", label: isRTL ? "تقويم العروض" : "Promotions calendar", icon: CalendarDays, show: canAccessPage(user, "discounts") },
  ].filter((x) => x.show), [user, intel, isRTL]);
  const tab = tabs.some((x) => x.id === params.get("tab")) ? params.get("tab") : tabs[0]?.id;

  return (
    <div className="p-6 space-y-5" data-testid="pricing-page">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_pricing")}</h1>
        <p className="text-sm text-[#A1E4DB] mt-0.5">
          {isRTL ? "أسعارك مقابل المنافسين على نفس المنتج" : "Your prices against competitors selling the same product"}
        </p>
      </div>
      <div className="flex gap-1 glass-card p-1.5 flex-wrap" data-testid="pricing-tabs">
        {tabs.map((x) => (
          <button key={x.id} onClick={() => setParams({ tab: x.id }, { replace: true })} data-testid={`pricing-tab-${x.id}`}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === x.id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:text-white hover:bg-white/5"}`}>
            <x.icon className="w-4 h-4" />{x.label}
          </button>
        ))}
      </div>
      {tab === "recommendations" && <PriceRecommendations />}
      {tab === "overpriced" && <ScannerPage embedded />}
      {(tab === "cheapest" || tab === "full") && <ComparisonPanel view={tab === "full" ? "full" : "advantage"} />}
      {tab === "price-wars" && <PriceWars />}
      {tab === "discounts" && <DiscountsPage embedded />}
      {tab === "promotions" && <PromotionsCalendar />}
    </div>
  );
}
