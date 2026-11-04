/**
 * Sales & prices (2 Nov 2026): the two plain tables the client asked for,
 * one row per product of his store.
 *   • Sales in units: product, brand, category, his units, and the units of
 *     every tracked store including his.
 *   • Prices: product, brand, category, his price, then each competitor's
 *     price in its own column.
 * Same rows and matches as the Market pages (backend/client_tables.py).
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Table2 } from "lucide-react";
import DataTable from "@/components/DataTable";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { RequestError } from "@/components/RequestError";

const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const PERIODS = [7, 14, 30, 90];
const dash = <span className="text-[#A1E4DB]/60">—</span>;

function productColumns(isRTL, categories) {
  return [
    { id: "name", label: isRTL ? "اسم المنتج" : "Product", type: "text", width: 320, always: true,
      // SKU and barcode too: the client looks products up by SKU (4 Nov 2026).
      get: (r) => [r.name_ar, r.name_en, r.sku, r.barcode], exportValue: (r) => (isRTL ? r.name_ar || r.name_en : r.name_en || r.name_ar),
      render: (r) => {
        const [main, other] = isRTL ? [r.name_ar || r.name_en, r.name_en] : [r.name_en || r.name_ar, r.name_ar];
        const code = r.barcode || r.sku;
        return <><p className="text-white">{main}</p>{other && other !== main && <p className="text-xs text-[#A1E4DB]">{other}</p>}
          {code && <p className="text-[11px] text-[#A1E4DB]/70" dir="ltr">{code}</p>}</>;
      } },
    { id: "brand", label: isRTL ? "البراند" : "Brand", type: "text", width: 130 },
    { id: "category", label: isRTL ? "الصنف" : "Category", type: "enum", width: 140, options: categories },
    { id: "barcode", label: isRTL ? "الباركود" : "Barcode", type: "text", width: 140, hidden: true,
      render: (r) => (r.barcode ? <span dir="ltr">{r.barcode}</span> : dash) },
  ];
}

export default function SalesPricesPage() {
  const { isRTL } = useI18n();
  const [tab, setTab] = useState("sales");
  const [days, setDays] = useState(30);
  const [q, setQ] = useState("");
  const res = useQuery({ queryKey: ["sales-prices", days],
    queryFn: async () => (await api.get("/sales-prices", { params: { days }, timeout: 60000 })).data });
  const data = res.data;
  const own = data?.own_store?.store_name || (isRTL ? "متجري" : "My store");

  const rows = useMemo(() => (data?.rows || []).map((r) => {
    // The cheapest in-stock price in the row, mine included, is shown in green.
    const live = Object.values(r.prices).filter((p) => !p[1]).map((p) => p[0]);
    if (r.my_price && !r.my_out_of_stock) live.push(r.my_price);
    return { ...r, low: live.length > 1 ? Math.min(...live) : null, n_prices: Object.keys(r.prices).length };
  }), [data]);
  const categories = useMemo(() => [...new Set(rows.map((r) => r.category).filter(Boolean))].sort(), [rows]);
  // One search over name, SKU, barcode and brand, for both tables. Arabic
  // digits count as digits; a barcode matches with or without leading zeros.
  const shown = useMemo(() => {
    const term = q.trim().toLowerCase().replace(/[٠-٩]/g, (d) => String("٠١٢٣٤٥٦٧٨٩".indexOf(d)));
    if (!term) return rows;
    const digits = /^\d+$/.test(term) ? term.replace(/^0+/, "") : null;
    return rows.filter((r) => [r.name_ar, r.name_en, r.brand].some((v) => (v || "").toLowerCase().includes(term))
      || [r.sku, r.barcode].some((v) => (v || "").toLowerCase().includes(term) || (digits && (v || "").replace(/^0+/, "").includes(digits))));
  }, [rows, q]);

  const salesColumns = useMemo(() => [
    ...productColumns(isRTL, categories),
    { id: "my_units", label: isRTL ? `مبيعات ${own} (حبة)` : `${own} sales (units)`, type: "number", width: 140, align: "end",
      exportValue: (r) => (r.my_units != null ? r.my_units : r.my_out_of_stock ? (isRTL ? "نفد" : "out of stock") : ""),
      render: (r) => (r.my_units != null ? <span className="text-white font-semibold">{fmt(r.my_units, 0)}</span>
        : r.my_out_of_stock ? <span className="text-[#F59E0B]">{isRTL ? "نفد" : "out of stock"}</span> : dash) },
    { id: "market_units", label: isRTL ? `مبيعات كل المتاجر شاملة ${own} (حبة)` : `All stores incl. ${own} (units)`, type: "number", width: 170, align: "end",
      render: (r) => (r.market_units == null ? dash : fmt(r.market_units, 0)) },
    { id: "share", label: isRTL ? `حصة ${own} (%)` : `${own} share (%)`, type: "number", width: 110, align: "end", hidden: true,
      get: (r) => (r.my_units != null && r.market_units ? Math.round((r.my_units / r.market_units) * 1000) / 10 : null) },
    { id: "stores_with_units", label: isRTL ? "متاجر لها قراءة مبيعات" : "Stores with a sales reading", type: "number", width: 120, align: "end", hidden: true },
  ], [isRTL, categories, own]);

  const priceColumns = useMemo(() => {
    const cell = (price, oos, low) => (
      <span className={oos ? "opacity-60" : ""}>
        <span className={!oos && low != null && price === low ? "text-[#10B981] font-semibold" : "text-white"}>{fmt(price)}</span>
        {oos && <span className="block text-xs text-[#F59E0B]">{isRTL ? "نفد" : "out of stock"}</span>}
      </span>);
    return [
      ...productColumns(isRTL, categories),
      { id: "my_price", label: isRTL ? `سعر ${own}` : `${own} price`, type: "number", width: 120, align: "end",
        exportValue: (r) => (r.my_price == null ? "" : `${r.my_price}${r.my_out_of_stock ? (isRTL ? " نفد" : " OOS") : ""}`),
        render: (r) => (r.my_price == null ? dash : <span className="font-semibold">{cell(r.my_price, r.my_out_of_stock, r.low)}</span>) },
      ...(data?.competitors || []).map((s, i) => ({
        id: `store:${s.store_id}`, label: s.store_name, type: "number", width: 105, align: "end",
        get: (r) => r.prices[i]?.[0], exportValue: (r) => (r.prices[i] ? `${r.prices[i][0]}${r.prices[i][1] ? (isRTL ? " نفد" : " OOS") : ""}` : ""),
        render: (r) => (r.prices[i] ? cell(r.prices[i][0], r.prices[i][1], r.low) : dash),
      })),
      { id: "n_prices", label: isRTL ? "عدد المنافسين الذين يبيعونه" : "Competitors selling it", type: "number", width: 120, align: "end", hidden: true },
    ];
  }, [isRTL, categories, own, data]);

  const totals = useMemo(() => {
    const mine = shown.filter((r) => r.my_units != null);
    const market = shown.filter((r) => r.market_units != null);
    return { mine: mine.reduce((n, r) => n + r.my_units, 0), market: market.reduce((n, r) => n + r.market_units, 0) };
  }, [shown]);

  const w = data?.window;
  const tabBtn = (id, ar, en) => (
    <button key={id} onClick={() => setTab(id)} data-testid={`sp-tab-${id}`}
      className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${tab === id ? "border-[#1E988E] text-white" : "border-transparent text-[#A1E4DB] hover:text-white"}`}>
      {isRTL ? ar : en}</button>);

  return (
    <div className="p-6 space-y-4" data-testid="sales-prices-page">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white inline-flex items-center gap-2">
          <Table2 className="w-6 h-6 text-[#1E988E]" />{isRTL ? "المبيعات والأسعار" : "Sales & prices"}</h1>
        <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL
          ? "كل منتج من منتجات متجري: كم بعت وكم باع السوق، وسعري مقابل سعر كل منافس"
          : "Every product of my store: what I sold, what the market sold, and my price against every competitor's"}</p>
      </div>

      <input value={q} onChange={(e) => setQ(e.target.value)} data-testid="sp-search"
        placeholder={isRTL ? "ابحث بالاسم أو الـ SKU أو الباركود أو البراند" : "Search by name, SKU, barcode or brand"}
        className="w-full max-w-md h-10 px-3 rounded-lg bg-[#090E1C] border border-white/15 text-white text-sm placeholder:text-[#A1E4DB]/60 focus:outline-none focus:border-[#1E988E]" />

      <nav className="flex flex-wrap gap-1 border-b border-white/10">
        {tabBtn("sales", "المبيعات بالحبة", "Sales in units")}
        {tabBtn("prices", "الأسعار", "Prices")}
      </nav>

      {tab === "sales" && (
        <div className="flex flex-wrap items-center gap-2" data-testid="sp-periods">
          <span className="text-sm text-[#A1E4DB]">{isRTL ? "الفترة:" : "Period:"}</span>
          {PERIODS.map((d) => (
            <button key={d} onClick={() => setDays(d)} data-testid={`sp-days-${d}`}
              className={`h-8 px-3 rounded-full text-xs ${days === d ? "bg-[#1E988E] text-[#090E1C] font-semibold" : "bg-white/5 text-[#A1E4DB] hover:text-white"}`}>
              {isRTL ? `آخر ${d} يوم` : `Last ${d} days`}</button>
          ))}
          {w && <span className="text-xs text-[#A1E4DB]" dir="ltr">{w.date_from} → {w.date_to}</span>}
        </div>
      )}

      {res.isError ? <RequestError id="sales-prices" error={res.error} onRetry={() => res.refetch()} />
        : !data ? <p className="text-sm text-[#A1E4DB]" data-testid="sp-loading">{isRTL ? "جارٍ التحميل…" : "Loading…"}</p>
        : tab === "sales" ? (
          <>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2" data-testid="sp-totals">
              <div className="glass-card rounded-md p-3">
                <p className="text-xs text-[#A1E4DB]">{isRTL ? `مبيعات ${own}` : `${own} sales`}</p>
                <p className="text-xl font-bold text-white">{fmt(totals.mine, 0)} <span className="text-xs font-normal text-[#A1E4DB]">{isRTL ? "حبة" : "units"}</span></p>
              </div>
              <div className="glass-card rounded-md p-3">
                <p className="text-xs text-[#A1E4DB]">{isRTL ? `مبيعات كل المتاجر شاملة ${own}` : `All stores incl. ${own}`}</p>
                <p className="text-xl font-bold text-white">{fmt(totals.market, 0)} <span className="text-xs font-normal text-[#A1E4DB]">{isRTL ? "حبة" : "units"}</span></p>
              </div>
              <div className="glass-card rounded-md p-3">
                <p className="text-xs text-[#A1E4DB]">{isRTL ? "المنتجات" : "Products"}</p>
                <p className="text-xl font-bold text-white">{fmt(shown.length, 0)}</p>
              </div>
            </div>
            <DataTable key={`sales-${isRTL}`} columns={salesColumns} rows={shown} storageKey="sp-sales" exportName={isRTL ? "مبيعات-بالحبة" : "sales-in-units"}
              rowKey={(r) => r.key} initialSort={{ id: "market_units", dir: "desc" }} />
            <p className="text-xs text-[#A1E4DB]/80">{isRTL
              ? `المبيعات بالحبة لكل متجر محسوبة من حركة المخزون وعدادات البيع في موقعه خلال الفترة (أيام كاملة بتوقيت السعودية)، ومبيعات ${own} محسوبة بنفس الطريقة وقد تختلف قليلاً عن تقارير زد. «نفد» = المنتج نافد لدى ${own} فلا توجد حركة تُقاس. «—» = لا توجد قراءة لهذا المنتج في هذه الفترة، وليست صفراً.`
              : `Units per store are measured from stock movement and sold counters on its site over the period (whole KSA days); ${own}'s units are measured the same way and may differ slightly from Zid reports. “Out of stock” = ${own} has none, so there is no movement to measure. “—” = no reading for this product in this period, not zero.`}</p>
          </>
        ) : (
          <>
            <DataTable key={`prices-${isRTL}`} columns={priceColumns} rows={shown} storageKey="sp-prices" exportName={isRTL ? "الأسعار" : "prices"}
              rowKey={(r) => r.key} initialSort={{ id: "n_prices", dir: "desc" }} />
            <p className="text-xs text-[#A1E4DB]/80">{isRTL
              ? "آخر سعر رُصد في كل متجر، بالريال شامل الضريبة. الأخضر = أرخص سعر متوفر في الصف. «نفد» = آخر سعر قبل نفاد الكمية. «—» = المتجر لا يبيع هذا المنتج."
              : "Each store's latest price, in SAR including VAT. Green = the cheapest in-stock price in the row. “Out of stock” = the last price before it ran out. “—” = the store does not sell this product."}</p>
          </>
        )}
    </div>
  );
}
