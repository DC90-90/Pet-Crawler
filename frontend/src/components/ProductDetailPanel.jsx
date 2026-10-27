/**
 * Product detail (16 Oct 2026) — one product against every seller:
 *   position     → my rank by price, gap to the lowest and to the median
 *   sellers      → price (with the seller's own pre-discount price), units sold
 *                  and revenue over the period, share of units, stock
 *   market sales → daily units sold by all measured sellers, per store
 * Sales come from the sealed daily ledger (the same facts as every revenue
 * figure). A seller whose store shows neither stock levels nor a sold counter
 * is marked "not measurable" and no share is shown while one is missing.
 */
import { useEffect, useMemo, useState } from "react";
import { SalesPeriod } from "@/components/SalesPeriod";
import { toast } from "sonner";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { HistoricalQuantity } from "@/components/HistoricalQuantity";
import { X, ExternalLink, Bell, ImageOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend } from "recharts";
import { useSeasonalEvents, SeasonalToggle, SeasonalChartElements } from "@/components/SeasonalAnnotations";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import FreshnessBadge from "@/components/FreshnessBadge";
import { StoreLogo } from "@/components/StoreLogo";

const STORE_COLORS = ["#1E988E", "#3B82F6", "#F59E0B", "#EC4899", "#8B5CF6", "#10B981", "#EF4444", "#06B6D4"];
const PERIODS = [7, 14, 30, 60];
const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));
const signed = (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n}%`);

function StockBadge({ signal }) {
  const cls = { HIGH: "stock-high", MEDIUM: "stock-medium", LOW: "stock-low", OOS: "stock-oos", AVAIL: "stock-high" };
  const labelMap = { AVAIL: "IN STOCK" };
  if (!signal || signal === "UNKNOWN") return <span className="text-[10px] text-[#A1E4DB]/60">—</span>;
  return <span className={`text-[10px] font-bold ${cls[signal] || ""}`}>{labelMap[signal] || signal}</span>;
}

function Stat({ label, value, sub, tone, testId }) {
  return (
    <div className="kpi-card !p-3" data-testid={testId}>
      <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p>
      <p className={`text-base font-bold mt-0.5 metric-number ${tone || "text-white"}`}>{value}</p>
      {sub && <p className="text-[10px] text-[#A1E4DB] mt-0.5">{sub}</p>}
    </div>
  );
}

function AlertButton({ sku, isRTL }) {
  const [open, setOpen] = useState(false);
  const [type, setType] = useState("price_drop");
  const [threshold, setThreshold] = useState(5);
  const [busy, setBusy] = useState(false);
  const types = [
    ["price_drop", isRTL ? "انخفاض سعر منافس" : "Competitor price drop"],
    ["price_increase", isRTL ? "ارتفاع سعر منافس" : "Competitor price increase"],
    ["out_of_stock", isRTL ? "نفاد مخزون منافس" : "Competitor out of stock"],
    ["back_in_stock", isRTL ? "عودة توفر منافس" : "Competitor back in stock"],
  ];
  const create = async () => {
    setBusy(true);
    try {
      await api.post("/alerts", { product_sku: sku, alert_type: type, threshold: ["price_drop", "price_increase"].includes(type) ? Number(threshold) : null });
      toast.success(isRTL ? "تم إنشاء التنبيه" : "Alert created");
      setOpen(false);
    } catch (e) {
      toast.error(e?.response?.data?.detail || (isRTL ? "تعذر إنشاء التنبيه" : "Could not create the alert"));
    } finally { setBusy(false); }
  };
  if (!open) {
    return (
      <Button size="sm" variant="outline" className="h-7 text-xs gap-1.5" onClick={() => setOpen(true)} data-testid="product-detail-alert-btn">
        <Bell className="w-3.5 h-3.5" />{isRTL ? "إنشاء تنبيه" : "Create alert"}
      </Button>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 p-2 rounded-md border border-white/10 bg-black/20" data-testid="product-detail-alert-form">
      <select value={type} onChange={(e) => setType(e.target.value)} className="h-7 text-xs rounded bg-[#0A2728] border border-[#13625F] text-white px-2">
        {types.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
      </select>
      {["price_drop", "price_increase"].includes(type) && (
        <label className="text-[11px] text-[#A1E4DB] inline-flex items-center gap-1">
          ≥ <input type="number" min={1} max={90} value={threshold} onChange={(e) => setThreshold(e.target.value)}
            className="w-12 h-7 text-xs rounded bg-[#0A2728] border border-[#13625F] text-white px-1" />%
        </label>
      )}
      <Button size="sm" className="h-7 text-xs bg-[#1E988E] text-[#090E1C]" disabled={busy} onClick={create}>{isRTL ? "حفظ" : "Save"}</Button>
      <button onClick={() => setOpen(false)} className="text-[#A1E4DB] hover:text-white" aria-label="close"><X className="w-3.5 h-3.5" /></button>
    </div>
  );
}

export default function ProductDetailPanel({ sku, onClose }) {
  const { t, isRTL } = useI18n();
  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [days, setDays] = useState(30);
  const [showExcluded, setShowExcluded] = useState(false);
  const seasonal = useSeasonalEvents();

  // iter73y — a request with no timeout left the panel on "Loading…" forever;
  // it fails visibly and can be retried.
  useEffect(() => {
    if (!sku) { setProduct(null); setError(null); return; }
    let alive = true;
    setLoading(true);
    setError(null);
    api.get(`/products/${encodeURIComponent(sku)}/full`, { params: { days }, timeout: 45000 })
      .then(({ data }) => { if (alive) setProduct(data); })
      .catch((err) => {
        if (!alive) return;
        setProduct(null);
        setError(err?.code === "ECONNABORTED" ? t("detail_timeout") : err?.response?.data?.detail || t("detail_failed"));
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [sku, attempt, days]);   // eslint-disable-line react-hooks/exhaustive-deps

  const view = useMemo(() => {
    if (!product) return null;
    const all = product.store_prices || [];
    const live = all.filter((s) => s.price_status === "live" && s.price != null).sort((a, b) => a.price - b.price);
    const liveStores = new Set(live.map((s) => s.store_id));
    // An older offer of a store that also has a live one is not another seller.
    const excluded = all.filter((s) => s.price_status !== "live" && !liveStores.has(s.store_id));
    const history = product.history || {};
    const dateMap = {};
    Object.entries(history).forEach(([store, points]) => points.forEach((pt) => {
      const date = pt.date.split("T")[0];
      dateMap[date] = { ...(dateMap[date] || { date }), [store]: pt.price };
    }));
    const maxPrice = Math.max(...live.map((s) => s.price), 1);
    return { live, excluded, historyData: Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date)),
      historyStores: Object.keys(history), maxPrice, market: product.market_sales, pos: product.position,
      mine: live.find((s) => s.is_own_store) };
  }, [product]);

  const colorOf = (name) => {
    const names = view?.historyStores?.length ? view.historyStores : (view?.market?.velocity?.stores || []);
    const i = names.indexOf(name);
    return STORE_COLORS[(i < 0 ? names.length : i) % STORE_COLORS.length];
  };

  return (
    <Sheet open={!!sku} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent aria-describedby={undefined} className="w-full sm:w-[720px] sm:max-w-[720px] overflow-y-auto p-0" data-testid="product-detail-panel">
        <SheetHeader className="px-5 py-4 border-b border-white/10 sticky top-0 bg-[#0A2728] z-10">
          <SheetTitle className="text-base font-bold text-white inline-flex items-center gap-2">
            <MineBadge sku={sku} />
            {product?.name_ar || t("loading")}
          </SheetTitle>
        </SheetHeader>

        {loading && !product ? (
          <div className="p-5 text-sm text-[#A1E4DB]" data-testid="product-detail-loading">{t("loading")}</div>
        ) : error ? (
          <div className="p-5 space-y-3" data-testid="product-detail-error">
            <p className="text-sm text-red-300">{error}</p>
            <Button size="sm" variant="outline" data-testid="product-detail-retry-btn" onClick={() => setAttempt((n) => n + 1)}>{t("retry")}</Button>
          </div>
        ) : product && view ? (
          <div className={`p-5 space-y-5 ${loading ? "opacity-60" : ""}`}>
            {/* Header */}
            <div className="flex gap-4">
              <div className="w-24 h-24 shrink-0 rounded-md bg-white flex items-center justify-center overflow-hidden" data-testid="product-detail-image">
                {product.image_url ? <img src={product.image_url} alt="" className="max-w-full max-h-full object-contain" loading="lazy" />
                  : <ImageOff className="w-6 h-6 text-gray-400" />}
              </div>
              <div className="min-w-0 flex-1 space-y-1.5">
                <p className="text-sm text-[#A1E4DB]">{product.name_en}</p>
                <SkuLine sku={product.sku} barcode={product.barcode} size="sm" />
                <div className="flex flex-wrap items-center gap-1.5">
                  {product.category && <Badge variant="secondary" className="text-[10px] capitalize">{product.category}</Badge>}
                  {product.brand && <Badge variant="secondary" className="text-[10px]">{product.brand}</Badge>}
                  {product.product_url && (
                    <a href={product.product_url} target="_blank" rel="noopener noreferrer" className="text-[11px] text-[#6AC1B5] inline-flex items-center gap-1">
                      {isRTL ? "صفحة المنتج" : "Product page"}<ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </div>
                <AlertButton sku={product.sku} isRTL={isRTL} />
              </div>
            </div>

            {/* Period */}
            <div className="flex items-center gap-1" data-testid="product-detail-period">
              <span className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB] me-2">{isRTL ? "الفترة" : "Period"}</span>
              {PERIODS.map((d) => (
                <button key={d} onClick={() => setDays(d)} data-testid={`product-detail-days-${d}`}
                  className={`text-xs rounded-full h-6 px-2.5 ${days === d ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:bg-white/5"}`}>
                  {isRTL ? `${d} يوماً` : `${d}D`}
                </button>
              ))}
            </div>

            {view.market && (
              <SalesPeriod from={view.market.window?.from} to={view.market.window?.to} days={view.market.days || days}
                basis={view.market.sellers_live ? (isRTL ? `مبيعات ${view.market.sellers_measured} من ${view.market.sellers_live} بائعين قابلة للقياس، مقدّرة من تغيّر المخزون`
                  : `${view.market.sellers_measured} of ${view.market.sellers_live} sellers' sales measurable, estimated from stock changes`) : null} />
            )}

            {/* Position */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2" data-testid="product-detail-position">
              <Stat testId="product-detail-own-price" label={t("col_price")}
                value={product.price != null ? `${product.price} SAR` : "—"}
                sub={view.mine?.discount_pct ? <span><s>{view.mine.original_price}</s> · -{view.mine.discount_pct}%</span>
                  : product.price_status === "unavailable" ? t("current_price_unavailable") : null} />
              <Stat testId="product-detail-rank" label={isRTL ? "ترتيبي بالسعر" : "My price rank"}
                value={view.pos ? `#${view.pos.rank} / ${view.pos.of}` : "—"}
                sub={view.pos ? (isRTL ? "1 = الأرخص" : "1 = cheapest") : null} />
              <Stat testId="product-detail-vs-lowest" label={isRTL ? "مقابل الأرخص" : "vs lowest"}
                value={signed(view.pos?.vs_lowest_pct)} tone={view.pos?.vs_lowest_pct > 0 ? "text-[#EF4444]" : "text-[#10B981]"}
                sub={view.pos ? `${view.pos.market_lowest} SAR` : null} />
              <Stat testId="product-detail-vs-median" label={isRTL ? "مقابل الوسيط" : "vs median"}
                value={signed(view.pos?.vs_median_pct)} tone={view.pos?.vs_median_pct > 0 ? "text-[#F59E0B]" : "text-[#10B981]"}
                sub={view.pos ? `${view.pos.market_median} SAR` : null} />
            </div>
            <HistoricalQuantity quantity={product.historical_quantity} observedAt={product.historical_quantity_at} id="product-own-historical-quantity" />

            {/* Market sales */}
            {view.market && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2" data-testid="product-detail-market">
                <Stat testId="product-detail-volume" label={isRTL ? "مبيعات السوق (وحدات)" : "Market units sold"}
                  value={fmt(view.market.units)} sub={isRTL ? `${days} يوماً` : `last ${days} days`} />
                <Stat testId="product-detail-market-revenue" label={isRTL ? "إيرادات السوق" : "Market revenue"}
                  value={view.market.revenue == null ? "—" : `${fmt(view.market.revenue)} SAR`} sub={isRTL ? "تقديرية" : "estimated"} />
                <Stat testId="product-detail-my-share" label={isRTL ? "حصتي (وحدات)" : "My share (units)"}
                  value={view.market.my_unit_share_pct != null ? `${view.market.my_unit_share_pct}%` : "—"}
                  sub={view.market.my_revenue_share_pct != null ? `${view.market.my_revenue_share_pct}% ${isRTL ? "من الإيرادات" : "of revenue"}` : null} />
                <Stat testId="product-detail-coverage" label={isRTL ? "بائعون مقاسون" : "Sellers measured"}
                  value={`${view.market.sellers_measured} / ${view.market.sellers_live}`}
                  tone={view.market.complete ? "text-white" : "text-[#F59E0B]"} />
                {!view.market.complete && (view.market.unmeasured || []).length > 0 && (
                  <div className="col-span-full text-[10px] text-[#F59E0B] space-y-0.5" data-testid="product-detail-unmeasured">
                    {view.market.unmeasured.map((u) => (
                      <p key={u.store}>
                        {u.reason === "out_of_stock"
                          ? (isRTL ? `${u.store}: نفد المخزون طوال الفترة — لا مبيعات لقياسها.` : `${u.store}: out of stock for the period — no sales to measure.`)
                          : u.reason === "no_stock_movement"
                            ? (isRTL ? `${u.store}: لم يتغير المخزون بين القراءات في الفترة.` : `${u.store}: stock did not move between readings in the period.`)
                            : (isRTL ? `${u.store}: لا ينشر المتجر المخزون ولا عدد المبيعات.` : `${u.store}: the store publishes neither stock levels nor a sold count.`)}
                      </p>
                    ))}
                    <p className="text-[#A1E4DB]">{isRTL ? "لا تظهر الحصة إلا عندما تُقاس مبيعات كل البائعين." : "A share is shown only when every seller's sales are measured."}</p>
                  </div>
                )}
              </div>
            )}

            {/* Every competitor out of stock: say so, with their last prices. */}
            {view.live.filter((s) => !s.is_own_store).length === 0 && (product.out_of_stock_competitors || []).length > 0 && (
              <div className="rounded-md border border-[#F59E0B]/30 bg-[#F59E0B]/10 p-3 text-xs" data-testid="product-detail-all-oos">
                <p className="text-[#FBBF24] font-semibold">
                  {isRTL ? `كل المنافسين (${product.out_of_stock_competitors.length}) نفد لديهم هذا المنتج — لا يوجد سعر حالي للمقارنة.`
                    : `All ${product.out_of_stock_competitors.length} competitors are out of stock — there is no current price to compare with.`}
                </p>
                <p className="text-[#A1E4DB] mt-1">
                  {isRTL ? "آخر أسعارهم: " : "Their last prices: "}
                  {product.out_of_stock_competitors.map((r) => `${r.store_name} ${r.last_price}`).join(" · ")} SAR
                </p>
              </div>
            )}

            {/* Sellers */}
            <div>
              <div className="flex items-baseline justify-between mb-2">
                <h4 className="text-xs font-semibold text-white">
                  {isRTL ? "متوفر حالياً لدى" : "In stock now at"} <span className="font-normal text-[#A1E4DB]" data-testid="seller-count">({view.live.filter((s) => s.in_stock !== false).length}{product.competitors_total != null ? (isRTL ? ` من ${product.competitors_total + 1} بائعين` : ` of ${product.competitors_total + 1} sellers`) : ""})</span>
                </h4>
                <span className="text-[10px] text-[#A1E4DB]/70">{isRTL ? "مرتبة من الأرخص" : "cheapest first"}</span>
              </div>
              <div className="border border-white/10 rounded-md overflow-x-auto">
                <table className="w-full text-xs" data-testid="product-detail-offer-table">
                  <thead>
                    <tr className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB] border-b border-white/10">
                      <th className="text-start p-2">{isRTL ? "المتجر" : "Store"}</th>
                      <th className="text-start p-2">{isRTL ? "السعر" : "Price"}</th>
                      <th className="text-end p-2">{isRTL ? `مبيع (${days}ي)` : `Sold (${days}d)`}</th>
                      <th className="text-end p-2">{isRTL ? "الإيرادات" : "Revenue"}</th>
                      <th className="text-end p-2">{isRTL ? "الحصة" : "Share"}</th>
                      <th className="text-start p-2">{isRTL ? "المخزون" : "Stock"}</th>
                      <th className="text-start p-2">{isRTL ? "آخر قراءة" : "Seen"}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {view.live.map((sp) => (
                      <tr key={sp.store_id} className={`border-b border-white/5 ${sp.is_own_store ? "bg-[#1E988E]/10" : ""}`} data-testid={`store-row-${sp.store_id}`}>
                        <td className="p-2">
                          <span className="inline-flex items-center gap-1.5">
                            <StoreLogo storeId={sp.store_id} name={sp.store_name} size={18} />
                            {sp.product_url ? (
                              <a href={sp.product_url} target="_blank" rel="noopener noreferrer" className="text-white hover:text-[#6AC1B5] inline-flex items-center gap-1" data-testid={`store-link-${sp.store_id}`}>
                                {sp.store_name}<ExternalLink className="w-3 h-3 opacity-60" />
                              </a>
                            ) : <span className="text-white">{sp.store_name}</span>}
                            {sp.is_own_store && <span className="text-[8px] font-bold uppercase px-1 rounded bg-[#1E988E]/20 text-[#1E988E]" data-testid={`my-store-tag-${sp.store_id}`}>{isRTL ? "متجري" : "Me"}</span>}
                          </span>
                          {sp.shared_stock_with?.length > 0 && <p className="text-[9px] text-[#F59E0B] mt-0.5">{isRTL ? `مخزون مشترك مع ${sp.shared_stock_with.join("، ")}` : `shares stock with ${sp.shared_stock_with.join(", ")}`}</p>}
                        </td>
                        <td className="p-2" data-testid={`detail-offer-price-${sp.store_id}`}>
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-white whitespace-nowrap">{sp.price} SAR</span>
                            <span className="hidden md:block h-1.5 rounded-full bg-[#1E988E]/60" style={{ width: `${Math.max(6, (sp.price / view.maxPrice) * 60)}px` }} />
                          </div>
                          {sp.discount_pct ? <p className="text-[10px] text-[#10B981]"><s className="text-[#A1E4DB]">{sp.original_price}</s> -{sp.discount_pct}%</p> : null}
                        </td>
                        <td className="p-2 text-end text-white metric-number" data-testid={`detail-offer-units-${sp.store_id}`}>
                          {sp.sales_measured ? fmt(sp.units_sold) : <span className="text-[10px] text-[#A1E4DB]/70" title={isRTL ? "لا ينشر المتجر المخزون ولا عدد المبيعات" : "Store publishes neither stock nor a sold count"}>{isRTL ? "غير قابل للقياس" : "n/a"}</span>}
                        </td>
                        <td className="p-2 text-end text-[#A1E4DB] metric-number">{sp.sales_measured ? fmt(sp.revenue_est) : "—"}</td>
                        <td className="p-2 text-end text-white metric-number">{sp.unit_share_pct != null ? `${sp.unit_share_pct}%` : "—"}</td>
                        <td className="p-2" data-testid={`detail-offer-stock-${sp.store_id}`}>
                          <StockBadge signal={sp.stock_signal} />
                          {sp.qty_available != null && sp.qty_available > 0 && <span className="ms-1 text-[10px] text-[#A1E4DB] font-mono">{sp.qty_available}</span>}
                        </td>
                        <td className="p-2"><FreshnessBadge crawledAt={sp.last_crawl_at || sp.crawled_at} testIdPrefix={`store-fresh-${sp.store_id}`} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {view.excluded.length > 0 && (
                <div className="mt-2">
                  <button className="text-[10px] text-[#A1E4DB] hover:text-white" onClick={() => setShowExcluded((v) => !v)} data-testid="product-detail-excluded-toggle">
                    {showExcluded ? "▾" : "▸"} {isRTL ? `${view.excluded.length} متجر خارج المقارنة (نفد المخزون أو قراءة قديمة)` : `${view.excluded.length} stores not compared (out of stock or old reading)`}
                  </button>
                  {showExcluded && (
                    <div className="mt-1 space-y-1">
                      {view.excluded.map((sp, i) => (
                        <div key={`${sp.store_id}-${i}`} className="flex items-center justify-between text-[11px] text-[#A1E4DB] px-2 py-1 rounded bg-white/[0.03]">
                          <span className="inline-flex items-center gap-1.5"><StoreLogo storeId={sp.store_id} name={sp.store_name} size={14} />{sp.store_name}</span>
                          <span data-testid={`detail-offer-exclusion-${sp.store_id}`}>{(sp.excluded_reason || "").replaceAll("_", " ")}{sp.historical_price ? ` · ${sp.historical_price} SAR` : ""}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Daily units sold, per store */}
            {view.market?.velocity?.velocity?.length > 0 && (
              <div data-testid="product-detail-velocity">
                <h4 className="text-xs font-semibold text-white mb-2">
                  {isRTL ? "المبيعات اليومية في السوق" : "Daily units sold in the market"}
                  <span className="font-normal text-[#A1E4DB]"> ({view.market.velocity.avg_daily} {t("units_day")})</span>
                </h4>
                <div className="border border-white/10 rounded-md p-3">
                  <ResponsiveContainer width="100%" height={170}>
                    <BarChart data={view.market.velocity.velocity}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                      <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#A1E4DB" }} tickFormatter={(d) => d.slice(5)} />
                      <YAxis tick={{ fontSize: 9, fill: "#A1E4DB" }} allowDecimals={false} />
                      <Tooltip contentStyle={{ fontSize: 11, background: "#0A2728", border: "1px solid rgba(255,255,255,0.1)" }} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      {view.market.velocity.stores.map((name) => <Bar key={name} dataKey={name} stackId="u" fill={colorOf(name)} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Price history */}
            {view.historyData.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-semibold text-white">{t("chart_price_history")}</h4>
                  <SeasonalToggle show={seasonal.show} toggle={seasonal.toggle} />
                </div>
                <div className="border border-white/10 rounded-md p-3">
                  <ResponsiveContainer width="100%" height={190}>
                    <LineChart data={view.historyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                      <XAxis dataKey="date" tick={{ fontSize: 9, fill: "#A1E4DB" }} tickFormatter={(d) => d.slice(5)} />
                      <YAxis tick={{ fontSize: 9, fill: "#A1E4DB" }} domain={["auto", "auto"]} />
                      <Tooltip contentStyle={{ fontSize: 11, background: "#0A2728", border: "1px solid rgba(255,255,255,0.1)" }} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      <SeasonalChartElements show={seasonal.show} />
                      {view.historyStores.map((store) => (
                        <Line key={store} type="stepAfter" dataKey={store} stroke={colorOf(store)} strokeWidth={store === product.store_prices?.find((s) => s.is_own_store)?.store_name ? 3 : 1.5} dot={false} connectNulls />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
            <p className="text-[10px] text-[#A1E4DB]/70">
              {isRTL ? "المبيعات تقديرية من التغير اليومي في المخزون أو عدّاد المبيعات العام للمتجر، وليست فواتير."
                : "Sales are estimated from day-to-day stock changes or the store's public sold counter, not from invoices."}
            </p>
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
