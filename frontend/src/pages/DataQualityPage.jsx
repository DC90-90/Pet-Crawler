/**
 * Data quality (17 Oct 2026): what Daleel can see in each store, and product
 * matches that need a decision. Every number elsewhere rests on these.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { ShieldCheck, ExternalLink, Check, X } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { useReleaseActions } from "@/lib/releaseActions";
import { RequestError } from "@/components/RequestError";
import { StoreLogo } from "@/components/StoreLogo";
import { SkuLine } from "@/components/SkuLine";

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());
const STATUS_TONE = { complete: "#10B981", done: "#10B981", partial: "#F59E0B", cut_off_by_restart: "#EF4444", failed: "#EF4444", running: "#6AC1B5" };
const REASONS = {
  own_price_far_below_market: ["Your price is far below every seller — maybe a single item vs a pack, or a wrong barcode", "سعرك أقل بكثير من كل البائعين — ربما قطعة مقابل عبوة أو باركود خاطئ"],
  own_price_far_above_market: ["Your price is far above every seller — maybe a pack vs a single item, or a wrong barcode", "سعرك أعلى بكثير من كل البائعين — ربما عبوة مقابل قطعة أو باركود خاطئ"],
  same_barcode_other_size: ["Competitors list your barcode with a different size — one listing or the barcode is wrong, so it is not compared. Confirm \"Same product\" only if the sizes really match.", "المنافسون يعرضون نفس الباركود بحجم مختلف — إحدى القوائم أو الباركود خاطئ، لذلك لا تتم المقارنة. اختر \"صحيح\" فقط إذا تطابق الحجم فعلاً."],
};

function Coverage({ isRTL }) {
  const q = useQuery({ queryKey: ["dq", "coverage"], queryFn: async () => (await api.get("/data-quality/coverage")).data });
  if (q.isError) return <RequestError id="dq-coverage" error={q.error} onRetry={() => q.refetch()} />;
  const rows = q.data?.stores || [];
  return (
    <div className="glass-card rounded-md p-5" data-testid="dq-coverage">
      <h3 className="text-sm font-semibold text-white mb-1">{isRTL ? "ما يراه دليل في كل متجر" : "What Daleel sees in each store"}</h3>
      <p className="text-[11px] text-[#A1E4DB] mb-3">{isRTL ? "آخر زحف، عدد المنتجات المحفوظة، الصور، وهل مبيعات المتجر قابلة للقياس." : "Last crawl, products saved, images, and whether the store's sales can be measured."}</p>
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">…</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">
                <th className="text-start p-2">{isRTL ? "المتجر" : "Store"}</th>
                <th className="text-end p-2">{isRTL ? "منتجات" : "Products"}</th>
                <th className="text-end p-2">{isRTL ? "صور" : "Images"}</th>
                <th className="text-start p-2">{isRTL ? "آخر زحف" : "Last crawl"}</th>
                <th className="text-start p-2">{isRTL ? "آخر 7 أيام" : "Last 7 days"}</th>
                <th className="text-start p-2">{isRTL ? "قياس المبيعات (30 يوماً)" : "Sales measured (30 days)"}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.store_id} className={`border-b border-white/5 ${s.active ? "" : "opacity-50"}`} data-testid={`dq-store-${s.store_id}`}>
                  <td className="p-2"><span className="inline-flex items-center gap-1.5 text-white"><StoreLogo storeId={s.store_id} name={s.name} size={18} />{s.name}</span>
                    <span className="ms-2 text-[10px] text-[#A1E4DB] uppercase">{s.platform}</span>{!s.active && <span className="ms-2 text-[10px] text-[#F59E0B]">{isRTL ? "متوقف" : "paused"}</span>}</td>
                  <td className="p-2 text-end text-white">{fmt(s.products)}</td>
                  <td className="p-2 text-end text-[#A1E4DB]">{s.image_pct == null ? "—" : `${s.image_pct}%`}</td>
                  <td className="p-2">{s.last_crawl ? (
                    <span><span style={{ color: STATUS_TONE[s.last_crawl.status] || "#A1E4DB" }}>{s.last_crawl.status}</span>
                      <span className="text-[#A1E4DB]"> · {new Date(s.last_crawl.at).toLocaleString(isRTL ? "ar-SA" : "en-GB", { dateStyle: "short", timeStyle: "short" })}</span>
                      {s.last_crawl.found != null && <span className="block text-[10px] text-[#A1E4DB]">{isRTL ? `وُجد ${fmt(s.last_crawl.found)} · حُفظ ${fmt(s.last_crawl.saved)}` : `found ${fmt(s.last_crawl.found)} · saved ${fmt(s.last_crawl.saved)}`}</span>}
                    </span>) : <span className="text-[#A1E4DB]">—</span>}</td>
                  <td className="p-2 text-[11px] text-[#A1E4DB]">
                    <span className="text-[#10B981]">{s.crawls_7d.complete} ✓</span>{s.crawls_7d.partial > 0 && <span className="text-[#F59E0B]"> · {s.crawls_7d.partial} {isRTL ? "جزئي" : "partial"}</span>}
                    {s.crawls_7d.cut_off > 0 && <span className="text-[#EF4444]"> · {s.crawls_7d.cut_off} {isRTL ? "مقطوع" : "cut off"}</span>}
                    {s.crawls_7d.failed > 0 && <span className="text-[#EF4444]"> · {s.crawls_7d.failed} {isRTL ? "فشل" : "failed"}</span>}
                  </td>
                  <td className="p-2 text-[11px]">
                    <span className={s.sales_measured_days_30 ? "text-white" : "text-[#A1E4DB]"}>{s.sales_measured_days_30 ? `${s.sales_measured_days_30}/30` : (isRTL ? "غير قابلة للقياس" : "not measurable")}</span>
                    <span className="block text-[10px] text-[#A1E4DB]">{s.sales_method === "stock levels" ? (isRTL ? "من مستويات المخزون" : "from stock levels") : s.sales_method === "public sold counter" ? (isRTL ? "من عدّاد المبيعات العام" : "from the public sold counter") : (isRTL ? "المتجر لا ينشر المخزون ولا المبيعات" : "the store publishes neither stock nor sales")}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Matches({ isRTL }) {
  const { canEdit } = useReleaseActions();
  const [done, setDone] = useState({});
  const [shown, setShown] = useState(20);
  const q = useQuery({ queryKey: ["dq", "matches"], queryFn: async () => (await api.get("/data-quality/matches", { timeout: 60000 })).data });
  if (q.isError) return <RequestError id="dq-matches" error={q.error} onRetry={() => q.refetch()} />;
  const rows = (q.data?.rows || []).filter((r) => !done[r.sku]);
  const decide = async (r, o, ok) => {
    try {
      await api.post(ok ? "/price-intel/confirm-match" : "/price-intel/reject-match",
        { my_sku: r.sku, competitor_sku: o.sku, competitor_store_id: o.store_id, competitor_offer_id: o.offer_id });
      toast.success(ok ? (isRTL ? "تم تأكيد المطابقة" : "Match confirmed") : (isRTL ? "تم رفض المطابقة ولن تُستخدم" : "Match rejected — it won't be used again"));
      if (ok) setDone((d) => ({ ...d, [r.sku]: true }));
      else q.refetch();
    } catch { toast.error(isRTL ? "تعذر الحفظ" : "Could not save"); }
  };
  return (
    <div className="glass-card rounded-md p-5" data-testid="dq-matches">
      <h3 className="text-sm font-semibold text-white mb-1">{isRTL ? "مطابقات تحتاج قراراً" : "Matches that need a decision"} {q.data && <span className="text-[#A1E4DB] font-normal">({rows.length})</span>}</h3>
      <p className="text-[11px] text-[#A1E4DB] mb-3">{isRTL ? "منتجات سعرها بعيد عن كل البائعين بنفس الباركود، أو أسعار بائعيها متفاوتة جداً. ارفض العرض الخاطئ ليُستبعد من كل المقارنات." : "Products whose price is far from every seller with the same barcode, or whose sellers' prices differ a lot. Reject a wrong offer and it leaves every comparison."}</p>
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">…</p> : rows.length === 0 ? <p className="text-xs text-[#A1E4DB]">{isRTL ? "لا شيء للمراجعة." : "Nothing to review."}</p> : (
        <div className="space-y-3">
          {rows.slice(0, shown).map((r) => (
            <div key={r.sku} className="rounded border border-white/10 p-3" data-testid={`dq-match-${r.sku}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm text-white">{r.name_ar || r.name_en}</p>
                  <SkuLine sku={r.sku} barcode={r.barcode} />
                  <p className="text-[11px] text-[#F59E0B] mt-1">{REASONS[r.reason]?.[isRTL ? 1 : 0] || (isRTL ? "أسعار البائعين متفاوتة جداً" : "Sellers' prices differ a lot")}</p>
                </div>
                <div className="text-end shrink-0"><p className="text-[10px] text-[#A1E4DB]">{isRTL ? "سعري" : "My price"}</p><p className="text-sm font-bold text-white">{r.my_price} SAR</p></div>
              </div>
              <div className="mt-2 space-y-1">
                {r.offers.map((o) => (
                  <div key={o.offer_id || o.sku} className="flex flex-wrap items-center gap-2 text-[11px] bg-white/[0.03] rounded px-2 py-1">
                    <StoreLogo storeId={o.store_id} name={o.store_name} size={14} />
                    <span className="text-white">{o.store_name}</span>
                    <span className="text-[#A1E4DB] truncate max-w-[300px]">{o.name}</span>
                    {o.url && <a href={o.url} target="_blank" rel="noopener noreferrer" className="text-[#6AC1B5]"><ExternalLink className="w-3 h-3" /></a>}
                    <span className="ms-auto text-white">{o.price} SAR <span className="text-[#A1E4DB]">(×{o.ratio_to_mine})</span></span>
                    {canEdit && <>
                      <button onClick={() => decide(r, o, true)} className="h-6 px-2 rounded bg-[#10B981]/20 text-[#10B981] inline-flex items-center gap-1"><Check className="w-3 h-3" />{isRTL ? "صحيح" : "Same product"}</button>
                      <button onClick={() => decide(r, o, false)} className="h-6 px-2 rounded bg-[#EF4444]/20 text-[#EF4444] inline-flex items-center gap-1"><X className="w-3 h-3" />{isRTL ? "مختلف" : "Different"}</button>
                    </>}
                  </div>
                ))}
              </div>
            </div>
          ))}
          {rows.length > shown && <button className="text-xs text-[#6AC1B5]" onClick={() => setShown((n) => n + 20)}>{isRTL ? "عرض المزيد" : "Show more"}</button>}
        </div>
      )}
    </div>
  );
}

export default function DataQualityPage() {
  const { isRTL } = useI18n();
  return (
    <div className="p-6 space-y-5" data-testid="data-quality-page">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white inline-flex items-center gap-2"><ShieldCheck className="w-6 h-6 text-[#1E988E]" />{isRTL ? "جودة البيانات" : "Data quality"}</h1>
        <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "على ماذا تستند كل الأرقام في دليل" : "What every number in Daleel rests on"}</p>
      </div>
      <Coverage isRTL={isRTL} />
      <Matches isRTL={isRTL} />
    </div>
  );
}
