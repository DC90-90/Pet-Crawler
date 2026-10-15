/**
 * Overview (15 Oct 2026) — the home page. Every number appears once in Daleel
 * and is taken from one source, labelled with its period:
 *   my revenue + store table  → /price-intel/store-ranking (sealed daily ledger, 30 days)
 *   my revenue share           → /market-share/overview (30 days)
 *   price position             → /insights/summary market_position_summary
 *   products I don't sell      → /market-share/overview (the Opportunities list)
 * Before, the same revenue appeared on four cards with four different values.
 */
import { useNavigate, Link } from "react-router-dom";
import { useQueries } from "@tanstack/react-query";
import { ArrowRight, Store as StoreIcon } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { RequestError } from "@/components/RequestError";
import DataFreshnessBanner from "@/components/DataFreshnessBanner";

const fmt = (n, d = 0) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: d }));

function Kpi({ label, value, sub, to, testId }) {
  const body = (
    <div className="kpi-card h-full" data-testid={testId}>
      <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{label}</p>
      <p className="text-2xl font-bold tracking-tighter text-white mt-1 metric-number">{value}</p>
      {sub && <p className="text-[11px] text-[#A1E4DB] mt-0.5">{sub}</p>}
    </div>
  );
  return to ? <Link to={to} className="block hover:opacity-90">{body}</Link> : body;
}

export default function OverviewPage() {
  const { t, isRTL } = useI18n();
  const navigate = useNavigate();
  const results = useQueries({
    queries: [
      { queryKey: ["overview", "ranking"], queryFn: async () => (await api.get("/price-intel/store-ranking")).data },
      { queryKey: ["overview", "summary", 30], queryFn: async () => (await api.get("/insights/summary", { params: { days: 30 } })).data },
      { queryKey: ["overview", "share", 30], queryFn: async () => (await api.get("/market-share/overview", { params: { days: 30, include_today: false } })).data },
    ],
  });
  const [rankQ, sumQ, shareQ] = results;
  const stores = rankQ.data?.stores || [];
  const own = stores.find((s) => s.is_own_store);
  const measured = stores.filter((s) => s.revenue_30d != null).sort((a, b) => b.revenue_30d - a.revenue_30d);
  const ownPosition = own && own.revenue_30d != null ? measured.findIndex((s) => s.store_id === own.store_id) + 1 : null;
  const table = [...measured, ...stores.filter((s) => s.revenue_30d == null)];
  const mps = sumQ.data?.market_position_summary;
  const pct = mps?.avg_percentile;
  const priceVerdict = pct == null ? "—"
    : pct < 33 ? (isRTL ? "أرخص من معظم السوق" : "Cheaper than most")
    : pct < 50 ? (isRTL ? "أقل من وسيط السوق" : "Below the market median")
    : pct < 66 ? (isRTL ? "أعلى من وسيط السوق" : "Above the market median")
    : (isRTL ? "أغلى من معظم السوق" : "More expensive than most");
  const share = shareQ.data?.kpis || {};
  const failed = results.find((r) => r.isError);

  return (
    <div className="p-6 space-y-5" data-testid="overview-page">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white">{t("nav_overview")}</h1>
        <p className="text-sm text-[#A1E4DB] mt-0.5">
          {isRTL ? "أداء متجرك مقابل المنافسين المتتبعين — آخر 30 يوماً مكتملة" : "Your store against tracked competitors — last 30 complete days"}
        </p>
      </div>
      <DataFreshnessBanner />
      {failed && <RequestError id="overview-request" error={failed.error} onRetry={() => results.filter((r) => r.isError).forEach((r) => r.refetch())} />}

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3" data-testid="overview-kpis">
        <Kpi testId="ov-kpi-revenue" label={isRTL ? "إيراداتي (30 يوماً)" : "My revenue (30 days)"}
          value={own?.revenue_30d != null ? `${fmt(own.revenue_30d)} SAR` : "—"}
          sub={own?.revenue_30d != null ? (isRTL ? `تقدير من حركة المخزون · ${own.revenue_days_measured} من 30 يوماً` : `Estimated from stock changes · ${own.revenue_days_measured} of 30 days measured`) : null} />
        <Kpi testId="ov-kpi-position" label={isRTL ? "ترتيبي بالإيرادات" : "My revenue rank"}
          value={ownPosition ? `#${ownPosition}` : "—"}
          sub={ownPosition ? (isRTL ? `من ${measured.length} متاجر قابلة للقياس` : `of ${measured.length} stores with measurable sales`) : null} />
        <Kpi testId="ov-kpi-share" to="/market-share" label={isRTL ? "حصتي من الإيرادات" : "My revenue share"}
          value={share.my_revenue_share_pct != null ? `${share.my_revenue_share_pct}%` : "—"}
          sub={share.products_contested != null ? (isRTL ? `على ${fmt(share.products_contested)} منتجاً تُقاس فيه مبيعات المنافسين` : `on ${fmt(share.products_contested)} products where competitors' sales are measured`) : null} />
        <Kpi testId="ov-kpi-price" to="/pricing" label={isRTL ? "موقعي السعري" : "My price position"}
          value={priceVerdict}
          sub={mps?.ranked_products ? (isRTL ? `${fmt(mps.ranked_products)} منتجاً مقارناً` : `${fmt(mps.ranked_products)} products compared`) : null} />
        <Kpi testId="ov-kpi-missing" to="/opportunities" label={isRTL ? "منتجات لا أبيعها" : "Products I don't sell"}
          value={fmt(share.missing_products_total)}
          sub={isRTL ? "يبيعها منافسون متتبعون" : "sold by tracked competitors"} />
      </div>

      {mps && mps.ranked_products > 0 && (
        <div className="glass-card rounded-md p-4" data-testid="overview-market-position">
          <div className="flex items-baseline justify-between mb-3">
            <h3 className="text-xs uppercase tracking-[0.15em] font-semibold text-[#A1E4DB]">{isRTL ? "أين تقع أسعاري" : "Where my prices sit"}</h3>
            <p className="text-[10px] text-[#A1E4DB]">{isRTL ? `${fmt(mps.ranked_products)} منتجاً مقارناً` : `${fmt(mps.ranked_products)} products compared`}</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {[
              ["cheapest", mps.cheapest_count, isRTL ? "الأرخص" : "Cheapest seller", "#10B981"],
              ["below_median", mps.below_median_count, isRTL ? "أقل من الوسيط" : "Below market median", "#6AC1B5"],
              ["above_median", mps.above_median_count, isRTL ? "أعلى من الوسيط" : "Above market median", "#FBBF24"],
              ["most_expensive", mps.most_expensive_count, isRTL ? "الأغلى" : "Most expensive", "#F59E0B"],
            ].map(([key, count, label, color]) => (
              <div key={key} className="text-start p-3 rounded" style={{ border: "1px solid rgba(255,255,255,0.06)", background: "rgba(0,0,0,0.15)" }}
                data-testid={`ov-mp-${key}`}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="w-2 h-2 rounded-full" style={{ background: color }} />
                  <span className="text-[10px] uppercase tracking-[0.1em] font-semibold" style={{ color }}>{label}</span>
                </div>
                <p className="text-xl font-bold text-white">{fmt(count)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="glass-card rounded-md p-5" data-testid="overview-store-table">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-white flex items-center gap-2"><StoreIcon className="w-4 h-4 text-[#1E988E]" />{isRTL ? "ترتيب المتاجر (30 يوماً)" : "Store ranking (30 days)"}</h3>
          <Link to="/stores" className="text-[11px] text-[#6AC1B5] inline-flex items-center gap-1">{t("nav_competitors")}<ArrowRight className="w-3 h-3" /></Link>
        </div>
        {rankQ.isLoading ? <p className="text-xs text-[#A1E4DB]">{t("loading")}</p> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.1em] text-[#A1E4DB] border-b border-white/10">
                  <th className="text-start py-2 pe-2">#</th>
                  <th className="text-start py-2 pe-2">{isRTL ? "المتجر" : "Store"}</th>
                  <th className="text-end py-2 pe-2">{isRTL ? "الإيرادات التقديرية" : "Est. revenue"}</th>
                  <th className="text-end py-2 pe-2">{isRTL ? "أيام مقاسة" : "Days measured"}</th>
                  <th className="text-end py-2 pe-2">{isRTL ? "منتجات موثقة" : "Verified products"}</th>
                  <th className="text-end py-2">{isRTL ? "متوفر" : "In stock"}</th>
                </tr>
              </thead>
              <tbody>
                {table.map((s, i) => (
                  <tr key={s.store_id} onClick={() => navigate(`/stores/${s.store_id}`)}
                    className={`border-b border-white/5 cursor-pointer hover:bg-white/[0.03] ${s.is_own_store ? "bg-[#1E988E]/10" : ""}`}
                    data-testid={`ov-store-${s.store_id}`}>
                    <td className="py-2 pe-2 text-[#A1E4DB]">{s.revenue_30d != null ? i + 1 : "—"}</td>
                    <td className="py-2 pe-2">
                      <span className="text-white font-medium">{s.name}</span>
                      {s.is_own_store && <span className="ms-2 text-[10px] text-[#1E988E]">{isRTL ? "متجري" : "my store"}</span>}
                      <span className="ms-2 text-[10px] text-[#A1E4DB] uppercase">{s.platform}</span>
                      {s.shared_stock_with?.length > 0 && (
                        <p className="text-[10px] text-[#F59E0B]">{isRTL ? `مخزون مشترك مع ${s.shared_stock_with.join("، ")}` : `shared stock with ${s.shared_stock_with.join(", ")}`}</p>
                      )}
                    </td>
                    <td className="py-2 pe-2 text-end metric-number">
                      {s.revenue_30d != null ? <span className="text-white">{fmt(s.revenue_30d)} SAR</span>
                        : <span className="text-[11px] text-[#A1E4DB]" title={isRTL ? "لا ينشر المتجر مستويات المخزون ولا عدد المبيعات" : "This store publishes neither stock levels nor sales counts"}>{isRTL ? "غير قابل للقياس" : "Not measurable"}</span>}
                    </td>
                    <td className="py-2 pe-2 text-end text-[#A1E4DB]">{s.revenue_30d != null ? `${s.revenue_days_measured}/30` : "—"}</td>
                    <td className="py-2 pe-2 text-end text-white">{fmt(s.products)}</td>
                    <td className="py-2 text-end text-[#A1E4DB]">{s.in_stock_pct != null ? `${s.in_stock_pct}%` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-[#A1E4DB] mt-2">
              {isRTL ? "الإيرادات تقديرية من التغير اليومي في المخزون أو عدّاد المبيعات العام، وليست فواتير."
                     : "Revenue is estimated from day-to-day stock changes or the store's public sold counter, not from invoices."}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
