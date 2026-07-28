import { useState } from "react";
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

// iter38 — the left card is now the LIVE Market Strength ranking (fixed 30d,
// recomputed after every crawl). The static April MySkuWatch list and its star
// ratings are gone from this widget entirely. The right card stays the live
// "Your Store Performance" (iter32).
function ScoreBar({ value, color = "#1E988E" }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="w-16 h-1.5 rounded-full bg-white/10 overflow-hidden inline-block">
        <span className="h-full block rounded-full" style={{ width: `${Math.max(2, Math.min(100, value))}%`, background: color }} />
      </span>
      <span className="metric-number text-xs font-bold text-white">{value}</span>
    </span>
  );
}

function RevenueCell({ row, isRTL }) {
  // MEASURED revenue — unchanged, solid teal, no tag.
  if (row.revenue_30d != null) {
    return <span className="metric-number text-[#6AC1B5]">{row.revenue_30d.toLocaleString()} SAR</span>;
  }

  // iter59 — TIER 2: MEASURED (APPROX.) from the Salla sold badge. This is a
  // real observation — the cumulative counter diffed between crawls — so it is
  // NOT the ±50% estimate. But the badge is bucketed by Salla, so it is not the
  // exact Zid figure either. Its own colour: sky, solid (not italic), between
  // measured teal and estimate amber.
  const ap = row.revenue_approx;
  if (ap && ap.usable && ap.revenue > 0) {
    const tip = isRTL
      ? `مقاس (تقريبي). مأخوذ من عدّاد المبيعات التراكمي الذي يعرضه متجر سلة ("تم بيعه أكثر من N مرة")، بفرق القراءات بين عمليتي زحف — أي مبيعات مرصودة فعلاً، وليست تقديراً.\n\n`
        + `تقريبي لأن سلة تعرض الرقم مقرَّباً/محدوداً بسقف، لا كعدد دقيق.\n\n`
        + `مبني على ${ap.products_measured} من ${ap.products_total} منتج (${ap.coverage_pct}%).`
        + (ap.products_capped ? ` ${ap.products_capped} منتج بقراءة محدودة بسقف واستُبعد.` : "")
        + (ap.products_baseline_only ? ` ${ap.products_baseline_only} منتج بقراءة واحدة فقط (يحتاج زحفة ثانية).` : "")
      : `Measured (approx.). Taken from the cumulative sold-counter Salla shows on the storefront ("sold more than N times"), diffed between crawls — real observed sales, not an estimate.\n\n`
        + `Approximate because Salla buckets and caps that number rather than publishing an exact unit count.\n\n`
        + `Based on ${ap.products_measured} of ${ap.products_total} products (${ap.coverage_pct}%).`
        + (ap.products_capped ? ` ${ap.products_capped} had a capped reading and were excluded.` : "")
        + (ap.products_baseline_only ? ` ${ap.products_baseline_only} have only one reading so far (need a second crawl).` : "");
    return (
      <span className="inline-flex flex-col gap-0.5" title={tip} data-testid="revenue-approx">
        <span className="inline-flex items-center gap-1.5">
          <span className="metric-number text-[#38BDF8]">
            {Math.round(ap.revenue).toLocaleString()} SAR
          </span>
          <span className="text-[9px] px-1 py-0.5 rounded bg-[#38BDF8]/10 text-[#38BDF8]/90 tracking-wide">
            {isRTL ? "مقاس تقريبي" : "MEASURED ~"}
          </span>
        </span>
        <span className="text-[9px] text-[#38BDF8]/60 leading-none">
          {isRTL ? `من عدّاد سلة · ${ap.coverage_pct}% تغطية`
                 : `from Salla sold-count · ${ap.coverage_pct}% coverage`}
        </span>
      </span>
    );
  }

  // iter57 — TIER 3: ROUGH ESTIMATE for platforms that hide sold-counts. Rendered
  // deliberately unlike the measured value: amber not teal, reduced opacity, an
  // explicit ESTIMATE tag, and a "~". ONE fixed +/-50% band for every store —
  // a coverage-derived band would tighten per store and imply a precision the
  // back-test does not support, and these figures inform pricing decisions.
  const est = row.revenue_est_salla;
  if (est && est.revenue_est > 0) {
    const tip = isRTL
      ? `تقدير تقريبي. متاجر سلة لا تكشف عدادات المبيعات، لذا يُشتق هذا الرقم من سرعة البيع المرصودة في متاجر زد مطبَّقة على كتالوج هذا المتجر — بدقة تقارب ±50% فقط. `
        + `استخدمه للمقارنة الاتجاهية، لا كأرقام دقيقة أو أساس للقرارات.\n\n`
        + `النطاق: ${Math.round(est.range_low).toLocaleString()}–${Math.round(est.range_high).toLocaleString()} ريال.\n\n`
        + `يصبح هذا الرقم مقاساً بمجرد أن نلتقط قراءتين من عدّاد المبيعات في المتجر ونحسب الفرق بينهما.\n\n`
        + `تنبيه: الترتيب مبني على الإيرادات، وهذا الصف مُرتَّب بهذا التقدير — أي أن موقعه قد يزيح بمقدار ±50%.`
      : `Rough estimate. This store's sold-counts have not been captured yet, so the figure is projected from Zid-store sales velocity applied to this store's catalog — accurate only to roughly ±50%. `
        + `Use for directional comparison, not exact figures or decisions.\n\n`
        + `Range: ${Math.round(est.range_low).toLocaleString()}–${Math.round(est.range_high).toLocaleString()} SAR.\n\n`
        + `It becomes MEASURED once we have two readings of the storefront's cumulative sold-counter to diff.\n\n`
        + `Note: the ranking is sorted by revenue, and this row is placed using this estimate — so its position could move by ±50%.`;
    return (
      <span className="inline-flex flex-col gap-0.5" title={tip} data-testid="revenue-est-salla">
        <span className="inline-flex items-center gap-1.5">
          <span className="metric-number text-[#F59E0B]/75 italic">
            ~{Math.round(est.revenue_est).toLocaleString()} SAR
          </span>
          <span className="text-[9px] px-1 py-0.5 rounded bg-[#F59E0B]/10 text-[#F59E0B]/90 not-italic tracking-wide">
            {isRTL ? "تقدير" : "ESTIMATE"}
          </span>
        </span>
        <span className="text-[9px] text-[#F59E0B]/60 leading-none">
          {isRTL ? `تقدير تقريبي · ±${est.band_pct}%` : `rough estimate · ±${est.band_pct}%`}
        </span>
      </span>
    );
  }

  if (row.revenue_status === "not_measurable") {
    // iter40 — blame Salla only when the store actually IS Salla; other
    // platforms without signals get a neutral label so the Salla claim
    // stays credible.
    const isSalla = row.platform === "salla";
    return (
      <span
        className="text-[9px] px-1.5 py-0.5 rounded bg-[#F59E0B]/10 text-[#F59E0B]"
        title={isSalla
          ? (isRTL ? "هذا المتجر لا يكشف عدادات المبيعات أو كميات قابلة للاستخدام" : "This store exposes no sales counters or usable quantities")
          : (isRTL ? "لا توجد إشارات مبيعات لهذا المتجر" : "No sales signals for this store")}
      >
        ⓘ {isSalla
          ? (isRTL ? "غير قابل للقياس (سلة)" : "Not measurable (Salla)")
          : (isRTL ? "غير قابل للقياس" : "Not measurable")}
      </span>
    );
  }
  return <span className="text-[9px] text-[#A1E4DB]">{isRTL ? "قيد التجميع" : "Accumulating"}</span>;
}

export function StoreRankingCard({ ranking, computedAt, isRTL }) {
  const [expanded, setExpanded] = useState(null);
  if (!ranking?.stores?.length) {
    return (
      <div className="glass-card p-5">
        <p className="text-[11px] text-[#A1E4DB]">{isRTL ? "لا توجد بيانات تصنيف حية بعد" : "No live ranking data yet"}</p>
      </div>
    );
  }
  const own = ranking.stores.find((r) => r.is_own_store);
  const compMeta = [
    { key: "breadth", label: isRTL ? "اتساع الكتالوج" : "Catalog breadth", w: 25, detail: (c) => `${c.breadth.products.toLocaleString()} ${isRTL ? "منتج" : "products"}` },
    { key: "price", label: isRTL ? "تنافسية الأسعار" : "Price competitiveness", w: 35, detail: (c) => c.price.avg_percentile != null ? `P${c.price.avg_percentile} · ${c.price.shared_products.toLocaleString()} ${isRTL ? "منتج مشترك" : "shared"}` : (isRTL ? "لا منتجات مشتركة" : "no shared products") },
    { key: "stock", label: isRTL ? "توفر المخزون" : "Stock health", w: 25, detail: (c) => `${Math.round(c.stock.score * 100)}% ${isRTL ? "متوفر" : "in stock"}` },
    { key: "freshness", label: isRTL ? "حداثة البيانات" : "Data freshness", w: 15, detail: (c) => `${Math.round(c.freshness.score * 100)}% ${isRTL ? "خلال 48 ساعة" : "seen <48h"}` },
  ];
  return (
    <div className="glass-card p-5" data-testid="store-ranking-card">
      <div className="flex items-center gap-2 mb-1">
        <Trophy className="w-5 h-5 text-[#F59E0B]" />
        <h3 className="text-sm font-semibold text-white">{isRTL ? "ترتيب قوة السوق" : "Market Strength Ranking"}</h3>
      </div>
      {/* iter62 — rank is by REVENUE now, not by the strength score. Saying so
          on the card matters: the rows still show a strength bar, and without
          this line a reader would reasonably assume the bar produced the order. */}
      <p className="text-[10px] text-[#A1E4DB] mb-2" data-testid="ranking-sort-note">
        {isRTL ? "مرتَّب حسب الإيرادات (الأعلى أولاً) · درجة القوة معروضة كمعلومة ثانوية"
               : "Ranked by revenue (highest first) · strength score shown as secondary info"}
      </p>
      {own && (
        <div className="flex items-end gap-2 mb-1" data-testid="own-rank-headline">
          <span className="text-4xl font-bold text-[#1E988E] metric-number">#{own.rank}</span>
          <span className="text-[#A1E4DB] text-sm mb-1">
            {isRTL ? `من ${ranking.total_stores} متجراً حسب الإيرادات · قوة السوق ${own.score}`
                   : `of ${ranking.total_stores} stores by revenue · Market Strength ${own.score}`}
          </span>
        </div>
      )}
      {/* How much of the order rests on a +/-50% projection rather than on
          measurement. The per-row tags say it too, but a reader scanning the
          ORDER needs it stated about the order itself. */}
      {ranking.ranked_on_estimate > 0 && (
        <p className="text-[10px] text-[#F59E0B]/85 mb-1" data-testid="ranking-estimate-note">
          {isRTL
            ? `${ranking.ranked_on_estimate} من ${ranking.total_stores} صفاً مرتَّب بتقدير ±50% (بالعنبري) — موضعها تقريبي`
            : `${ranking.ranked_on_estimate} of ${ranking.total_stores} rows are placed using a ±50% estimate (shown in amber) — those positions are approximate`}
          {ranking.no_revenue_value > 0 && (isRTL
            ? ` · ${ranking.no_revenue_value} بلا رقم إيرادات على الإطلاق (في الأسفل)`
            : ` · ${ranking.no_revenue_value} have no revenue figure at all (placed last)`)}
        </p>
      )}
      {computedAt && (
        <p className="text-[10px] text-[#6AC1B5] mb-3 font-mono">
          {isRTL ? "محدث حتى" : "as of"}{" "}
          {new Date(computedAt).toLocaleString(isRTL ? "ar-SA" : "en-GB", { dateStyle: "medium", timeStyle: "short" })}
          {" · "}{isRTL ? "آخر 30 يوماً" : "last 30 days"}
        </p>
      )}
      <div className="space-y-1">
        {ranking.stores.map((r) => (
          <div key={r.store_id}>
            <button
              type="button"
              onClick={() => setExpanded(expanded === r.store_id ? null : r.store_id)}
              className={`w-full flex items-center gap-2 text-xs py-1.5 px-2 rounded-lg text-start transition-colors hover:bg-white/5 ${r.is_own_store ? "bg-[#1E988E]/10 border border-[#1E988E]/20" : ""}`}
              data-testid={`ranking-row-${r.store_id}`}
              data-revenue-basis={r.revenue_rank_basis}
              data-revenue-rank-value={r.revenue_rank_value ?? ""}
            >
              <span className="text-[#A1E4DB] w-6 text-center metric-number">#{r.rank}</span>
              <span className={`flex-1 truncate ${r.is_own_store ? "text-[#1E988E] font-semibold" : "text-white"}`}>
                {r.name}
                <span className="text-[8px] ms-1.5 px-1 py-0.5 rounded bg-white/10 text-[#A1E4DB] uppercase">{r.platform}</span>
                {r.stale && (
                  <span className="text-[8px] ms-1 px-1 py-0.5 rounded bg-[#EF4444]/15 text-[#F87171]">
                    {isRTL ? "بيانات قديمة" : "stale data"}
                  </span>
                )}
              </span>
              {/* iter62 — the strength score is no longer the sort key, but it
                  stays on every row (bar + number) as secondary information. */}
              <span title={isRTL ? `قوة السوق ${r.score} (معلومة ثانوية — الترتيب حسب الإيرادات)`
                                 : `Market Strength ${r.score} (secondary — ranking is by revenue)`}>
                <ScoreBar value={r.score} color={r.is_own_store ? "#1E988E" : "#6AC1B5"} />
              </span>
              <span className="w-28 text-end hidden sm:inline-block"><RevenueCell row={r} isRTL={isRTL} /></span>
            </button>
            {expanded === r.store_id && (
              <div className="mx-2 mb-1 px-3 py-2 rounded-lg bg-black/20 border border-white/5 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5" data-testid={`ranking-breakdown-${r.store_id}`}>
                {compMeta.map((cm) => (
                  <div key={cm.key} className="flex items-center gap-2 text-[10px]">
                    <span className="text-[#A1E4DB] w-32 shrink-0">{cm.label} <span className="opacity-60">({cm.w}%)</span></span>
                    <span className="flex-1 h-1 rounded-full bg-white/10 overflow-hidden">
                      <span className="h-full block rounded-full bg-[#1E988E]" style={{ width: `${Math.round(r.components[cm.key].score * 100)}%` }} />
                    </span>
                    <span className="text-white metric-number w-8 text-end">{Math.round(r.components[cm.key].score * 100)}</span>
                    <span className="text-[#A1E4DB] opacity-70 w-28 text-end truncate">{cm.detail(r.components)}</span>
                  </div>
                ))}
                {r.overlap != null && (
                  <div className="text-[10px] text-[#A1E4DB] sm:col-span-2">
                    {isRTL ? `${r.overlap.toLocaleString()} منتجاً مشتركاً مع كتالوجك` : `${r.overlap.toLocaleString()} products overlap with your catalog`}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

export function MarketPositionWidget({ ranking, rankingComputedAt, myKpis, summary, isRTL }) {
  if (!ranking && !myKpis && !summary) return null;
  const isLedger = myKpis?.my_revenue_source === "zid_orders";
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      <StoreRankingCard ranking={ranking} computedAt={rankingComputedAt} isRTL={isRTL} />
      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">{isRTL ? "أداء متجرك (14 يوم)" : "Your Store Performance (14d)"}</h3>
        <div className="grid grid-cols-2 gap-4" data-testid="pi-store-performance-live">
          <div>
            <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">
              {isLedger ? (isRTL ? "الإيرادات (14 يوم)" : "Revenue (14d)") : (isRTL ? "الإيرادات المقدرة (14 يوم)" : "Est. Revenue (14d)")}
            </p>
            <p className="text-xl font-bold text-[#1E988E] metric-number">
              {myKpis?.my_revenue != null ? `${myKpis.my_revenue.toLocaleString()} SAR` : "—"}
            </p>
            {isLedger && myKpis?.my_orders_count != null && (
              <p className="text-[9px] text-[#6AC1B5]">{myKpis.my_orders_count.toLocaleString()} {isRTL ? "طلب · سجل زد" : "orders · Zid ledger"}</p>
            )}
          </div>
          <div>
            <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">
              {isLedger ? (isRTL ? "الوحدات المباعة" : "Units Sold") : (isRTL ? "الوحدات المباعة (تقديري)" : "Est. Units Sold")}
            </p>
            <p className="text-xl font-bold text-white metric-number">{myKpis?.my_units_sold != null ? myKpis.my_units_sold.toLocaleString() : "—"}</p>
          </div>
          <div>
            <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">{isRTL ? "المنتجات النشطة" : "Active Products"}</p>
            <p className="text-xl font-bold text-white metric-number">{myKpis?.total_products != null ? myKpis.total_products.toLocaleString() : "—"}</p>
          </div>
          <div>
            <p className="text-[9px] uppercase text-[#A1E4DB] tracking-wider">{isRTL ? "وسيط فرق السعر" : "Median Price Spread"}</p>
            <p className="text-xl font-bold text-[#F59E0B] metric-number">{summary?.median_spread != null ? `${summary.median_spread.toLocaleString()} SAR` : "—"}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
