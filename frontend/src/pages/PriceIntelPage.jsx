import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { AlertTriangle, TrendingDown, TrendingUp, Award, ShoppingCart, CheckCircle2, XCircle, AlertCircle, ChevronRight, Shield, Trophy, PackageSearch, Info, Lock, Fingerprint, Type, FileText } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

const CONFIDENCE_LEVELS = [
  { min: 100, label: "Confirmed", labelAr: "مؤكد يدوياً", icon: CheckCircle2, color: "#10B981", bg: "bg-[#10B981]/15 text-[#10B981]", desc: "Manually verified by you — 100% reliable", descAr: "تم التحقق يدوياً — موثوق 100%" },
  { min: 99, label: "Barcode Match", labelAr: "مطابقة باركود", icon: Fingerprint, color: "#10B981", bg: "bg-[#10B981]/15 text-[#10B981]", desc: "Exact barcode/EAN match (8-14 digits) — highest automated confidence", descAr: "مطابقة باركود/EAN بالضبط — أعلى ثقة تلقائية" },
  { min: 95, label: "SKU Match", labelAr: "مطابقة SKU", icon: Lock, color: "#00D4B4", bg: "bg-[#00D4B4]/15 text-[#00D4B4]", desc: "Exact SKU identifier match between stores", descAr: "مطابقة معرف SKU بالضبط بين المتاجر" },
  { min: 85, label: "Strong Name", labelAr: "اسم قوي", icon: Type, color: "#00D4B4", bg: "bg-[#00D4B4]/15 text-[#00D4B4]", desc: "5+ name tokens match with weight/pack verification", descAr: "5+ كلمات مطابقة مع تحقق من الوزن والتعبئة" },
  { min: 80, label: "Good Name", labelAr: "اسم جيد", icon: Type, color: "#F59E0B", bg: "bg-[#F59E0B]/15 text-[#F59E0B]", desc: "4 name tokens match — review recommended", descAr: "4 كلمات مطابقة — يُنصح بالمراجعة" },
  { min: 75, label: "Baseline", labelAr: "بيانات أساسية", icon: FileText, color: "#F59E0B", bg: "bg-[#F59E0B]/15 text-[#F59E0B]", desc: "MySKUwatch estimated data — expires May 17", descAr: "بيانات MySKUwatch تقديرية — تنتهي 17 مايو" },
  { min: 70, label: "Weak Name", labelAr: "اسم ضعيف", icon: AlertCircle, color: "#EF4444", bg: "bg-[#EF4444]/15 text-[#EF4444]", desc: "3 tokens match only — likely needs manual review", descAr: "3 كلمات فقط — يحتاج مراجعة يدوية غالباً" },
];

function getConfLevel(confidence, method) {
  if (confidence === 100) return CONFIDENCE_LEVELS[0];
  for (const lvl of CONFIDENCE_LEVELS) {
    if (confidence >= lvl.min) return lvl;
  }
  return CONFIDENCE_LEVELS[CONFIDENCE_LEVELS.length - 1];
}

function ConfidenceBadge({ confidence, method }) {
  const lvl = getConfLevel(confidence, method);
  const Icon = lvl.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full ${lvl.bg}`} title={lvl.desc}>
      <Icon className="w-3 h-3" />
      {confidence}% {lvl.label}
    </span>
  );
}

function FlagBadges({ flags }) {
  if (!flags || flags.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {flags.map((f) => (
        <span key={f} className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${f === "SUSPICIOUS_PRICE" ? "bg-[#EF4444]/15 text-[#EF4444]" : f === "SIZE_MISMATCH" ? "bg-[#F59E0B]/15 text-[#F59E0B]" : "bg-white/10 text-[#9CA3AF]"}`}>{f.replace(/_/g, " ")}</span>
      ))}
    </div>
  );
}

export default function PriceIntelPage() {
  const { isRTL } = useI18n();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedSku, setSelectedSku] = useState(null);
  const [detail, setDetail] = useState(null);
  const [tab, setTab] = useState("action");
  const [leaderboard, setLeaderboard] = useState(null);
  const [catalogGaps, setCatalogGaps] = useState([]);
  const [showGuide, setShowGuide] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [r, lb, gaps] = await Promise.all([
        api.get("/price-intel/dashboard"),
        api.get("/baseline/leaderboard").catch(() => ({ data: null })),
        api.get("/baseline/catalog-gaps").catch(() => ({ data: [] })),
      ]);
      setData(r.data);
      setLeaderboard(lb.data);
      setCatalogGaps(gaps.data || []);
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

  if (loading) return <div className="flex items-center justify-center h-96"><div className="w-8 h-8 rounded-full border-2 border-[#00D4B4] border-t-transparent animate-spin" /></div>;
  if (!data) return <div className="p-6 text-[#9CA3AF]">No data available. Import products first.</div>;

  const s = data.summary;
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
        <p className="text-sm text-[#9CA3AF]">{isRTL ? "مقارنة أسعار منتجاتك مع المنافسين" : "Compare your prices against competitors"}</p>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: "My Products", val: s.total_products, color: "#00D4B4" },
          { label: "Matched", val: s.matched_products, color: "#10B981" },
          { label: "Overpriced (RED)", val: s.overpriced_red, color: "#EF4444" },
          { label: "Overpriced (YELLOW)", val: s.overpriced_yellow, color: "#F59E0B" },
          { label: "I'm Cheapest", val: s.cheapest_count, color: "#10B981" },
          { label: "OOS Opportunity", val: s.oos_opportunities, color: "#00D4B4" },
        ].map((k) => (
          <div key={k.label} className="kpi-card">
            <p className="text-[9px] uppercase tracking-wider text-[#9CA3AF]">{k.label}</p>
            <p className="text-xl font-bold metric-number" style={{ color: k.color }}>{k.val}</p>
          </div>
        ))}
      </div>

      {/* Confidence Distribution Bar + Guide Toggle */}
      {data.confidence_distribution && (() => {
        const cd = data.confidence_distribution;
        const total = Object.values(cd).reduce((a, b) => a + b, 0) || 1;
        const segments = [
          { key: "confirmed_100", label: "Confirmed", count: cd.confirmed_100, color: "#10B981" },
          { key: "barcode_99", label: "Barcode", count: cd.barcode_99, color: "#059669" },
          { key: "sku_95", label: "SKU", count: cd.sku_95, color: "#00D4B4" },
          { key: "name_85", label: "Name 5+", count: cd.name_85, color: "#0EA5E9" },
          { key: "name_80", label: "Name 4", count: cd.name_80, color: "#F59E0B" },
          { key: "baseline_80", label: "Baseline", count: cd.baseline_80, color: "#D97706" },
          { key: "name_70", label: "Name 3", count: cd.name_70, color: "#EF4444" },
        ].filter(s => s.count > 0);
        return (
          <div className="glass-card p-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Shield className="w-4 h-4 text-[#00D4B4]" />
                <h3 className="text-sm font-semibold text-white">{isRTL ? "توزيع الثقة" : "Match Confidence Distribution"}</h3>
                <span className="text-[10px] text-[#9CA3AF]">{total.toLocaleString()} total matches</span>
              </div>
              <button onClick={() => setShowGuide(!showGuide)} className="flex items-center gap-1 text-[10px] text-[#00D4B4] hover:text-[#00E5C3] transition-colors" data-testid="toggle-guide">
                <Info className="w-3.5 h-3.5" />{showGuide ? "Hide" : "Show"} Confidence Guide
              </button>
            </div>
            {/* Stacked bar */}
            <div className="flex h-4 rounded-full overflow-hidden mb-2">
              {segments.map(seg => (
                <div key={seg.key} style={{ width: `${(seg.count / total) * 100}%`, backgroundColor: seg.color }} className="transition-all duration-500" title={`${seg.label}: ${seg.count}`} />
              ))}
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {segments.map(seg => (
                <div key={seg.key} className="flex items-center gap-1.5 text-[10px]">
                  <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.color }} />
                  <span className="text-[#9CA3AF]">{seg.label}</span>
                  <span className="text-white font-semibold metric-number">{seg.count}</span>
                  <span className="text-[#9CA3AF]">({Math.round((seg.count / total) * 100)}%)</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Confidence Guide Panel */}
      {showGuide && (
        <div className="glass-card p-5 border border-[#00D4B4]/20 animate-fadeIn" data-testid="confidence-guide">
          <div className="flex items-center gap-2 mb-4">
            <Shield className="w-5 h-5 text-[#00D4B4]" />
            <h3 className="text-base font-semibold text-white">{isRTL ? "دليل مستويات الثقة" : "Data Confidence Guide"}</h3>
          </div>
          <div className="space-y-2">
            {CONFIDENCE_LEVELS.map((lvl) => {
              const Icon = lvl.icon;
              return (
                <div key={lvl.min} className="flex items-start gap-3 py-2.5 px-3 rounded-xl hover:bg-white/3 transition-colors">
                  <div className={`flex items-center justify-center w-10 h-10 rounded-xl ${lvl.bg}`}><Icon className="w-5 h-5" /></div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-white">{lvl.min}%</span>
                      <span className="text-sm font-medium" style={{ color: lvl.color }}>{isRTL ? lvl.labelAr : lvl.label}</span>
                    </div>
                    <p className="text-[11px] text-[#9CA3AF] mt-0.5">{isRTL ? lvl.descAr : lvl.desc}</p>
                  </div>
                  <div className="w-24 h-2 rounded-full bg-white/5 mt-2 overflow-hidden">
                    <div className="h-full rounded-full transition-all" style={{ width: `${lvl.min}%`, backgroundColor: lvl.color }} />
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-4 pt-3 border-t border-white/5 text-[10px] text-[#9CA3AF] space-y-1">
            <p><strong className="text-white">Rule:</strong> {isRTL ? "المقارنات بثقة أقل من 75% تظهر فقط في تبويب 'غير مؤكد' للمراجعة اليدوية" : "Comparisons below 75% confidence appear ONLY in the 'Unverified' tab for manual review"}</p>
            <p><strong className="text-white">Rule:</strong> {isRTL ? "الفرق بالسعر أكثر من 150% يتم رفضه تلقائياً لتطابقات الأسماء" : "Price differences >150% are auto-rejected for name-based matches"}</p>
            <p><strong className="text-white">Rule:</strong> {isRTL ? "فرق الوزن أكثر من 10% = رفض المطابقة" : "Weight difference >10% = match rejected entirely"}</p>
            <p><strong className="text-white">Rule:</strong> {isRTL ? "المنتجات المتعددة (باك) لا تطابق مع المنتجات المفردة أبداً" : "Multi-pack products NEVER match single units"}</p>
          </div>
        </div>
      )}

      {/* Market Position Widget */}
      {leaderboard && leaderboard.my_store_baseline && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="glass-card p-5">
            <div className="flex items-center gap-2 mb-3">
              <Trophy className="w-5 h-5 text-[#F59E0B]" />
              <h3 className="text-sm font-semibold text-white">{isRTL ? "ترتيبك في السوق" : "Market Position"}</h3>
              <Badge className="text-[8px] bg-[#F59E0B]/10 text-[#F59E0B] border-0 ms-auto">Baseline data (expires May 17)</Badge>
            </div>
            <div className="flex items-end gap-1 mb-3">
              <span className="text-4xl font-bold text-[#F59E0B] metric-number">#{leaderboard.my_store_baseline.market_rank}</span>
              <span className="text-[#9CA3AF] text-sm mb-1">of {leaderboard.my_store_baseline.market_total_stores} stores</span>
            </div>
            <div className="space-y-1.5">
              {leaderboard.leaderboard?.slice(0, 7).map((e) => (
                <div key={e.rank} className={`flex items-center gap-2 text-xs py-1 px-2 rounded-lg ${e.is_my_store ? "bg-[#00D4B4]/10 border border-[#00D4B4]/20" : ""}`}>
                  <span className="text-[#9CA3AF] w-5 text-right">#{e.rank}</span>
                  <span className={`flex-1 ${e.is_my_store ? "text-[#00D4B4] font-semibold" : "text-white"}`}>{e.store_domain}</span>
                  <span className="text-[#9CA3AF]">{e.relative_size}</span>
                </div>
              ))}
              {leaderboard.leaderboard?.length > 7 && (
                <div className="text-[10px] text-[#9CA3AF] text-center pt-1">
                  ... + {leaderboard.leaderboard.length - 7} more stores (you are #{leaderboard.my_store_baseline.market_rank})
                </div>
              )}
            </div>
          </div>
          <div className="glass-card p-5">
            <h3 className="text-sm font-semibold text-white mb-3">{isRTL ? "أداء متجرك" : "Your Store Performance"}</h3>
            <div className="grid grid-cols-2 gap-4">
              <div><p className="text-[9px] uppercase text-[#9CA3AF] tracking-wider">Est. Revenue (14d)</p><p className="text-xl font-bold text-[#00D4B4] metric-number">{leaderboard.my_store_baseline.est_revenue_sar?.toLocaleString()} SAR</p></div>
              <div><p className="text-[9px] uppercase text-[#9CA3AF] tracking-wider">Est. Units Sold</p><p className="text-xl font-bold text-white metric-number">{leaderboard.my_store_baseline.est_units_sold?.toLocaleString()}</p></div>
              <div><p className="text-[9px] uppercase text-[#9CA3AF] tracking-wider">Active Products</p><p className="text-xl font-bold text-white metric-number">{leaderboard.my_store_baseline.total_products?.toLocaleString()}</p></div>
              <div><p className="text-[9px] uppercase text-[#9CA3AF] tracking-wider">Price Spread</p><p className="text-xl font-bold text-[#F59E0B] metric-number">{leaderboard.my_store_baseline.median_price_spread_pct}%</p></div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Bar */}
      <div className="flex gap-1 glass-card p-1.5">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all ${tab === t.id ? "bg-[#00D4B4] text-[#0A0F1E]" : "text-[#9CA3AF] hover:text-white hover:bg-white/5"}`}
            data-testid={`tab-${t.id}`}>
            <t.icon className="w-4 h-4" />{t.label} <Badge className="text-[10px] bg-white/10 border-0 text-[#9CA3AF]">{t.count}</Badge>
          </button>
        ))}
      </div>

      {/* Section A: Action Required */}
      {tab === "action" && (
        <div className="glass-card overflow-hidden">
          <Table className="dense-table">
            <TableHeader><TableRow>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Product</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">My Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Cheapest</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Diff%</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Confidence</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Severity</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.action_required.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center py-12 text-[#9CA3AF]">No overpriced products found</TableCell></TableRow>
              ) : data.action_required.slice(0, 50).map((r) => (
                <TableRow key={r.my_sku} className="cursor-pointer" onClick={() => openDetail(r.my_sku)}>
                  <TableCell><p className="text-sm text-white font-medium truncate max-w-[250px]">{r.my_name_en || r.my_name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{r.my_sku}</p></TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
                  <TableCell><span className="text-sm text-[#9CA3AF]">{r.cheapest_competitor}</span><br/><span className="text-sm font-semibold text-[#10B981] metric-number">{r.cheapest_price} SAR</span></TableCell>
                  <TableCell><span className={`text-sm font-bold ${r.diff_pct > 15 ? "text-[#EF4444]" : "text-[#F59E0B]"}`}>+{r.diff_pct}%</span></TableCell>
                  <TableCell><ConfidenceBadge confidence={r.confidence} method={r.match_method} /></TableCell>
                  <TableCell><span className={`inline-block w-3 h-3 rounded-full ${r.severity === "red" ? "bg-[#EF4444]" : "bg-[#F59E0B]"}`} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Section B: My Advantages */}
      {tab === "advantage" && (
        <div className="glass-card overflow-hidden">
          <Table className="dense-table">
            <TableHeader><TableRow>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Product</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">My Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Advantage</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Detail</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Confidence</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.my_advantages.length === 0 ? (
                <TableRow><TableCell colSpan={5} className="text-center py-12 text-[#9CA3AF]">No advantages found yet</TableCell></TableRow>
              ) : data.my_advantages.slice(0, 50).map((r, i) => (
                <TableRow key={`${r.my_sku}-${r.advantage}-${i}`} className="cursor-pointer" onClick={() => openDetail(r.my_sku)}>
                  <TableCell><p className="text-sm text-white font-medium truncate max-w-[250px]">{r.my_name_en || r.my_name_ar}</p></TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
                  <TableCell>
                    {r.advantage === "cheapest" ? <Badge className="bg-[#10B981]/15 text-[#10B981] border-0 text-xs">I'm Cheapest</Badge> : <Badge className="bg-[#00D4B4]/15 text-[#00D4B4] border-0 text-xs">Competitor OOS</Badge>}
                  </TableCell>
                  <TableCell>{r.advantage === "cheapest" ? <span className="text-sm text-[#10B981]">Saving {r.saving_sar} SAR</span> : <span className="text-sm text-[#00D4B4]">My stock: {r.my_stock}</span>}</TableCell>
                  <TableCell><ConfidenceBadge confidence={r.confidence} method={r.match_method} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Section C: Full Comparison Table */}
      {tab === "full" && (
        <div className="glass-card overflow-hidden">
          <Table className="dense-table">
            <TableHeader><TableRow>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">My Product</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">My Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Cheapest Competitor</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Diff%</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Sellers</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Confidence</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Flags</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {data.full_table.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="text-center py-12 text-[#9CA3AF]">No matches found. Import products and run matching first.</TableCell></TableRow>
              ) : data.full_table.slice(0, 100).map((r) => (
                <TableRow key={r.my_sku} className="cursor-pointer" onClick={() => openDetail(r.my_sku)}>
                  <TableCell><p className="text-sm text-white font-medium truncate max-w-[200px]">{r.my_name_en || r.my_name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{r.my_sku}</p></TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
                  <TableCell><span className="text-xs text-[#9CA3AF]">{r.cheapest_competitor}</span></TableCell>
                  <TableCell><span className="text-sm font-semibold metric-number" style={{ color: r.diff_pct > 0 ? "#EF4444" : "#10B981" }}>{r.cheapest_price} SAR</span></TableCell>
                  <TableCell><span className={`text-sm font-bold ${r.diff_pct > 5 ? "text-[#EF4444]" : r.diff_pct < -5 ? "text-[#10B981]" : "text-[#9CA3AF]"}`}>{r.diff_pct > 0 ? "+" : ""}{r.diff_pct}%</span></TableCell>
                  <TableCell><Badge className="bg-white/10 border-0 text-[#9CA3AF] text-xs">{r.sellers}</Badge></TableCell>
                  <TableCell><ConfidenceBadge confidence={r.confidence} method={r.match_method} /></TableCell>
                  <TableCell><FlagBadges flags={r.flags} /></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Section: Unverified Matches (<75% confidence) */}
      {tab === "unverified" && (
        <div className="glass-card overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 bg-[#F59E0B]/5">
            <p className="text-xs text-[#F59E0B]">{isRTL ? "هذه المطابقات بثقة أقل من 75% — تحتاج مراجعة يدوية" : "These matches have <75% confidence — manual review required"}</p>
          </div>
          <Table className="dense-table">
            <TableHeader><TableRow>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">My Product</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">My Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Competitor</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Confidence</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Actions</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {(data.unverified || []).length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center py-12 text-[#9CA3AF]">No unverified matches</TableCell></TableRow>
              ) : (data.unverified || []).slice(0, 50).map((r) => (
                <TableRow key={r.my_sku}>
                  <TableCell><p className="text-sm text-white truncate max-w-[200px]">{r.my_name_en || r.my_name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{r.my_sku}</p></TableCell>
                  <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
                  <TableCell><span className="text-xs text-[#9CA3AF]">{r.cheapest_competitor}</span><br/><span className="text-sm metric-number text-white">{r.cheapest_price} SAR</span></TableCell>
                  <TableCell><span className={`text-sm font-bold ${r.diff_pct > 5 ? "text-[#EF4444]" : "text-[#9CA3AF]"}`}>{r.diff_pct > 0 ? "+" : ""}{r.diff_pct}%</span></TableCell>
                  <TableCell><ConfidenceBadge confidence={r.confidence} method={r.match_method} /></TableCell>
                  <TableCell>
                    <Button size="sm" variant="ghost" onClick={() => openDetail(r.my_sku)} className="text-[10px] text-[#00D4B4] h-7">Review</Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Catalog Gaps — Products I Don't Sell */}
      {tab === "gaps" && (
        <div className="glass-card overflow-hidden">
          <div className="px-4 py-3 border-b border-white/5 bg-[#00D4B4]/5">
            <p className="text-xs text-[#00D4B4]">{isRTL ? "منتجات رائجة لا تبيعها — فرص إيرادات فورية" : "Trending products you DON'T sell — immediate revenue opportunities"}</p>
            <Badge className="text-[8px] bg-[#F59E0B]/10 text-[#F59E0B] border-0 mt-1">Includes baseline data (expires May 17)</Badge>
          </div>
          <Table className="dense-table">
            <TableHeader><TableRow>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Priority</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Product</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Barcode</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Est. Revenue (14d)</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Units Sold</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Sellers</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Avg Price</TableHead>
              <TableHead className="text-[10px] uppercase text-[#9CA3AF]">Action</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {catalogGaps.length === 0 ? (
                <TableRow><TableCell colSpan={8} className="text-center py-12 text-[#9CA3AF]">No catalog gaps found</TableCell></TableRow>
              ) : catalogGaps.map((g) => (
                <TableRow key={g.barcode}>
                  <TableCell>
                    <Badge className={`text-[10px] border-0 ${g.priority?.includes("🔴") ? "bg-[#EF4444]/15 text-[#EF4444]" : "bg-[#F59E0B]/15 text-[#F59E0B]"}`}>{g.priority}</Badge>
                  </TableCell>
                  <TableCell><p className="text-sm text-white font-medium max-w-[250px] truncate">{g.product_name}</p></TableCell>
                  <TableCell><span className="text-xs font-mono text-[#9CA3AF]">{g.barcode}</span></TableCell>
                  <TableCell><span className="text-sm font-bold text-[#00D4B4] metric-number">{g.est_revenue_sar?.toLocaleString()} SAR</span></TableCell>
                  <TableCell><span className="text-sm metric-number text-white">{g.est_units_sold}</span></TableCell>
                  <TableCell><Badge className="bg-white/10 border-0 text-[#9CA3AF] text-xs">{g.sellers_count}</Badge></TableCell>
                  <TableCell><span className="text-sm metric-number text-white">{g.avg_price_sar} SAR</span></TableCell>
                  <TableCell><span className="text-[10px] text-[#F59E0B] font-medium">{g.action}</span></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Section D: Product Detail Drill-Down */}
      <Sheet open={!!selectedSku} onOpenChange={(o) => { if (!o) { setSelectedSku(null); setDetail(null); } }}>
        <SheetContent className="w-[600px] sm:max-w-[600px] bg-[#111827] border-white/10 overflow-y-auto" data-testid="product-detail-sheet">
          <SheetHeader>
            <SheetTitle className="text-white text-lg">{detail?.my_product?.name_en || detail?.my_product?.name_ar || "Loading..."}</SheetTitle>
          </SheetHeader>
          {detail && (
            <div className="space-y-5 mt-4">
              {/* My Product Info */}
              <div className="glass-card p-4">
                <p className="text-[10px] uppercase text-[#9CA3AF] tracking-wider mb-2">My Product</p>
                <div className="flex items-center gap-3">
                  {detail.my_product.image_url && <img src={detail.my_product.image_url} alt="" className="w-16 h-16 rounded-lg object-cover bg-white/5" />}
                  <div>
                    <p className="text-sm text-white font-medium">{detail.my_product.name_en}</p>
                    <p className="text-xs text-[#9CA3AF]">{detail.my_product.name_ar}</p>
                    <p className="text-lg font-bold text-[#00D4B4] metric-number mt-1">{detail.market_summary.my_price} SAR</p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3 mt-3 text-xs">
                  <div><span className="text-[#9CA3AF]">Lowest:</span> <span className="text-white font-semibold">{detail.market_summary.lowest_price} SAR</span></div>
                  <div><span className="text-[#9CA3AF]">Highest:</span> <span className="text-white font-semibold">{detail.market_summary.highest_price} SAR</span></div>
                  <div><span className="text-[#9CA3AF]">Sellers:</span> <span className="text-white font-semibold">{detail.market_summary.sellers_count}</span></div>
                </div>
              </div>

              {/* Competitors */}
              {detail.competitors.map((c) => (
                <div key={`${c.competitor_sku}-${c.competitor_store_id}`} className="glass-card p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <p className="text-sm text-white font-medium">{c.competitor_store_name}</p>
                      <p className="text-[10px] text-[#9CA3AF]">{c.competitor_name}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <ConfidenceBadge confidence={c.confidence} method={c.match_method} />
                      <FlagBadges flags={c.flags} />
                    </div>
                  </div>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-lg font-bold text-white metric-number">{c.competitor_price} SAR</span>
                    <span className={`text-sm font-semibold ${c.diff_pct > 0 ? "text-[#10B981]" : c.diff_pct < 0 ? "text-[#EF4444]" : "text-[#9CA3AF]"}`}>
                      {c.diff_pct > 0 ? "+" : ""}{c.diff_pct}% ({c.diff_sar > 0 ? "+" : ""}{c.diff_sar} SAR)
                    </span>
                    <Badge className={`text-[10px] border-0 ${c.competitor_in_stock ? "bg-[#10B981]/15 text-[#10B981]" : "bg-[#EF4444]/15 text-[#EF4444]"}`}>
                      {c.competitor_in_stock ? "In Stock" : "OOS"}
                    </Badge>
                  </div>
                  {/* Price History Chart */}
                  {c.price_history?.length > 1 && (
                    <div className="h-24 mt-2">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={c.price_history}>
                          <XAxis dataKey="date" hide />
                          <YAxis domain={["auto", "auto"]} hide />
                          <Tooltip contentStyle={{ background: "#1F2937", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 11 }} labelStyle={{ color: "#9CA3AF" }} />
                          <ReferenceLine y={detail.market_summary.my_price} stroke="#00D4B4" strokeDasharray="3 3" strokeWidth={1} />
                          <Line type="monotone" dataKey="price" stroke="#F59E0B" strokeWidth={2} dot={false} />
                        </LineChart>
                      </ResponsiveContainer>
                      <p className="text-[9px] text-[#9CA3AF] text-center mt-0.5">Trend: <span className={`font-semibold ${c.price_trend === "rising" ? "text-[#EF4444]" : c.price_trend === "falling" ? "text-[#10B981]" : "text-[#9CA3AF]"}`}>{c.price_trend}</span></p>
                    </div>
                  )}
                  {/* Confirm/Reject */}
                  <div className="flex gap-2 mt-3 pt-3 border-t border-white/5">
                    <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); confirmMatch(c); }}
                      className="text-[10px] text-[#10B981] hover:bg-[#10B981]/10 gap-1 h-7" data-testid={`confirm-${c.competitor_sku}`}>
                      <CheckCircle2 className="w-3 h-3" />Confirm
                    </Button>
                    <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); rejectMatch(c); }}
                      className="text-[10px] text-[#EF4444] hover:bg-[#EF4444]/10 gap-1 h-7" data-testid={`reject-${c.competitor_sku}`}>
                      <XCircle className="w-3 h-3" />Reject
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
