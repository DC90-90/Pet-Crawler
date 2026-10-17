/**
 * Price recommendations (17 Oct 2026): one suggested shelf price per product
 * from the verified competitor cohort, the product's cost and the owner's
 * minimum margin; an admin approves a price and Daleel sends it to Zid.
 */
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowRight, Check, Settings2, ImageOff, History } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/App";
import { RequestError } from "@/components/RequestError";
import { SkuLine } from "@/components/SkuLine";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";

const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const ACTIONS = [
  ["lower", "Lower to compete", "خفّض للمنافسة", "#EF4444"],
  ["raise", "Raise margin", "ارفع الهامش", "#10B981"],
  ["check_cost", "Check cost", "راجع التكلفة", "#F59E0B"],
  ["check_identity", "Check product", "راجع المنتج", "#F59E0B"],
  ["hold", "Hold", "أبقِ السعر", "#A1E4DB"],
  ["restock", "Out of stock", "نفد المخزون", "#A1E4DB"],
  ["no_market", "No competitor", "بلا منافس", "#A1E4DB"],
];

function Settings({ settings, canEdit, isRTL, onSaved }) {
  const [form, setForm] = useState(settings);
  const [open, setOpen] = useState(false);
  const save = async () => {
    try {
      await api.put("/pricing/settings", { min_margin_pct: Number(form.min_margin_pct), raise_gap_pct: Number(form.raise_gap_pct), undercut_sar: Number(form.undercut_sar) });
      toast.success(isRTL ? "تم حفظ القواعد" : "Rules saved");
      setOpen(false); onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };
  return (
    <div className="glass-card rounded-md p-3 text-xs" data-testid="pricing-rules">
      <div className="flex flex-wrap items-center gap-3">
        <Settings2 className="w-4 h-4 text-[#1E988E]" />
        <span className="text-[#A1E4DB]">{isRTL ? "القواعد:" : "Rules:"}</span>
        <span className="text-white">{isRTL ? `أدنى هامش ${settings.min_margin_pct}%` : `minimum margin ${settings.min_margin_pct}%`}</span>
        <span className="text-white">{isRTL ? `ارفع إذا كنت أرخص بـ ${settings.raise_gap_pct}%+` : `raise when ${settings.raise_gap_pct}%+ under the next seller`}</span>
        <span className="text-white">{settings.undercut_sar ? (isRTL ? `أقل من الأرخص بـ ${settings.undercut_sar} ريال` : `${settings.undercut_sar} SAR under the cheapest`) : (isRTL ? "مطابقة الأرخص" : "match the cheapest")}</span>
        {canEdit && <button className="ms-auto text-[#6AC1B5] hover:text-white" onClick={() => setOpen((v) => !v)} data-testid="pricing-rules-edit">{isRTL ? "تعديل" : "Edit"}</button>}
      </div>
      {open && (
        <div className="flex flex-wrap items-end gap-3 mt-3">
          {[["min_margin_pct", isRTL ? "أدنى هامش %" : "Min margin %"], ["raise_gap_pct", isRTL ? "فجوة الرفع %" : "Raise gap %"], ["undercut_sar", isRTL ? "أقل من الأرخص (ريال)" : "Undercut (SAR)"]].map(([k, label]) => (
            <label key={k} className="text-[11px] text-[#A1E4DB] flex flex-col gap-1">{label}
              <input type="number" step="0.5" value={form[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                className="w-24 h-7 px-2 rounded bg-[#0A2728] border border-[#13625F] text-white" />
            </label>
          ))}
          <button onClick={save} className="h-7 px-3 rounded bg-[#1E988E] text-[#090E1C] font-semibold">{isRTL ? "حفظ" : "Save"}</button>
        </div>
      )}
    </div>
  );
}

export default function PriceRecommendations() {
  const { isRTL } = useI18n();
  const { user } = useAuth();
  const qc = useQueryClient();
  const canApply = ["super_admin", "admin"].includes(user?.role);
  const [action, setAction] = useState("lower");
  const [shown, setShown] = useState(50);
  const [confirm, setConfirm] = useState(null);
  const [sent, setSent] = useState({});
  const [showLog, setShowLog] = useState(false);
  const q = useQuery({ queryKey: ["pricing", "recommendations"], queryFn: async () => (await api.get("/pricing/recommendations", { timeout: 60000 })).data });
  const log = useQuery({ queryKey: ["pricing", "changes"], queryFn: async () => (await api.get("/pricing/changes")).data, enabled: showLog });
  const rows = useMemo(() => (q.data?.rows || []).filter((r) => r.action === action), [q.data, action]);
  if (q.isError) return <RequestError id="pricing-recs-request" error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <p className="text-sm text-[#A1E4DB]">{isRTL ? "جارٍ حساب التوصيات…" : "Working out recommendations…"}</p>;
  const { summary, settings } = q.data;

  const apply = async () => {
    const r = confirm;
    setConfirm(null);
    try {
      const { data } = await api.post("/pricing/apply", { sku: r.sku, price: r.recommended_price }, { timeout: 45000 });
      setSent((s) => ({ ...s, [r.sku]: data.status }));
      toast.success(data.status === "confirmed" ? (isRTL ? "تم تحديث السعر في زد" : "Price updated on Zid") : (isRTL ? "أُرسل السعر، بانتظار التأكيد" : "Price sent, not yet confirmed"));
      qc.invalidateQueries({ queryKey: ["pricing", "changes"] });
    } catch (e) {
      const d = e?.response?.data?.detail;
      toast.error((d && (d.reason || d)) || (isRTL ? "تعذر تحديث السعر" : "Could not update the price"));
    }
  };

  return (
    <div className="space-y-4" data-testid="pricing-recommendations">
      <Settings settings={settings} canEdit={canApply} isRTL={isRTL} onSaved={() => q.refetch()} />
      <div className="flex flex-wrap gap-1.5" data-testid="pricing-rec-actions">
        {ACTIONS.filter(([id]) => summary.by_action[id]).map(([id, en, ar, color]) => (
          <button key={id} onClick={() => { setAction(id); setShown(50); }} data-testid={`pricing-rec-${id}`}
            className={`h-8 px-3 rounded-full text-xs inline-flex items-center gap-1.5 ${action === id ? "bg-[#1E988E] text-[#090E1C] font-semibold" : "bg-white/5 text-[#A1E4DB] hover:text-white"}`}>
            <span className="w-2 h-2 rounded-full" style={{ background: color }} />{isRTL ? ar : en}<span className="opacity-70">{summary.by_action[id]}</span>
          </button>
        ))}
      </div>
      <p className="text-[11px] text-[#A1E4DB]">
        {action === "raise" && (isRTL ? `رفع هذه الأسعار يضيف نحو ${fmt(summary.raise_profit_30d, 0)} ريال ربحاً خلال 30 يوماً بنفس حجم المبيعات، مع بقائك الأرخص. ` : `Raising these adds about ${fmt(summary.raise_profit_30d, 0)} SAR profit over 30 days at the same sales, while you stay the cheapest. `)}
        {summary.without_cost > 0 && (isRTL ? `${summary.without_cost} منتجاً بلا تكلفة: الهامش لا يُحسب لها — ارفع ملف التكاليف من صفحة الاستيراد.` : `${summary.without_cost} products have no cost, so their margin can't be checked — upload costs on the Import page.`)}
      </p>

      <div className="glass-card rounded-md overflow-x-auto">
        <table className="w-full text-xs" data-testid="pricing-rec-table">
          <thead>
            <tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">
              <th className="text-start p-2">{isRTL ? "المنتج" : "Product"}</th>
              <th className="text-start p-2">{isRTL ? "السعر ← المقترح" : "Price → suggested"}</th>
              <th className="text-end p-2">{isRTL ? "الأرخص" : "Cheapest"}</th>
              <th className="text-end p-2">{isRTL ? "الهامش" : "Margin"}</th>
              <th className="text-end p-2">{isRTL ? "مبيع 30ي" : "Sold 30d"}</th>
              <th className="text-end p-2">{isRTL ? "أثر الربح 30ي" : "Profit 30d"}</th>
              <th className="text-start p-2">{isRTL ? "السبب" : "Why"}</th>
              {canApply && <th className="p-2" />}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, shown).map((r) => (
              <tr key={r.sku} className="border-b border-white/5" data-testid={`pricing-rec-row-${r.sku}`}>
                <td className="p-2">
                  <div className="flex items-center gap-2">
                    <div className="w-9 h-9 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
                      {r.image_url ? <img src={r.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : <ImageOff className="w-4 h-4 text-gray-400" />}
                    </div>
                    <div className="min-w-0">
                      <p className="text-white truncate max-w-[260px]">{r.name_ar || r.name_en}</p>
                      <SkuLine sku={r.sku} barcode={r.barcode} />
                    </div>
                  </div>
                </td>
                <td className="p-2 whitespace-nowrap">
                  <span className="text-white">{fmt(r.price)}</span>
                  {r.recommended_price != null && <>
                    <ArrowRight className="inline w-3 h-3 mx-1 text-[#A1E4DB]" />
                    <span className={`font-bold ${r.change_sar < 0 ? "text-[#EF4444]" : "text-[#10B981]"}`}>{fmt(r.recommended_price)}</span>
                    <span className="block text-[10px] text-[#A1E4DB]">{r.change_pct > 0 ? "+" : ""}{r.change_pct}%{r.rank_after === 1 ? (isRTL ? " · الأرخص" : " · cheapest") : ""}</span>
                  </>}
                </td>
                <td className="p-2 text-end text-[#A1E4DB]">{fmt(r.competitor_min_price)}<span className="block text-[10px]">{r.num_sellers ? `${r.num_sellers} ${isRTL ? "بائع" : "sellers"}` : ""}</span></td>
                <td className="p-2 text-end whitespace-nowrap">
                  {r.margin_now_pct == null ? <span className="text-[#A1E4DB]/60" title={isRTL ? "لا توجد تكلفة" : "No cost on file"}>—</span> : (
                    <span className="text-white">{r.margin_now_pct}%{r.margin_after_pct != null && <span className="text-[#A1E4DB]"> → {r.margin_after_pct}%</span>}</span>)}
                </td>
                <td className="p-2 text-end text-white">{fmt(r.units_30d, 0)}</td>
                <td className="p-2 text-end whitespace-nowrap">
                  {r.profit_change_30d != null ? <span className={r.profit_change_30d < 0 ? "text-[#EF4444]" : "text-[#10B981]"}>{r.profit_change_30d > 0 ? "+" : ""}{fmt(r.profit_change_30d, 0)}</span> : "—"}
                  {r.breakeven_extra_sales_pct != null && <span className="block text-[10px] text-[#A1E4DB]">{isRTL ? `يحتاج +${r.breakeven_extra_sales_pct}% مبيعات للتعادل` : `needs +${r.breakeven_extra_sales_pct}% sales to break even`}</span>}
                </td>
                <td className="p-2 text-[11px] text-[#A1E4DB] max-w-[240px]">{r.reason}</td>
                {canApply && (
                  <td className="p-2">
                    {sent[r.sku] ? <span className="text-[10px] text-[#10B981] inline-flex items-center gap-1"><Check className="w-3 h-3" />{sent[r.sku] === "confirmed" ? (isRTL ? "حُدّث" : "updated") : (isRTL ? "أُرسل" : "sent")}</span>
                      : r.recommended_price != null && (r.action === "lower" || r.action === "raise") && (
                        <button onClick={() => setConfirm(r)} className="h-7 px-2.5 rounded bg-[#1E988E] text-[#090E1C] text-[11px] font-semibold whitespace-nowrap" data-testid={`pricing-approve-${r.sku}`}>
                          {isRTL ? "اعتماد" : "Approve"}
                        </button>
                      )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 && <p className="p-4 text-xs text-[#A1E4DB]">{isRTL ? "لا توجد منتجات هنا." : "Nothing here."}</p>}
      </div>
      {rows.length > shown && <button className="text-xs text-[#6AC1B5] hover:text-white" onClick={() => setShown((n) => n + 50)}>{isRTL ? `عرض المزيد (${rows.length - shown})` : `Show more (${rows.length - shown})`}</button>}
      <p className="text-[10px] text-[#A1E4DB]/70">
        {isRTL ? "أثر الربح محسوب بنفس حجم المبيعات الحالي (دون نموذج طلب) وبالسعر قبل الضريبة. الأسعار تشمل ضريبة القيمة المضافة 15%، والتكلفة بدونها."
          : "Profit change is at today's sales volume (no demand model), on prices net of VAT. Prices include 15% VAT; costs exclude it."}
      </p>

      <div>
        <button className="text-[11px] text-[#A1E4DB] hover:text-white inline-flex items-center gap-1" onClick={() => setShowLog((v) => !v)} data-testid="pricing-changes-toggle">
          <History className="w-3.5 h-3.5" />{isRTL ? "سجل تغييرات الأسعار" : "Price change log"}
        </button>
        {showLog && (
          <div className="mt-2 glass-card rounded-md p-3 text-[11px] space-y-1" data-testid="pricing-changes">
            {(log.data || []).length === 0 ? <p className="text-[#A1E4DB]">{isRTL ? "لا تغييرات بعد." : "No changes yet."}</p> :
              log.data.map((c, i) => (
                <div key={i} className="flex flex-wrap gap-2 text-[#A1E4DB]">
                  <span>{new Date(c.at).toLocaleString(isRTL ? "ar-SA" : "en-GB")}</span>
                  <span className="text-white">{c.name_ar || c.sku}</span>
                  <span>{c.previous_shelf_price} → {c.requested_shelf_price}</span>
                  <span className={c.status === "confirmed" ? "text-[#10B981]" : "text-[#F59E0B]"}>{c.status}</span>
                  <span>{c.approved_by}</span>
                  {c.reason && <span className="text-[#F59E0B]">{String(c.reason).slice(0, 80)}</span>}
                </div>
              ))}
          </div>
        )}
      </div>

      <AlertDialog open={!!confirm} onOpenChange={(o) => { if (!o) setConfirm(null); }}>
        <AlertDialogContent className="bg-[#0A2728] border-white/10 text-white">
          <AlertDialogHeader>
            <AlertDialogTitle>{isRTL ? "تغيير السعر في متجرك؟" : "Change the price on your store?"}</AlertDialogTitle>
            <AlertDialogDescription className="text-[#A1E4DB]">
              {confirm && (isRTL
                ? `${confirm.name_ar}: من ${confirm.price} إلى ${confirm.recommended_price} ريال (شامل الضريبة). سيُرسل إلى زد ويظهر للعملاء فوراً.`
                : `${confirm.name_ar || confirm.name_en}: from ${confirm.price} to ${confirm.recommended_price} SAR (incl. VAT). This is sent to Zid and shoppers see it right away.`)}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{isRTL ? "إلغاء" : "Cancel"}</AlertDialogCancel>
            <AlertDialogAction onClick={apply} className="bg-[#1E988E] text-[#090E1C]" data-testid="pricing-approve-confirm">{isRTL ? "اعتماد وإرسال" : "Approve and send"}</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
