import { Shield, Info, Trophy } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { CONFIDENCE_LEVELS } from "./PriceIntelShared";

export function PriceIntelKpiRow({ summary }) {
  const cards = [
    { label: "My Products", val: summary.total_products, color: "#1E988E" },
    { label: "Matched", val: summary.matched_products, color: "#10B981" },
    { label: "Overpriced (RED)", val: summary.overpriced_red, color: "#EF4444" },
    { label: "Overpriced (YELLOW)", val: summary.overpriced_yellow, color: "#F59E0B" },
    { label: "I'm Cheapest", val: summary.cheapest_count, color: "#10B981" },
    { label: "OOS Opportunity", val: summary.oos_opportunities, color: "#1E988E" },
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      {cards.map((k) => (
        <div key={k.label} className="kpi-card">
          <p className="text-[9px] uppercase tracking-wider text-[#A1E4DB]">{k.label}</p>
          <p className="text-xl font-bold metric-number" style={{ color: k.color }}>{k.val}</p>
        </div>
      ))}
    </div>
  );
}

export function ConfidenceDistribution({ distribution, isRTL, showGuide, onToggleGuide }) {
  if (!distribution) return null;
  const total = Object.values(distribution).reduce((a, b) => a + b, 0) || 1;
  const segments = [
    { key: "confirmed_100", label: "Confirmed", count: distribution.confirmed_100, color: "#10B981" },
    { key: "barcode_99", label: "Barcode", count: distribution.barcode_99, color: "#059669" },
    { key: "sku_95", label: "SKU", count: distribution.sku_95, color: "#1E988E" },
    { key: "name_85", label: "Name 5+", count: distribution.name_85, color: "#0EA5E9" },
    { key: "name_80", label: "Name 4", count: distribution.name_80, color: "#F59E0B" },
    { key: "baseline_80", label: "Baseline", count: distribution.baseline_80, color: "#D97706" },
    { key: "name_70", label: "Name 3", count: distribution.name_70, color: "#EF4444" },
  ].filter(s => s.count > 0);

  return (
    <div className="glass-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Shield className="w-4 h-4 text-[#1E988E]" />
          <h3 className="text-sm font-semibold text-white">{isRTL ? "توزيع الثقة" : "Match Confidence Distribution"}</h3>
          <span className="text-[10px] text-[#A1E4DB]">{total.toLocaleString()} total matches</span>
        </div>
        <button onClick={onToggleGuide} className="flex items-center gap-1 text-[10px] text-[#1E988E] hover:text-[#6AC1B5] transition-colors" data-testid="toggle-guide">
          <Info className="w-3.5 h-3.5" />{showGuide ? "Hide" : "Show"} Confidence Guide
        </button>
      </div>
      <div className="flex h-4 rounded-full overflow-hidden mb-2">
        {segments.map(seg => (
          <div key={seg.key} style={{ width: `${(seg.count / total) * 100}%`, backgroundColor: seg.color }} className="transition-all duration-500" title={`${seg.label}: ${seg.count}`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {segments.map(seg => (
          <div key={seg.key} className="flex items-center gap-1.5 text-[10px]">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: seg.color }} />
            <span className="text-[#A1E4DB]">{seg.label}</span>
            <span className="text-white font-semibold metric-number">{seg.count}</span>
            <span className="text-[#A1E4DB]">({Math.round((seg.count / total) * 100)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ConfidenceGuidePanel({ isRTL }) {
  return (
    <div className="glass-card p-5 border border-[#1E988E]/20 animate-fadeIn" data-testid="confidence-guide">
      <div className="flex items-center gap-2 mb-4">
        <Shield className="w-5 h-5 text-[#1E988E]" />
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
                <p className="text-[11px] text-[#A1E4DB] mt-0.5">{isRTL ? lvl.descAr : lvl.desc}</p>
              </div>
              <div className="w-24 h-2 rounded-full bg-white/5 mt-2 overflow-hidden">
                <div className="h-full rounded-full transition-all" style={{ width: `${lvl.min}%`, backgroundColor: lvl.color }} />
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-4 pt-3 border-t border-white/5 text-[10px] text-[#A1E4DB] space-y-1">
        <p><strong className="text-white">Rule:</strong> {isRTL ? "المقارنات بثقة أقل من 75% تظهر فقط في تبويب 'غير مؤكد' للمراجعة اليدوية" : "Comparisons below 75% confidence appear ONLY in the 'Unverified' tab for manual review"}</p>
        <p><strong className="text-white">Rule:</strong> {isRTL ? "الفرق بالسعر أكثر من 150% يتم رفضه تلقائياً لتطابقات الأسماء" : "Price differences >150% are auto-rejected for name-based matches"}</p>
        <p><strong className="text-white">Rule:</strong> {isRTL ? "فرق الوزن أكثر من 10% = رفض المطابقة" : "Weight difference >10% = match rejected entirely"}</p>
        <p><strong className="text-white">Rule:</strong> {isRTL ? "المنتجات المتعددة (باك) لا تطابق مع المنتجات المفردة أبداً" : "Multi-pack products NEVER match single units"}</p>
      </div>
    </div>
  );
}

export function MarketPositionWidget({ leaderboard, isRTL }) {
  if (!leaderboard?.my_store_baseline) return null;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 mb-3">
          <Trophy className="w-5 h-5 text-[#F59E0B]" />
          <h3 className="text-sm font-semibold text-white">{isRTL ? "ترتيبك في السوق" : "Market Position"}</h3>
          <Badge className="text-[8px] bg-[#F59E0B]/10 text-[#F59E0B] border-0 ms-auto">Baseline data (expires May 17)</Badge>
        </div>
        <div className="flex items-end gap-1 mb-3">
          <span className="text-4xl font-bold text-[#F59E0B] metric-number">#{leaderboard.my_store_baseline.market_rank}</span>
          <span className="text-[#A1E4DB] text-sm mb-1">of {leaderboard.my_store_baseline.market_total_stores} stores</span>
        </div>
        <div className="space-y-1.5">
          {leaderboard.leaderboard?.slice(0, 7).map((e) => (
            <div key={e.rank} className={`flex items-center gap-2 text-xs py-1 px-2 rounded-lg ${e.is_my_store ? "bg-[#1E988E]/10 border border-[#1E988E]/20" : ""}`}>
              <span className="text-[#A1E4DB] w-5 text-right">#{e.rank}</span>
              <span className={`flex-1 ${e.is_my_store ? "text-[#1E988E] font-semibold" : "text-white"}`}>{e.store_domain}</span>
              <span className="text-[#A1E4DB]">{e.relative_size}</span>
            </div>
          ))}
          {leaderboard.leaderboard?.length > 7 && (
            <div className="text-[10px] text-[#A1E4DB] text-center pt-1">
              ... + {leaderboard.leaderboard.length - 7} more stores (you are #{leaderboard.my_store_baseline.market_rank})
            </div>
          )}
        </div>
      </div>
      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">{isRTL ? "أداء متجرك" : "Your Store Performance"}</h3>
        <div className="grid grid-cols-2 gap-4">
          <div><p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">Est. Revenue (14d)</p><p className="text-xl font-bold text-[#1E988E] metric-number">{leaderboard.my_store_baseline.est_revenue_sar?.toLocaleString()} SAR</p></div>
          <div><p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">Est. Units Sold</p><p className="text-xl font-bold text-white metric-number">{leaderboard.my_store_baseline.est_units_sold?.toLocaleString()}</p></div>
          <div><p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">Active Products</p><p className="text-xl font-bold text-white metric-number">{leaderboard.my_store_baseline.total_products?.toLocaleString()}</p></div>
          <div><p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">Price Spread</p><p className="text-xl font-bold text-[#F59E0B] metric-number">{leaderboard.my_store_baseline.median_price_spread_pct}%</p></div>
        </div>
      </div>
    </div>
  );
}
