import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { AlertTriangle, Award, ShoppingCart, AlertCircle, PackageSearch } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  PriceIntelKpiRow,
  ConfidenceDistribution,
  ConfidenceGuidePanel,
  MarketPositionWidget,
} from "@/components/priceIntel/PriceIntelHeader";
import { PriceIntelTabContent } from "@/components/priceIntel/PriceIntelTabs";
import { PriceIntelDetailSheet } from "@/components/priceIntel/PriceIntelDetailSheet";
import DataFreshnessBanner from "@/components/DataFreshnessBanner";

export default function PriceIntelPage() {
  const { isRTL } = useI18n();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedSku, setSelectedSku] = useState(null);
  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState("action");
  // iter38 — live Market Strength ranking (replaces the static April
  // MySkuWatch leaderboard in the widget)
  const [ranking, setRanking] = useState(null);
  const [rankingComputedAt, setRankingComputedAt] = useState(null);
  const [catalogGaps, setCatalogGaps] = useState([]);
  const [showGuide, setShowGuide] = useState(false);
  const [cacheComputedAt, setCacheComputedAt] = useState(null);
  // iter32 — live sources for the "Your Store Performance" card (replaces the
  // frozen market_intelligence_baseline literals from the April import).
  const [myKpis, setMyKpis] = useState(null);
  const [summary14, setSummary14] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [r, rk, gaps, mine, sum] = await Promise.all([
        api.get("/price-intel/dashboard"),
        api.get("/price-intel/store-ranking").catch(() => ({ data: null })),
        api.get("/baseline/catalog-gaps").catch(() => ({ data: [] })),
        // Both cached server-side (14 is a standard dashboard-cache window);
        // limit=1 keeps the my-products payload to KPIs + one row.
        api.get("/my-products", { params: { days: 14, limit: 1 } }).catch(() => ({ data: null })),
        api.get("/insights/summary", { params: { days: 14 } }).catch(() => ({ data: null })),
      ]);
      setData(r.data);
      setRanking(rk.data);
      setRankingComputedAt(rk.headers?.["x-cache-computed-at"] || null);
      setCatalogGaps(gaps.data || []);
      setMyKpis(mine.data?.kpis || null);
      setSummary14(sum.data || null);
      // iter26 — dashboard-cache freshness from the X-Cache-Computed-At header
      setCacheComputedAt(r.headers?.["x-cache-computed-at"] || null);
    } catch {
      toast.error("Failed to load price intelligence");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const openDetail = async (sku) => {
    setSelectedSku(sku);
    try {
      const r = await api.get(`/price-intel/product/${sku}`);
      setDetail(r.data);
    } catch {
      toast.error("Failed to load product detail");
    }
  };

  const closeDetail = () => { setSelectedSku(null); setDetail(null); };

  const confirmMatch = async (m) => {
    try {
      await api.post("/price-intel/confirm-match", { my_sku: m.my_sku, competitor_sku: m.competitor_sku, competitor_store_id: m.competitor_store_id });
      toast.success("Match confirmed (confidence → 100)");
      if (selectedSku) openDetail(selectedSku);
      fetchData();
    } catch { toast.error("Failed"); }
  };

  const rejectMatch = async (m) => {
    try {
      await api.post("/price-intel/reject-match", { my_sku: m.my_sku, competitor_sku: m.competitor_sku, competitor_store_id: m.competitor_store_id });
      toast.success("Match rejected and blacklisted");
      if (selectedSku) openDetail(selectedSku);
      fetchData();
    } catch { toast.error("Failed"); }
  };

  if (loading) return <div className="flex items-center justify-center h-96"><div className="w-8 h-8 rounded-full border-2 border-[#1E988E] border-t-transparent animate-spin" /></div>;
  if (!data) return <div className="p-6 text-[#A1E4DB]">No data available. Import products first.</div>;

  const tabs = [
    { id: "action", label: isRTL ? "إجراء مطلوب" : "Action Required", count: data.action_required.length, icon: AlertTriangle },
    { id: "advantage", label: isRTL ? "مزاياي" : "My Advantages", count: data.my_advantages.length, icon: Award },
    { id: "full", label: isRTL ? "المقارنة الكاملة" : "Full Comparison", count: data.full_table.length, icon: ShoppingCart },
    { id: "unverified", label: isRTL ? "غير مؤكد" : "Unverified", count: (data.unverified || []).length, icon: AlertCircle },
    { id: "gaps", label: isRTL ? "فجوات الكتالوج" : "Catalog Gaps", count: catalogGaps.length, icon: PackageSearch },
  ];

  return (
    <div className="p-6 space-y-5" data-testid="price-intel-page">
      <div>
        <h1 className="text-2xl font-semibold text-white">{isRTL ? "استخبارات الأسعار" : "Price Intelligence"}</h1>
        <p className="text-sm text-[#A1E4DB]">{isRTL ? "مقارنة أسعار منتجاتك مع المنافسين" : "Compare your prices against competitors"}</p>
        {cacheComputedAt && (
          <p className="text-[11px] text-[#6AC1B5] mt-0.5 font-mono" data-testid="price-intel-cache-freshness">
            {isRTL ? "المؤشرات محدثة حتى" : "Metrics as of"}{" "}
            {new Date(cacheComputedAt).toLocaleString(isRTL ? "ar-SA" : "en-GB", { dateStyle: "medium", timeStyle: "short" })}
          </p>
        )}
      </div>

      <DataFreshnessBanner />

      <PriceIntelKpiRow summary={data.summary} />

      <ConfidenceDistribution
        distribution={data.confidence_distribution}
        isRTL={isRTL}
        showGuide={showGuide}
        onToggleGuide={() => setShowGuide(!showGuide)}
      />

      {showGuide && <ConfidenceGuidePanel isRTL={isRTL} />}

      <MarketPositionWidget ranking={ranking} rankingComputedAt={rankingComputedAt} myKpis={myKpis} summary={summary14} isRTL={isRTL} />

      <div className="flex gap-1 glass-card p-1.5">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === t.id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:text-white hover:bg-white/5"}`}
            data-testid={`tab-${t.id}`}>
            <t.icon className="w-4 h-4" />{t.label} <Badge className="text-[10px] bg-white/10 border-0 text-[#A1E4DB]">{t.count}</Badge>
          </button>
        ))}
      </div>

      <PriceIntelTabContent
        tab={tab}
        data={data}
        catalogGaps={catalogGaps}
        isRTL={isRTL}
        onOpen={openDetail}
      />

      <PriceIntelDetailSheet
        selectedSku={selectedSku}
        detail={detail}
        onClose={closeDetail}
        onConfirm={confirmMatch}
        onReject={rejectMatch}
      />
    </div>
  );
}
