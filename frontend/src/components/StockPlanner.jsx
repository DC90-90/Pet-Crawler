/**
 * Stock planner (17 Oct 2026): days of stock left per own product, what to
 * reorder for the lead time + cover chosen, and what running out cost —
 * including what measured competitors sold of it while it was out at mine.
 */
import { useMemo, useState } from "react";
import { SalesPeriod } from "@/components/SalesPeriod";
import { useQuery } from "@tanstack/react-query";
import { ImageOff } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { RequestError } from "@/components/RequestError";
import { SkuLine } from "@/components/SkuLine";

const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const STATUSES = [
  ["out", "Out of stock", "نفد", "#EF4444"],
  ["critical", "Runs out before restock", "ينفد قبل التوريد", "#EF4444"],
  ["low", "Low", "منخفض", "#F59E0B"],
  ["ok", "Healthy", "جيد", "#10B981"],
  ["overstock", "Overstock (4+ months)", "مخزون زائد", "#6AC1B5"],
  ["no_sales", "No sales", "بلا مبيعات", "#A1E4DB"],
];

export default function StockPlanner() {
  const { isRTL } = useI18n();
  const [lead, setLead] = useState(7);
  const [cover, setCover] = useState(30);
  const [status, setStatus] = useState("out");
  const [shown, setShown] = useState(50);
  const q = useQuery({
    queryKey: ["stock-planner", lead, cover],
    queryFn: async () => (await api.get("/stock/planner", { params: { lead_days: lead, cover_days: cover }, timeout: 90000 })).data,
  });
  const rows = useMemo(() => (q.data?.rows || []).filter((r) => r.status === status), [q.data, status]);
  if (q.isError) return <RequestError id="stock-planner-request" error={q.error} onRetry={() => q.refetch()} />;
  const s = q.data?.summary;

  return (
    <div className="glass-card rounded-md p-5 space-y-4" data-testid="stock-planner">
      <p className="text-xs text-[#A1E4DB]">
        {isRTL ? "كم يكفي مخزونك، ماذا تعيد طلبه، وكم كلّفك نفاد المخزون — من دفتر متجرك اليومي لآخر 30 يوماً مكتملة."
          : "How long your stock lasts, what to reorder, and what running out cost — from your store's daily ledger, last 30 complete days."}
      </p>
      <SalesPeriod from={q.data?.window?.from} to={q.data?.window?.to} days={q.data?.window?.days || 30}
        basis={isRTL ? "سرعة بيعك من دفتر متجرك اليومي" : "your sales rate from your store's daily ledger"} />
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <label className="text-[#A1E4DB] inline-flex items-center gap-2">{isRTL ? "مدة التوريد (أيام)" : "Supplier lead time (days)"}
          <input type="number" min={1} max={60} value={lead} onChange={(e) => setLead(Math.max(1, Number(e.target.value) || 7))} className="w-16 h-7 px-2 rounded bg-[#0A2728] border border-[#13625F] text-white" />
        </label>
        <label className="text-[#A1E4DB] inline-flex items-center gap-2">{isRTL ? "تغطية بعد التوريد (أيام)" : "Cover after delivery (days)"}
          <input type="number" min={7} max={120} value={cover} onChange={(e) => setCover(Math.max(7, Number(e.target.value) || 30))} className="w-16 h-7 px-2 rounded bg-[#0A2728] border border-[#13625F] text-white" />
        </label>
      </div>
      {!s ? <p className="text-xs text-[#A1E4DB]">{isRTL ? "جارٍ الحساب…" : "Working it out…"}</p> : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="stock-planner-kpis">
            {[
              [isRTL ? "باعه المنافسون أثناء نفاده لديك" : "Competitors sold while you were out", `${fmt(s.competitor_revenue_while_oos)} SAR`, isRTL ? "مبيعات مقاسة" : "measured sales"],
              [isRTL ? "مبيعاتك المفقودة (تقدير)" : "Your lost sales (estimate)", `${fmt(s.lost_revenue_est)} SAR`, isRTL ? "أيام النفاد × معدل بيعك" : "days out × your sales rate"],
              [isRTL ? "منتجات تحتاج طلباً" : "Products to reorder", fmt(s.reorder_products), isRTL ? `بقيمة ${fmt(s.reorder_value_at_cost)} ريال بالتكلفة` : `${fmt(s.reorder_value_at_cost)} SAR at cost`],
              [isRTL ? "تنفد قبل التوريد" : "Run out before restock", fmt(s.critical), isRTL ? `${fmt(s.low)} منخفض` : `${fmt(s.low)} more are low`],
            ].map(([label, value, sub]) => (
              <div key={label} className="kpi-card !p-3">
                <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p>
                <p className="text-lg font-bold text-white mt-0.5">{value}</p>
                <p className="text-[10px] text-[#A1E4DB]">{sub}</p>
              </div>
            ))}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {STATUSES.map(([id, en, ar, color]) => (
              <button key={id} onClick={() => { setStatus(id); setShown(50); }} data-testid={`stock-status-${id}`}
                className={`h-8 px-3 rounded-full text-xs inline-flex items-center gap-1.5 ${status === id ? "bg-[#1E988E] text-[#090E1C] font-semibold" : "bg-white/5 text-[#A1E4DB] hover:text-white"}`}>
                <span className="w-2 h-2 rounded-full" style={{ background: color }} />{isRTL ? ar : en}<span className="opacity-70">{fmt(s[id])}</span>
              </button>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="stock-planner-table">
              <thead>
                <tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">
                  <th className="text-start p-2">{isRTL ? "المنتج" : "Product"}</th>
                  <th className="text-end p-2">{isRTL ? "المخزون" : "Stock"}</th>
                  <th className="text-end p-2">{isRTL ? "بيع/يوم" : "Sold/day"}</th>
                  <th className="text-end p-2">{isRTL ? "يكفي (أيام)" : "Days left"}</th>
                  <th className="text-end p-2">{isRTL ? "اطلب" : "Reorder"}</th>
                  <th className="text-end p-2">{isRTL ? "أيام النفاد" : "Days out"}</th>
                  <th className="text-end p-2">{isRTL ? "باعه المنافسون أثناءها" : "Competitors sold meanwhile"}</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, shown).map((r) => (
                  <tr key={r.sku} className="border-b border-white/5">
                    <td className="p-2">
                      <div className="flex items-center gap-2">
                        <div className="w-9 h-9 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
                          {r.image_url ? <img src={r.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : <ImageOff className="w-4 h-4 text-gray-400" />}
                        </div>
                        <div className="min-w-0"><p className="text-white truncate max-w-[280px]">{r.name_ar || r.name_en}</p><SkuLine sku={r.sku} barcode={r.barcode} /></div>
                      </div>
                    </td>
                    <td className="p-2 text-end text-white">{fmt(r.quantity)}</td>
                    <td className="p-2 text-end text-white">{fmt(r.velocity_per_day, 2)}</td>
                    <td className="p-2 text-end text-white">{r.days_of_cover == null ? "—" : fmt(r.days_of_cover, 1)}</td>
                    <td className="p-2 text-end font-semibold text-white">{r.reorder_qty ? fmt(r.reorder_qty) : "—"}</td>
                    <td className="p-2 text-end text-[#A1E4DB]">{r.oos_days || "—"}{r.lost_revenue_est ? <span className="block text-[10px]">{isRTL ? `≈ ${fmt(r.lost_revenue_est)} ريال مفقودة` : `≈ ${fmt(r.lost_revenue_est)} SAR lost`}</span> : null}</td>
                    <td className="p-2 text-end text-white">{r.competitor_revenue_while_oos ? `${fmt(r.competitor_revenue_while_oos)} SAR` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length === 0 && <p className="p-4 text-xs text-[#A1E4DB]">{isRTL ? "لا توجد منتجات هنا." : "Nothing here."}</p>}
          </div>
          {rows.length > shown && <button className="text-xs text-[#6AC1B5] hover:text-white" onClick={() => setShown((n) => n + 50)}>{isRTL ? `عرض المزيد (${rows.length - shown})` : `Show more (${rows.length - shown})`}</button>}
        </>
      )}
    </div>
  );
}
