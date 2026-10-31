/**
 * Key brands (21 Oct 2026): every item of the client's key brands, in every
 * tracked store, with each store's latest price and stock — including the
 * items the own store does not sell yet.
 */
import { Fragment, useMemo, useState } from "react";
import { SectionTabs } from "@/components/SectionTabs";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { Star, ExternalLink, ImageOff, ShieldCheck, ChevronDown } from "lucide-react";
import DataTable from "@/components/DataTable";
import { useAuth } from "@/App";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { RequestError } from "@/components/RequestError";
import { StoreLogo } from "@/components/StoreLogo";
import { SkuLine } from "@/components/SkuLine";

const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const SHOW = [
  ["all", "All items", "كل المنتجات"],
  ["not_mine", "I don't sell", "لا أبيعها"],
  ["dearer", "I'm dearer", "سعري أعلى"],
  ["cheapest", "I'm cheapest", "أنا الأرخص"],
];

// Every store asked which key-brand items it lists; each checked against Daleel.
function CoverageCheck({ isRTL }) {
  const { user } = useAuth();
  const canRun = ["super_admin", "admin"].includes(user?.role);
  const [open, setOpen] = useState({});
  const q = useQuery({ queryKey: ["brands", "key", "audit"], queryFn: async () => (await api.get("/brands/key/audit")).data,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 15000 : false) });
  const run = async () => {
    try {
      const { data } = await api.post("/brands/key/audit");
      if (data.started) toast.success(isRTL ? "بدأ الفحص — يستغرق نحو 30–60 دقيقة" : "Check started — takes about 30–60 minutes");
      else toast.info(isRTL ? "الفحص يعمل بالفعل" : "A check is already running");
      q.refetch();
    } catch (e) { toast.error(e?.response?.data?.detail || "Failed"); }
  };
  const d = q.data;
  const rows = d?.stores || [];
  const pct = d?.store_lists ? Math.round((d.in_daleel / d.store_lists) * 1000) / 10 : 100;
  return (
    <div className="glass-card rounded-md p-4" data-testid="key-brands-coverage">
      <div className="flex flex-wrap items-center gap-3">
        <ShieldCheck className="w-4 h-4 text-[#1E988E]" />
        <h3 className="text-sm font-semibold text-white">{isRTL ? "فحص التغطية: هل كل منتج في المتاجر موجود في دليل؟" : "Coverage check: is every store item in Daleel?"}</h3>
        {d?.started_at && <span className="text-[10px] text-[#A1E4DB]">{d.status === "running" ? (isRTL ? "يعمل الآن… " : "running… ") : ""}{new Date(d.finished_at || d.started_at).toLocaleString(isRTL ? "ar-SA" : "en-GB", { dateStyle: "short", timeStyle: "short" })}</span>}
        {d?.status === "done" && <span className="text-xs text-white">{isRTL ? `المتاجر تعرض ${d.store_lists} · في دليل ${d.in_daleel}` : `stores list ${d.store_lists} · in Daleel ${d.in_daleel}`}
          <span className={d.store_lists - d.in_daleel ? " text-[#F59E0B]" : " text-[#10B981]"}> ({pct}%)</span></span>}
        {canRun && <button onClick={run} disabled={d?.status === "running"} className="ms-auto h-7 px-3 rounded bg-[#1E988E] text-[#090E1C] text-xs font-semibold disabled:opacity-50" data-testid="key-brands-audit-run">{isRTL ? "تشغيل الفحص" : "Run check"}</button>}
      </div>
      <p className="text-[11px] text-[#A1E4DB] mt-1">{isRTL ? "يسأل كل متجر عن منتجات هذه العلامات (صفحات العلامات والبحث في سلة، والقائمة الكاملة في زد) ويتحقق أن دليل قرأ كل منتج خلال آخر 7 أيام." : "Asks each store for its items of these brands (Salla brand pages and search; the full product list on Zid) and checks Daleel read each one in the last 7 days."}</p>
      {rows.length > 0 && (
        <div className="overflow-x-auto mt-3">
          <table className="w-full text-xs">
            <thead><tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">
              <th className="text-start p-2">{isRTL ? "المتجر" : "Store"}</th>
              <th className="text-end p-2">{isRTL ? "يعرض المتجر" : "Store lists"}</th>
              <th className="text-end p-2">{isRTL ? "في دليل" : "In Daleel"}</th>
              <th className="text-end p-2">{isRTL ? "ناقص" : "Missing"}</th>
              <th className="text-start p-2">{isRTL ? "ملاحظة" : "Note"}</th>
            </tr></thead>
            <tbody>
              {rows.map((s) => {
                const missing = Object.values(s.brands || {}).flatMap((b) => b.missing);
                return (
                  <Fragment key={s.store_id}>
                    <tr className="border-b border-white/5" data-testid={`audit-store-${s.store_id}`}>
                      <td className="p-2 text-white"><span className="inline-flex items-center gap-1.5"><StoreLogo storeId={s.store_id} name={s.store} size={14} />{s.store}</span></td>
                      <td className="p-2 text-end text-white">{s.checked ? s.store_lists : "—"}</td>
                      <td className="p-2 text-end text-white">{s.checked ? s.in_daleel : "—"}</td>
                      <td className="p-2 text-end">{!s.checked ? <span className="text-[#F59E0B]">{isRTL ? "لم يُفحص" : "not checked"}</span> : missing.length === 0 ? <span className="text-[#10B981]">0 ✓</span> :
                        <button className="text-[#F59E0B] inline-flex items-center gap-0.5" onClick={() => setOpen((o) => ({ ...o, [s.store_id]: !o[s.store_id] }))}>{missing.length}<ChevronDown className="w-3 h-3" /></button>}</td>
                      <td className="p-2 text-[10px] text-[#A1E4DB]">{s.note}</td>
                    </tr>
                    {open[s.store_id] && missing.length > 0 && (
                      <tr className="border-b border-white/5 bg-white/[0.02]"><td colSpan={5} className="p-2">
                        <div className="grid gap-1 text-[11px]">
                          {missing.map((m) => (
                            <div key={m.listing_id} className="flex flex-wrap items-center gap-2">
                              <span className="text-[#6AC1B5] w-24 shrink-0">{m.brand}</span>
                              <span className="text-white truncate max-w-[420px]">{m.name}</span>
                              {m.price != null && <span className="text-[#A1E4DB]">{m.price}</span>}
                              {m.url && <a href={m.url} target="_blank" rel="noopener noreferrer" className="text-[#6AC1B5]"><ExternalLink className="w-3 h-3" /></a>}
                              <span className="text-[10px] text-[#F59E0B]">{m.why === "never collected" ? (isRTL ? "لم يُجمع بعد" : "never collected") : (isRTL ? "قُرئ سابقاً، ليس هذا الأسبوع" : "seen before, not this week")}</span>
                            </div>))}
                        </div>
                      </td></tr>)}
                  </Fragment>);
              })}
            </tbody>
          </table>
        </div>)}
    </div>
  );
}

export default function KeyBrandsPage() {
  const { isRTL } = useI18n();
  const [brand, setBrand] = useState(null);
  const [show, setShow] = useState("all");
  const res = useQuery({ queryKey: ["brands", "key"], queryFn: async () => (await api.get("/brands/key", { timeout: 90000 })).data });
  const items = useMemo(() => {
    const all = res.data?.items || [];
    return all.filter((i) => (!brand || i.brand === brand)
      && (show !== "not_mine" || !i.own_sells)
      && (show !== "dearer" || (i.own_vs_cheapest_pct || 0) > 0)
      && (show !== "cheapest" || (i.own_vs_cheapest_pct != null && i.own_vs_cheapest_pct <= 0)));
  }, [res.data, brand, show]);
  const columns = useMemo(() => {
    const stores = [...new Map((res.data?.items || []).flatMap((i) => i.offers.map((o) => [o.store_id, o.store_name]))).entries()]
      .sort((a, b) => String(a[1]).localeCompare(String(b[1])));
    const offerOf = (i, sid) => i.offers.find((o) => o.store_id === sid);
    return [
      { id: "name", label: isRTL ? "المنتج" : "Product", type: "text", width: 300, always: true, get: (i) => [i.name_ar, i.name_en],
        render: (i) => (
          <div className="flex items-start gap-2">
            <div className="w-10 h-10 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
              {i.image_url ? <img src={i.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : <ImageOff className="w-4 h-4 text-gray-400" />}
            </div>
            <div className="min-w-0"><p className="text-white">{i.name_ar || i.name_en}</p>{i.name_en && i.name_ar && i.name_en !== i.name_ar && <p className="text-xs text-[#A1E4DB]">{i.name_en}</p>}</div>
          </div>) },
      { id: "brand", label: isRTL ? "العلامة" : "Brand", type: "enum", width: 130, options: (res.data?.brands || []).map((b) => b.brand) },
      { id: "barcode", label: isRTL ? "الباركود" : "Barcode", type: "text", width: 140, render: (i) => i.barcode ? <SkuLine sku={i.barcode} /> : "—" },
      { id: "own_sells", label: isRTL ? "أبيعه؟" : "I sell it", type: "enum", width: 100, options: [["true", isRTL ? "نعم" : "Yes"], ["false", isRTL ? "لا" : "No"]],
        get: (i) => String(i.own_sells), render: (i) => i.own_sells ? (isRTL ? "نعم" : "Yes") : <span className="text-[#F59E0B]">{isRTL ? "لا أبيعه" : "not sold by me"}</span> },
      { id: "own_price", label: isRTL ? "سعري (ريال)" : "My price (SAR)", type: "number", width: 110, align: "end", render: (i) => fmt(i.own_price) },
      { id: "own_in_stock", label: isRTL ? "مخزوني" : "My stock", type: "enum", width: 110, options: [["true", isRTL ? "متوفر" : "In stock"], ["false", isRTL ? "نفد" : "Out of stock"]],
        get: (i) => (i.own_sells ? String(i.own_in_stock) : null), render: (i) => !i.own_sells ? "—" : i.own_in_stock === false ? <span className="text-[#F59E0B]">{isRTL ? "نفد" : "out of stock"}</span> : i.own_in_stock ? (isRTL ? "متوفر" : "in stock") : (isRTL ? "غير معروف" : "unknown") },
      { id: "cheapest_price", label: isRTL ? "أرخص سعر متوفر (ريال)" : "Cheapest in stock (SAR)", type: "number", width: 120, align: "end", render: (i) => fmt(i.cheapest_price) },
      { id: "cheapest_store", label: isRTL ? "أرخص متجر" : "Cheapest store", type: "text", width: 130 },
      { id: "own_vs_cheapest_pct", label: isRTL ? "سعري مقابل الأرخص (%)" : "Me vs cheapest (%)", type: "number", width: 120, align: "end",
        render: (i) => i.own_vs_cheapest_pct == null ? "—" : <span className={i.own_vs_cheapest_pct > 0 ? "text-[#EF4444]" : "text-[#10B981]"}>{i.own_vs_cheapest_pct > 0 ? "+" : ""}{i.own_vs_cheapest_pct}%</span> },
      { id: "stores", label: isRTL ? "عدد المتاجر" : "Stores", type: "number", width: 90, align: "end" },
      { id: "competitors_in_stock", label: isRTL ? "منافسون متوفرون" : "Competitors in stock", type: "number", width: 110, align: "end" },
      { id: "offers", field: "offers.store_name", label: isRTL ? "كل المتاجر: السعر والمخزون" : "Every store: price and stock", type: "text", width: 360,
        get: (i) => i.offers.map((o) => o.store_name),
        exportValue: (i) => i.offers.map((o) => `${o.store_name} ${o.price ?? "—"} ${o.in_stock === false ? "OOS" : ""} ${o.match === "name" ? "(by name)" : ""}`.trim()),
        render: (i) => (
          <div className="flex flex-wrap gap-1">
            {i.offers.map((o) => (
              <a key={o.store_id} href={o.url || undefined} target="_blank" rel="noopener noreferrer" title={o.name} onClick={(e) => e.stopPropagation()}
                className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-xs ${o.own ? "bg-[#1E988E]/20 border border-[#1E988E]/40" : "bg-white/[0.04]"} ${o.in_stock === false ? "opacity-50" : ""}`}>
                <StoreLogo storeId={o.store_id} name={o.store_name} size={12} />
                <span className="text-white">{o.store_name}</span>
                <span className="text-white font-semibold">{fmt(o.price)}</span>
                {o.in_stock === false && <span className="text-[#F59E0B]">{isRTL ? "نفد" : "OOS"}</span>}
                {o.match === "name" && <span className="text-[#A1E4DB]" title={isRTL ? "رُبط بالاسم: نفس العلامة والحجم والعبوة والنكهة، والمتجر لا ينشر باركود" : "Linked by name: same brand, size, pack and flavour; this store publishes no barcode"}>{isRTL ? "بالاسم" : "by name"}</span>}
                {o.url && <ExternalLink className="w-2.5 h-2.5 text-[#6AC1B5]" />}
              </a>
            ))}
          </div>) },
      // One price column per store, for side-by-side comparison (Columns menu).
      ...stores.map(([sid, name]) => ({
        id: `store:${sid}`, label: isRTL ? `${name} (ريال)` : `${name} (SAR)`, type: "number", width: 110, align: "end", hidden: true,
        get: (i) => offerOf(i, sid)?.price,
        render: (i) => { const o = offerOf(i, sid); return !o ? "—" : <span className={o.in_stock === false ? "opacity-60" : ""}>{fmt(o.price)}{o.in_stock === false && <span className="block text-xs text-[#F59E0B]">{isRTL ? "نفد" : "OOS"}</span>}{o.match === "name" && <span className="block text-xs text-[#A1E4DB]" title={isRTL ? "رُبط بالاسم: نفس العلامة والحجم والعبوة والنكهة، والمتجر لا ينشر باركود" : "Linked by name: same brand, size, pack and flavour; this store publishes no barcode"}>{isRTL ? "بالاسم" : "by name"}</span>}</span>; },
      })),
    ];
  }, [res.data, isRTL]);
  if (res.isError) return <div className="p-6"><RequestError id="key-brands" error={res.error} onRetry={() => res.refetch()} /></div>;

  return (
    <div className="p-6 space-y-5" data-testid="key-brands-page">
      <SectionTabs section="market" />
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white inline-flex items-center gap-2"><Star className="w-6 h-6 text-[#1E988E]" />{isRTL ? "العلامات الرئيسية" : "Key brands"}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "كل منتج من هذه العلامات في كل المتاجر — بسعره ومخزونه في كل متجر" : "Every item of these brands in every store — with each store's price and stock"}</p>
          <p className="text-xs text-[#A1E4DB] mt-1">{isRTL
            ? "يُربط منتج المتجر بمنتجي بالباركود. إن لم ينشر المتجر باركود يُربط بالاسم فقط عندما تتطابق العلامة والحجم والعبوة وكل نكهة وعمر، ويظهر عليه «بالاسم». «لا أبيعه» تعني أن أياً من منتجاتي لا يطابقه بهذه القواعد (مثلاً كرتون وأنا أبيع الحبة)."
            : "A store's item is linked to mine by barcode. When the store publishes no barcode it is linked by name only when brand, size, pack and every flavour and age word agree, and is marked “by name”. “Not sold by me” means none of my products matches it by these rules (e.g. a carton when I sell the single)."}</p>
        </div>

      </div>

      <CoverageCheck isRTL={isRTL} />

      {!res.data ? <p className="text-sm text-[#A1E4DB]">{isRTL ? "جارٍ جمع منتجات العلامات من كل المتاجر… قد يستغرق دقيقة في أول مرة." : "Gathering every item of these brands from all stores… the first load can take a minute."}</p> : <>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2" data-testid="key-brands-cards">
          {res.data.brands.map((b) => (
            <button key={b.brand} onClick={() => setBrand(brand === b.brand ? null : b.brand)} data-testid={`key-brand-${b.brand}`}
              className={`glass-card rounded-md p-3 text-start transition ${brand === b.brand ? "ring-2 ring-[#1E988E]" : "hover:ring-1 hover:ring-white/20"}`}>
              <p className="text-sm font-semibold text-white">{b.brand}</p>
              <p className="text-xl font-bold text-white mt-1">{fmt(b.items, 0)} <span className="text-[10px] font-normal text-[#A1E4DB]">{isRTL ? "منتج" : "items"}</span></p>
              <p className="text-[10px] text-[#A1E4DB]">{isRTL ? `أبيع ${b.own_sells} · لا أبيع ${b.not_sold_by_me}` : `I sell ${b.own_sells} · not mine ${b.not_sold_by_me}`}</p>
              {(b.me_cheapest + b.me_dearer) > 0 && <p className="text-[10px]"><span className="text-[#10B981]">{isRTL ? `الأرخص ${b.me_cheapest}` : `cheapest ${b.me_cheapest}`}</span> · <span className="text-[#EF4444]">{isRTL ? `أعلى ${b.me_dearer}` : `dearer ${b.me_dearer}`}</span></p>}
            </button>
          ))}
        </div>

        {brand && (() => {
          const b = res.data.brands.find((x) => x.brand === brand);
          return (
            <div className="glass-card rounded-md p-3 text-[11px] flex flex-wrap gap-2" data-testid="key-brand-stores">
              <span className="text-[#A1E4DB]">{isRTL ? `${brand} في كل متجر:` : `${brand} per store:`}</span>
              {Object.entries(b.per_store).map(([s, n]) => <span key={s} className="px-2 py-0.5 rounded bg-white/5 text-white">{s} <span className="text-[#A1E4DB]">{n}</span></span>)}
            </div>);
        })()}

        <div className="flex flex-wrap items-center gap-2">
          {SHOW.map(([id, en, ar]) => (
            <button key={id} onClick={() => setShow(id)} className={`h-8 px-3 rounded-full text-xs ${show === id ? "bg-[#1E988E] text-[#090E1C] font-semibold" : "bg-white/5 text-[#A1E4DB] hover:text-white"}`}>{isRTL ? ar : en}</button>
          ))}
        </div>

        <DataTable columns={columns} rows={items} storageKey="key-brands" exportName="daleel-key-brands"
          rowKey={(i) => i.key} initialSort={{ id: "stores", dir: "desc" }} />

        <p className="text-[10px] text-[#A1E4DB]/70">
          {isRTL ? `آخر قراءة لكل متجر خلال ${res.data.window_days} أيام، مجمعة بالباركود. الأسعار شاملة الضريبة. يُحدَّث كل 30 دقيقة.`
            : `Each store's latest reading in the last ${res.data.window_days} days, grouped by barcode. Prices include VAT. Refreshed every 30 minutes.`}
        </p>
      </>}
    </div>
  );
}
