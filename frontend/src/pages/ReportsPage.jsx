/**
 * Reports (17 Oct 2026): the daily brief and the weekly report Daleel builds
 * each morning from sealed facts — the same content as the email — plus who
 * receives them. Print / save as PDF from the browser.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileText, Printer, Mail, RefreshCw } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/App";
import { RequestError } from "@/components/RequestError";

const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));

function Section({ title, count, headers, rows }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div className="mb-5 break-inside-avoid">
      <h3 className="text-sm font-semibold text-white mb-1.5">{title}{count ? <span className="text-[#A1E4DB] font-normal"> ({count})</span> : null}</h3>
      <table className="w-full text-xs">
        <thead><tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">{headers.map((h) => <th key={h} className="text-start p-1.5">{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i} className="border-b border-white/5">{r.map((c, j) => <td key={j} className="p-1.5 text-white">{c ?? "—"}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function Daily({ r, isRTL }) {
  const t = (en, ar) => (isRTL ? ar : en);
  const move = (x) => [x.name_ar, x.store_name, fmt(x.old_price, 2), fmt(x.new_price, 2), `${x.change_pct}%`, fmt(x.my_price, 2)];
  const mh = [t("Product", "المنتج"), t("Store", "المتجر"), t("Was", "قبل"), t("Now", "الآن"), "%", t("My price", "سعري")];
  return (
    <>
      <p className="text-xs text-[#A1E4DB] mb-4">{t(`Changes on ${r.day} for the products you sell`, `تغيّرات يوم ${r.day} على منتجاتك`)}</p>
      <Section title={t("Competitors cut prices", "خفّض منافسون أسعارهم")} count={r.counts?.price_cuts} headers={mh} rows={(r.price_cuts || []).map(move)} />
      <Section title={t("Competitors raised prices", "رفع منافسون أسعارهم")} count={r.counts?.price_rises} headers={mh} rows={(r.price_rises || []).map(move)} />
      <Section title={t("Competitors ran out (your chance)", "نفد لدى منافس (فرصتك)")} count={r.counts?.went_out}
        headers={[t("Product", "المنتج"), t("Store", "المتجر"), t("My stock", "مخزوني")]} rows={(r.went_out || []).map((x) => [x.name_ar, x.store_name, fmt(x.my_quantity)])} />
      <Section title={t("Back in stock at competitors", "عاد للتوفر لدى منافس")} count={r.counts?.came_back}
        headers={[t("Product", "المنتج"), t("Store", "المتجر"), t("Price", "السعر")]} rows={(r.came_back || []).map((x) => [x.name_ar, x.store_name, fmt(x.price, 2)])} />
      <Section title={t("Mine: runs out before restock", "منتجاتي التي ستنفد قبل التوريد")}
        headers={[t("Product", "المنتج"), t("Stock", "المخزون"), t("Days left", "يكفي"), t("Reorder", "اطلب")]} rows={(r.running_out || []).map((x) => [x.name_ar, fmt(x.quantity), fmt(x.days_of_cover, 1), fmt(x.reorder_qty)])} />
      <Section title={t("Out at mine, competitors sold it", "نفد لديّ وباعه المنافسون")}
        headers={[t("Product", "المنتج"), t("Days out", "أيام النفاد"), t("Competitors sold (SAR)", "باع المنافسون (ريال)")]} rows={(r.missed_while_out || []).map((x) => [x.name_ar, x.oos_days, fmt(x.competitor_revenue_while_oos)])} />
      <Section title={t("Raise and stay cheapest", "ارفع السعر وابقَ الأرخص")}
        headers={[t("Product", "المنتج"), t("Price", "سعري"), t("Suggested", "المقترح"), t("Profit 30d", "ربح 30 يوماً")]} rows={(r.raise_now || []).map((x) => [x.name_ar, fmt(x.price, 2), fmt(x.recommended_price, 2), fmt(x.profit_change_30d)])} />
      {r.new_products && Object.keys(r.new_products).length > 0 && (
        <p className="text-xs text-[#A1E4DB]">{t("New products at competitors: ", "منتجات جديدة لدى المنافسين: ")}{Object.entries(r.new_products).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
      )}
    </>
  );
}

function Weekly({ r, isRTL }) {
  const t = (en, ar) => (isRTL ? ar : en);
  return (
    <>
      <p className="text-xs text-[#A1E4DB] mb-4">{r.from} → {r.to}</p>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {[[t("My revenue (7 days)", "إيراداتي (7 أيام)"), r.my_revenue != null ? `${fmt(r.my_revenue)} SAR` : "—", r.my_change_pct != null ? `${r.my_change_pct > 0 ? "+" : ""}${r.my_change_pct}% ${t("vs previous week", "عن الأسبوع السابق")}` : ""],
          [t("My rank", "ترتيبي"), r.my_rank ? `#${r.my_rank} / ${r.stores_ranked}` : "—", t("stores with measurable sales", "متاجر قابلة للقياس")],
          [t("Price moves", "تحركات السعر"), r.pricing ? `${r.pricing.by_action?.lower || 0} ↓  ${r.pricing.by_action?.raise || 0} ↑` : "—", r.pricing ? t(`+${fmt(r.pricing.raise_profit_30d)} SAR from raises (30d)`, `+${fmt(r.pricing.raise_profit_30d)} ريال من الرفع (30 يوماً)`) : ""],
          [t("Sold by competitors while I was out", "باعه المنافسون أثناء نفاده لديّ"), r.stock ? `${fmt(r.stock.competitor_revenue_while_oos)} SAR` : "—", r.stock ? t(`${r.stock.reorder_products} products to reorder`, `${r.stock.reorder_products} منتجاً يحتاج طلباً`) : ""],
        ].map(([label, value, sub]) => (
          <div key={label} className="kpi-card !p-3"><p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p><p className="text-lg font-bold text-white mt-0.5">{value}</p><p className="text-[10px] text-[#A1E4DB]">{sub}</p></div>
        ))}
      </div>
      <Section title={t("Store ranking (7 days)", "ترتيب المتاجر (7 أيام)")} headers={[t("Store", "المتجر"), t("Revenue", "الإيرادات"), t("Previous week", "الأسبوع السابق"), "%"]}
        rows={(r.ranking || []).map((x) => [x.own ? `★ ${x.store}` : x.store, fmt(x.revenue), fmt(x.previous), x.change_pct != null ? `${x.change_pct}%` : "—"])} />
      <Section title={t("Competitor campaigns", "حملات المنافسين")} headers={[t("Store", "المتجر"), t("From", "من"), t("To", "إلى"), t("Peak on sale", "ذروة المخفّض"), t("Avg discount", "متوسط الخصم")]}
        rows={(r.campaigns || []).map((c) => [c.store, c.start, c.end, `${c.peak_share_pct}%`, `${c.avg_discount_pct}%`])} />
      <Section title={t("Data coverage", "تغطية البيانات")} headers={[t("Store", "المتجر"), t("Products", "منتجات"), t("Sales measured (30d)", "قياس المبيعات (30 يوماً)"), t("Last crawl", "آخر زحف")]}
        rows={(r.coverage || []).filter((c) => c.active).map((c) => [c.name, fmt(c.products), c.sales_measured_days_30 ? `${c.sales_measured_days_30}/30` : t("not measurable", "غير قابلة للقياس"), c.last_crawl?.status || "—"])} />
    </>
  );
}

function Delivery({ isRTL }) {
  const t = (en, ar) => (isRTL ? ar : en);
  const q = useQuery({ queryKey: ["notifications", "settings"], queryFn: async () => (await api.get("/notifications/settings")).data });
  const [form, setForm] = useState(null);
  useEffect(() => { if (q.data) setForm({ ...q.data, daily_recipients: (q.data.daily_recipients || []).join(", "), weekly_recipients: (q.data.weekly_recipients || []).join(", ") }); }, [q.data]);
  if (!form) return null;
  const split = (s) => s.split(/[,\s;]+/).map((x) => x.trim()).filter(Boolean);
  const save = async () => {
    try {
      await api.put("/notifications/settings", { daily_enabled: form.daily_enabled, weekly_enabled: form.weekly_enabled,
        daily_recipients: split(form.daily_recipients), weekly_recipients: split(form.weekly_recipients) });
      toast.success(t("Delivery saved", "تم حفظ الإرسال")); q.refetch();
    } catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };
  const test = async (kind) => {
    try {
      const { data } = await api.post("/notifications/test", null, { params: { kind }, timeout: 120000 });
      if (data.status === "sent") toast.success(t("Test email sent", "أُرسل بريد الاختبار"));
      else toast.error(data.status === "not_configured" ? t("Email is not set up on the server yet", "البريد غير مُعد على الخادم بعد") : `${data.status}`);
    } catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };
  return (
    <div className="glass-card rounded-md p-4 space-y-3 print:hidden" data-testid="report-delivery">
      <h3 className="text-sm font-semibold text-white inline-flex items-center gap-2"><Mail className="w-4 h-4 text-[#1E988E]" />{t("Email delivery", "الإرسال بالبريد")}</h3>
      {!form.email_configured && <p className="text-[11px] text-[#F59E0B]">{t("Email isn't set up on the server yet (Resend key and sender). Reports are still built every morning and shown here.", "البريد غير مُعد على الخادم بعد (مفتاح Resend والمرسل). تُبنى التقارير كل صباح وتظهر هنا.")}</p>}
      {[["daily", t("Daily brief — every day 09:00", "الموجز اليومي — يومياً 09:00")], ["weekly", t("Weekly report — Sunday 09:15", "التقرير الأسبوعي — الأحد 09:15")]].map(([k, label]) => (
        <div key={k} className="flex flex-wrap items-center gap-3 text-xs">
          <label className="inline-flex items-center gap-2 text-white min-w-[230px]"><input type="checkbox" checked={!!form[`${k}_enabled`]} onChange={(e) => setForm({ ...form, [`${k}_enabled`]: e.target.checked })} />{label}</label>
          <input value={form[`${k}_recipients`]} onChange={(e) => setForm({ ...form, [`${k}_recipients`]: e.target.value })} placeholder={t("emails, separated by commas", "عناوين بريد مفصولة بفواصل")}
            className="flex-1 min-w-[220px] h-7 px-2 rounded bg-[#0A2728] border border-[#13625F] text-white" />
          <button onClick={() => test(k)} className="h-7 px-2 rounded bg-white/5 text-[#A1E4DB] hover:text-white">{t("Send test", "إرسال اختبار")}</button>
        </div>
      ))}
      <button onClick={save} className="h-7 px-3 rounded bg-[#1E988E] text-[#090E1C] text-xs font-semibold">{t("Save", "حفظ")}</button>
    </div>
  );
}

export default function ReportsPage() {
  const { isRTL } = useI18n();
  const { user } = useAuth();
  const isAdmin = ["super_admin", "admin"].includes(user?.role);
  const [kind, setKind] = useState("daily");
  const q = useQuery({ queryKey: ["reports", kind], queryFn: async () => (await api.get("/reports/latest", { params: { kind }, timeout: 120000 })).data });
  const rebuild = async () => {
    try { await api.post("/reports/rebuild", null, { params: { kind }, timeout: 180000 }); q.refetch(); toast.success(isRTL ? "تم تحديث التقرير" : "Report rebuilt"); }
    catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };
  return (
    <div className="p-6 space-y-5" data-testid="reports-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white inline-flex items-center gap-2"><FileText className="w-6 h-6 text-[#1E988E]" />{isRTL ? "التقارير" : "Reports"}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "يُبنى كل صباح من بيانات الأيام المكتملة" : "Built every morning from complete days"}</p>
        </div>
        <div className="flex gap-2 print:hidden">
          {isAdmin && <button onClick={rebuild} className="h-8 px-3 rounded-full border border-white/10 text-xs text-white inline-flex items-center gap-1.5"><RefreshCw className="w-3.5 h-3.5" />{isRTL ? "تحديث" : "Rebuild"}</button>}
          <button onClick={() => window.print()} className="h-8 px-3 rounded-full border border-white/10 text-xs text-white inline-flex items-center gap-1.5" data-testid="report-print"><Printer className="w-3.5 h-3.5" />{isRTL ? "طباعة / PDF" : "Print / save as PDF"}</button>
        </div>
      </div>
      <div className="flex gap-1 glass-card p-1.5 w-fit print:hidden">
        {[["daily", isRTL ? "الموجز اليومي" : "Daily brief"], ["weekly", isRTL ? "التقرير الأسبوعي" : "Weekly report"]].map(([id, label]) => (
          <button key={id} onClick={() => setKind(id)} className={`px-4 py-2 rounded-lg text-sm font-medium ${kind === id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:text-white"}`} data-testid={`report-tab-${id}`}>{label}</button>
        ))}
      </div>
      {q.isError ? <RequestError id="reports-request" error={q.error} onRetry={() => q.refetch()} /> : !q.data ? (
        <p className="text-sm text-[#A1E4DB]">{isRTL ? "جارٍ بناء التقرير…" : "Building the report…"}</p>
      ) : (
        <div className="glass-card rounded-md p-5" data-testid={`report-${kind}`}>
          {kind === "daily" ? <Daily r={q.data.report} isRTL={isRTL} /> : <Weekly r={q.data.report} isRTL={isRTL} />}
          <p className="text-[10px] text-[#A1E4DB]/70 mt-3">{isRTL ? "الإيرادات تقديرية من التغير اليومي في المخزون أو عدّاد المبيعات العام، وليست فواتير." : "Revenue is estimated from day-to-day stock changes or the public sold counter, not from invoices."}</p>
        </div>
      )}
      {isAdmin && <Delivery isRTL={isRTL} />}
    </div>
  );
}
