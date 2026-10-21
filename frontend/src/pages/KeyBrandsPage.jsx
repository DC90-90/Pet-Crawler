/**
 * Key brands (21 Oct 2026): every item of the client's key brands, in every
 * tracked store, with each store's latest price and stock — including the
 * items the own store does not sell yet.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Star, ExternalLink, ImageOff, Download, Search } from "lucide-react";
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

function csv(items) {
  const stores = [...new Set(items.flatMap((i) => i.offers.map((o) => o.store_name)))].sort();
  const head = ["brand", "barcode", "name", "my_price", "cheapest_price", "cheapest_store", "vs_cheapest_pct", ...stores.flatMap((s) => [`${s} price`, `${s} in stock`])];
  const esc = (v) => (v == null ? "" : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const lines = items.map((i) => {
    const by = Object.fromEntries(i.offers.map((o) => [o.store_name, o]));
    return [i.brand, i.barcode, i.name_ar || i.name_en, i.own_price, i.cheapest_price, i.cheapest_store, i.own_vs_cheapest_pct,
      ...stores.flatMap((s) => [by[s]?.price, by[s] ? (by[s].in_stock ? "yes" : "no") : ""])].map(esc).join(",");
  });
  const blob = new Blob(["﻿" + [head.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `daleel-key-brands-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function KeyBrandsPage() {
  const { isRTL } = useI18n();
  const [brand, setBrand] = useState(null);
  const [show, setShow] = useState("all");
  const [q, setQ] = useState("");
  const [shown, setShown] = useState(60);
  const res = useQuery({ queryKey: ["brands", "key"], queryFn: async () => (await api.get("/brands/key", { timeout: 90000 })).data });
  const items = useMemo(() => {
    const all = res.data?.items || [];
    const s = q.trim().toLowerCase();
    return all.filter((i) => (!brand || i.brand === brand)
      && (show !== "not_mine" || !i.own_sells)
      && (show !== "dearer" || (i.own_vs_cheapest_pct || 0) > 0)
      && (show !== "cheapest" || (i.own_vs_cheapest_pct != null && i.own_vs_cheapest_pct <= 0))
      && (!s || `${i.name_ar || ""} ${i.name_en || ""} ${i.barcode || ""}`.toLowerCase().includes(s)));
  }, [res.data, brand, show, q]);
  if (res.isError) return <div className="p-6"><RequestError id="key-brands" error={res.error} onRetry={() => res.refetch()} /></div>;

  return (
    <div className="p-6 space-y-5" data-testid="key-brands-page">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white inline-flex items-center gap-2"><Star className="w-6 h-6 text-[#1E988E]" />{isRTL ? "العلامات الرئيسية" : "Key brands"}</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "كل منتج من هذه العلامات في كل المتاجر — بسعره ومخزونه في كل متجر" : "Every item of these brands in every store — with each store's price and stock"}</p>
        </div>
        {res.data && <button onClick={() => csv(items)} className="h-8 px-3 rounded bg-white/5 text-[#A1E4DB] hover:text-white text-xs inline-flex items-center gap-1.5" data-testid="key-brands-export">
          <Download className="w-3.5 h-3.5" />{isRTL ? `تصدير (${items.length})` : `Export (${items.length})`}</button>}
      </div>

      {!res.data ? <p className="text-sm text-[#A1E4DB]">{isRTL ? "جارٍ جمع منتجات العلامات من كل المتاجر… قد يستغرق دقيقة في أول مرة." : "Gathering every item of these brands from all stores… the first load can take a minute."}</p> : <>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 gap-2" data-testid="key-brands-cards">
          {res.data.brands.map((b) => (
            <button key={b.brand} onClick={() => { setBrand(brand === b.brand ? null : b.brand); setShown(60); }} data-testid={`key-brand-${b.brand}`}
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
            <button key={id} onClick={() => { setShow(id); setShown(60); }} className={`h-8 px-3 rounded-full text-xs ${show === id ? "bg-[#1E988E] text-[#090E1C] font-semibold" : "bg-white/5 text-[#A1E4DB] hover:text-white"}`}>{isRTL ? ar : en}</button>
          ))}
          <div className="relative ms-auto">
            <Search className="w-3.5 h-3.5 absolute top-2 start-2 text-[#A1E4DB]" />
            <input value={q} onChange={(e) => { setQ(e.target.value); setShown(60); }} placeholder={isRTL ? "بحث بالاسم أو الباركود" : "Search name or barcode"}
              className="h-8 w-60 ps-7 pe-2 rounded bg-[#0A2728] border border-[#13625F] text-white text-xs" data-testid="key-brands-search" />
          </div>
        </div>

        <div className="glass-card rounded-md overflow-x-auto">
          <table className="w-full text-xs" data-testid="key-brands-table">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">
                <th className="text-start p-2">{isRTL ? "المنتج" : "Product"}</th>
                <th className="text-end p-2">{isRTL ? "سعري" : "My price"}</th>
                <th className="text-end p-2">{isRTL ? "الأرخص (متوفر)" : "Cheapest in stock"}</th>
                <th className="text-start p-2">{isRTL ? "كل المتاجر" : "Every store"}</th>
              </tr>
            </thead>
            <tbody>
              {items.slice(0, shown).map((i) => (
                <tr key={i.key} className="border-b border-white/5 align-top" data-testid={`key-item-${i.key}`}>
                  <td className="p-2">
                    <div className="flex items-center gap-2">
                      <div className="w-10 h-10 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
                        {i.image_url ? <img src={i.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : <ImageOff className="w-4 h-4 text-gray-400" />}
                      </div>
                      <div className="min-w-0">
                        <p className="text-white max-w-[300px] truncate" title={i.name_ar || i.name_en}>{i.name_ar || i.name_en}</p>
                        <p className="text-[10px] text-[#6AC1B5]">{i.brand}</p>
                        {i.barcode && <SkuLine sku={i.barcode} />}
                      </div>
                    </div>
                  </td>
                  <td className="p-2 text-end whitespace-nowrap">
                    {i.own_sells ? <>
                      <span className="text-white font-semibold">{fmt(i.own_price)}</span>
                      {i.own_in_stock === false && <span className="block text-[10px] text-[#F59E0B]">{isRTL ? "نفد عندي" : "out of stock"}</span>}
                      {i.own_vs_cheapest_pct != null && <span className={`block text-[10px] ${i.own_vs_cheapest_pct > 0 ? "text-[#EF4444]" : "text-[#10B981]"}`}>{i.own_vs_cheapest_pct > 0 ? "+" : ""}{i.own_vs_cheapest_pct}%</span>}
                    </> : <span className="text-[10px] text-[#F59E0B]">{isRTL ? "لا أبيعه" : "not sold by me"}</span>}
                  </td>
                  <td className="p-2 text-end whitespace-nowrap">
                    <span className="text-white">{fmt(i.cheapest_price)}</span>
                    {i.cheapest_store && <span className="block text-[10px] text-[#A1E4DB]">{i.cheapest_store}</span>}
                  </td>
                  <td className="p-2">
                    <div className="flex flex-wrap gap-1">
                      {i.offers.map((o) => (
                        <a key={o.store_id} href={o.url || undefined} target="_blank" rel="noopener noreferrer" title={o.name}
                          className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] ${o.own ? "bg-[#1E988E]/20 border border-[#1E988E]/40" : "bg-white/[0.04]"} ${o.in_stock === false ? "opacity-50" : ""}`}>
                          <StoreLogo storeId={o.store_id} name={o.store_name} size={12} />
                          <span className="text-white">{o.store_name}</span>
                          <span className="text-white font-semibold">{fmt(o.price)}</span>
                          {o.in_stock === false && <span className="text-[#F59E0B]">{isRTL ? "نفد" : "OOS"}</span>}
                          {o.url && <ExternalLink className="w-2.5 h-2.5 text-[#6AC1B5]" />}
                        </a>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {items.length === 0 && <p className="p-4 text-xs text-[#A1E4DB]">{isRTL ? "لا توجد منتجات." : "Nothing here."}</p>}
        </div>
        {items.length > shown && <button className="text-xs text-[#6AC1B5] hover:text-white" onClick={() => setShown((n) => n + 60)}>{isRTL ? `عرض المزيد (${items.length - shown})` : `Show more (${items.length - shown})`}</button>}
        <p className="text-[10px] text-[#A1E4DB]/70">
          {isRTL ? `آخر قراءة لكل متجر خلال ${res.data.window_days} أيام، مجمعة بالباركود. الأسعار شاملة الضريبة. يُحدَّث كل 30 دقيقة.`
            : `Each store's latest reading in the last ${res.data.window_days} days, grouped by barcode. Prices include VAT. Refreshed every 30 minutes.`}
        </p>
      </>}
    </div>
  );
}
