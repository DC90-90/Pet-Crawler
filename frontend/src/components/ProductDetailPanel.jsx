import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { X, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine, ReferenceArea } from "recharts";
import { useSeasonalEvents, SeasonalToggle, SeasonalChartElements } from "@/components/SeasonalAnnotations";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import FreshnessBadge, { isStale } from "@/components/FreshnessBadge";
import { MarketPositionBar } from "@/components/MarketPosition";

const STORE_COLORS = ["#002DF5", "#00C853", "#FF3B30", "#FFB300", "#8B5CF6", "#EC4899", "#06B6D4"];

function StockBadge({ signal }) {
  const cls = { HIGH: "stock-high", MEDIUM: "stock-medium", LOW: "stock-low", OOS: "stock-oos", AVAIL: "stock-high" };
  const labelMap = { AVAIL: "IN STOCK" };
  return <span className={`text-xs font-bold ${cls[signal] || ""}`}>{labelMap[signal] || signal}</span>;
}

function TierBadge({ tier, score }) {
  const cls = { 1: "tier-1", 2: "tier-2", 3: "tier-3", 4: "bg-emerald-50 text-emerald-700" };
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded ${cls[tier] || "tier-2"}`}>
      {tier === 4 ? "T4 Authenticated" : `Tier ${tier}`} - {score}% confidence
    </span>
  );
}

export default function ProductDetailPanel({ sku, onClose }) {
  const { t } = useI18n();
  const [product, setProduct] = useState(null);
  const [history, setHistory] = useState({});
  const [velocity, setVelocity] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const seasonal = useSeasonalEvents();

  // iter73y — the request used to have NO timeout and a bare
  // `.catch(console.error)`, so any backend stall left the panel on
  // "Loading…" forever with nothing the user could do. Now it fails visibly
  // and can be retried.
  useEffect(() => {
    if (!sku) { setProduct(null); setError(null); return; }
    let alive = true;
    setLoading(true);
    setError(null);
    api.get(`/products/${encodeURIComponent(sku)}/full?days=30`, { timeout: 45000 })
      .then(({ data }) => {
        if (!alive) return;
        setProduct(data);
        setHistory(data.history || {});
        setVelocity(data.velocity || null);
      })
      .catch((err) => {
        if (!alive) return;
        console.error(err);
        setProduct(null);
        setError(
          err?.code === "ECONNABORTED"
            ? t("detail_timeout")
            : err?.response?.data?.detail || t("detail_failed")
        );
      })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [sku, attempt]);   // eslint-disable-line react-hooks/exhaustive-deps

  // Build price history chart data
  const buildHistoryData = () => {
    const dateMap = {};
    const stores = Object.keys(history);
    stores.forEach((store) => {
      history[store].forEach((pt) => {
        const date = pt.date.split("T")[0];
        if (!dateMap[date]) dateMap[date] = { date };
        dateMap[date][store] = pt.price;
      });
    });
    return Object.values(dateMap).sort((a, b) => a.date.localeCompare(b.date));
  };

  const historyData = buildHistoryData();
  const storeNames = Object.keys(history);

  return (
    <Sheet open={!!sku} onOpenChange={(open) => { if (!open) onClose(); }}>
      <SheetContent aria-describedby={undefined} className="w-[520px] sm:max-w-[520px] overflow-y-auto p-0" data-testid="product-detail-panel">
        <SheetHeader className="px-5 py-4 border-b border-white/10 sticky top-0 bg-[#0A2728]/80 z-10">
          <SheetTitle className="text-base font-bold text-white inline-flex items-center gap-2">
            <MineBadge sku={sku} />
            {product?.name_ar || t("loading")}
          </SheetTitle>
        </SheetHeader>

        {loading ? (
          <div className="p-5 text-sm text-[#A1E4DB]" data-testid="product-detail-loading">{t("loading")}</div>
        ) : error ? (
          <div className="p-5 space-y-3" data-testid="product-detail-error">
            <p className="text-sm text-red-300">{error}</p>
            <Button
              size="sm"
              variant="outline"
              data-testid="product-detail-retry-btn"
              onClick={() => setAttempt((n) => n + 1)}
            >
              {t("retry")}
            </Button>
          </div>
        ) : product ? (
          <div className="p-5 space-y-5">
            {/* Product Header */}
            <div>
              <p className="text-sm text-[#A1E4DB]">{product.name_en}</p>
              <SkuLine sku={product.sku} barcode={product.barcode} size="sm" className="mt-1" />
              <div className="flex items-center gap-2 mt-1.5">
                <Badge variant="secondary" className="text-[10px] capitalize">{product.category}</Badge>
                <Badge variant="secondary" className="text-[10px]">{product.brand}</Badge>
              </div>
            </div>

            {/* KPIs */}
            <div className="text-sm" data-testid="product-detail-own-price">
              <span className="text-[#A1E4DB]">{t("col_price")}: </span>
              <span className="font-semibold text-white">{product.price ?? "—"} SAR</span>
              {product.price_status === "unavailable" && <p className="text-xs text-[#A1E4DB] mt-1" data-testid="product-detail-price-unavailable">{t("current_price_unavailable")}</p>}
            </div>
            {product.price_range && (
              <div className="grid grid-cols-3 gap-3">
                <div className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{t("price_range")}</p>
                  <p className="text-sm font-bold text-white mt-0.5" data-testid="product-detail-price-range">{product.price_range.min == null || product.price_range.max == null ? "—" : `${product.price_range.min}–${product.price_range.max}`} SAR</p>
                </div>
                <div className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{t("market_avg")}</p>
                  <p className="text-sm font-bold text-white mt-0.5" data-testid="product-detail-market-average">{product.price_range.avg ?? "—"} SAR</p>
                </div>
                <div className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{t("total_volume")}</p>
                  <p className="text-sm font-bold text-white mt-0.5" data-testid="product-detail-volume">{product.total_volume ?? "—"}</p>
                </div>
              </div>
            )}

            {/* Market Position bar (Feb 2026) */}
            {product.market_position && (
              <div>
                <MarketPositionBar mp={product.market_position} />
                {product.market_position.stale_sellers > 0 && (
                  <p className="text-[10px] text-[#A1E4DB]/70 mt-1" data-testid="mp-stale-note">
                    {product.market_position.stale_sellers} of {product.market_position.total_sellers} prices are older than 7 days — see "price as of" below.
                  </p>
                )}
              </div>
            )}

            {/* Confidence Badge */}
            {product.store_prices?.[0]?.price_status === "live" && product.store_prices[0].source_tier != null && (
              <div>
                <TierBadge tier={product.store_prices[0].source_tier} score={product.store_prices[0].confidence_score} />
              </div>
            )}

            {/* Price by Store Table */}
            <div>
              <div className="flex items-baseline justify-between mb-2">
                <h4 className="text-xs font-semibold text-white">
                  {t("stores_carrying")}
                  {product.seller_count != null && (
                    <span className="ms-1.5 font-normal text-[#A1E4DB]" data-testid="seller-count">({product.seller_count})</span>
                  )}
                </h4>
                {product.seller_summary && (
                  <span className="text-[10px] text-[#A1E4DB]/70" data-testid="seller-summary">
                    {product.seller_summary.live} live
                    {product.seller_summary.stale > 0 && ` · ${product.seller_summary.stale} stale`}
                    {product.seller_summary.oos > 0 && ` · ${product.seller_summary.oos} OOS`}
                  </span>
                )}
              </div>
              <div className="border border-white/10 rounded-md overflow-hidden">
                <Table className="dense-table product-detail-offers" data-testid="product-detail-offer-table">
                  <TableHeader>
                    <TableRow className="bg-[#0A2728]/80/5">
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Store</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Price</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">30-day Trend</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Stock</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Tier</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Freshness</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {product.store_prices?.map((sp) => {
                      const series = (history?.[sp.store_name] || []).map((h) => h.price).filter((p) => p > 0);
                      const minP = series.length ? Math.min(...series) : 0;
                      const maxP = series.length ? Math.max(...series) : 0;
                      const range = maxP - minP || 1;
                      const points = series.length > 1
                        ? series.map((p, i) => `${(i / (series.length - 1)) * 100},${30 - ((p - minP) / range) * 28 - 1}`).join(" ")
                        : "";
                      const trendPct = series.length > 1 ? Math.round(((series[series.length - 1] - series[0]) / series[0]) * 100) : 0;
                      // iter60 — staleness comes from the backend (7-day rule,
                      // same one that labels the row) and only DIMS the row. It
                      // never removes it: the client needs to know who carries
                      // the product even when our last look is old.
                      const stale = sp.is_stale != null ? sp.is_stale : isStale(sp.crawled_at);
                      return (
                      <TableRow key={sp.store_id} style={stale ? { opacity: 0.7 } : undefined} data-stale={stale} data-testid={`store-row-${sp.store_id}`}>
                        <TableCell className="text-xs font-medium" data-label="Store">
                          {sp.product_url ? (
                            <a href={sp.product_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-white hover:text-[#6AC1B5] transition-colors" data-testid={`store-link-${sp.store_id}`} title={sp.product_url}>
                              {sp.store_name}
                              <ExternalLink className="w-3 h-3 opacity-60" />
                            </a>
                          ) : (sp.store_name)}
                          {sp.excluded_reason && <p className="mt-1 text-[10px] text-amber-400" data-testid={`detail-offer-exclusion-${sp.store_id}`}>{sp.excluded_reason.replaceAll("_", " ")}</p>}
                          {sp.is_own_store && (
                            <span className="ms-1.5 inline-flex items-center text-[8px] font-bold tracking-[0.1em] uppercase px-1 py-0.5 rounded bg-[#1E988E]/15 text-[#1E988E] border border-[#1E988E]/30" data-testid={`my-store-tag-${sp.store_id}`}>My Store</span>
                          )}
                          {sp.match_source === "matched" && sp.sku && (
                            <div className="text-[9px] text-[#A1E4DB]/60 font-mono mt-0.5" data-testid={`store-matched-sku-${sp.store_id}`} title="Linked by the matching engine, not by an identical SKU">
                              matched · {sp.sku}
                            </div>
                          )}
                        </TableCell>
                        <TableCell data-label="Price" data-testid={`detail-offer-price-${sp.store_id}`}>
                          <span className="text-xs font-semibold">{sp.price ?? "—"} SAR</span>
                          {stale && sp.price_as_of && (
                            <div className="text-[9px] text-[#FBBF24]/90 mt-0.5" data-testid={`store-price-asof-${sp.store_id}`}>
                              as of {sp.price_as_of}
                            </div>
                          )}
                          {sp.discount_pct > 0 && <span className="text-[10px] text-green-600 ms-1">-{sp.discount_pct}%</span>}
                          {sp.tier4_member_price && sp.tier4_member_price !== sp.price && (
                            <div className="text-[10px] text-emerald-600 font-medium mt-0.5">Member: {sp.tier4_member_price} SAR</div>
                          )}
                          {sp.tier4_flash_sale && (
                            <Badge variant="outline" className="text-[8px] mt-0.5 bg-red-50 text-red-600 border-red-200">Flash Sale{sp.tier4_flash_price ? ` ${sp.tier4_flash_price} SAR` : ""}</Badge>
                          )}
                        </TableCell>
                        <TableCell data-label="30-day trend">
                          {points ? (
                            <div className="inline-flex items-center gap-2" data-testid={`store-trend-${sp.store_id}`}>
                              <svg width="100" height="30" viewBox="0 0 100 30" className="overflow-visible">
                                <polyline fill="none" stroke={trendPct > 5 ? "#EF4444" : trendPct < -5 ? "#10B981" : "#6AC1B5"} strokeWidth="1.5" points={points} />
                              </svg>
                              <span className={`text-[10px] font-mono ${trendPct > 0 ? "text-red-400" : trendPct < 0 ? "text-emerald-400" : "text-[#A1E4DB]"}`}>{trendPct > 0 ? "+" : ""}{trendPct}%</span>
                            </div>
                          ) : (<span className="text-[10px] text-[#A1E4DB]/60">—</span>)}
                        </TableCell>
                        <TableCell data-stock-status={sp.stock_status} data-label="Stock" data-testid={`detail-offer-stock-${sp.store_id}`}>
                          <StockBadge signal={sp.stock_signal} />
                          {sp.tier4_qty_exact != null && (
                            <span className="text-[10px] text-emerald-600 ms-1 font-medium">{sp.tier4_qty_exact} exact</span>
                          )}
                        </TableCell>
                        <TableCell data-label="Tier"><span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${sp.source_tier === 4 ? "bg-emerald-50 text-emerald-700" : `tier-${sp.source_tier}`}`}>{sp.source_tier == null ? "—" : `T${sp.source_tier}`}</span></TableCell>
                        <TableCell data-label="Last observation"><FreshnessBadge crawledAt={sp.last_crawl_at || sp.crawled_at} testIdPrefix={`store-fresh-${sp.store_id}`} /></TableCell>
                      </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              </div>
            </div>

            {/* Price History Chart */}
            {historyData.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-xs font-semibold text-white">{t("chart_price_history")}</h4>
                  <SeasonalToggle show={seasonal.show} toggle={seasonal.toggle} />
                </div>
                <div className="border border-white/10 rounded-md p-3">
                  <ResponsiveContainer width="100%" height={180}>
                    <LineChart data={historyData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d) => d.slice(5)} />
                      <YAxis tick={{ fontSize: 9 }} />
                      <Tooltip contentStyle={{ fontSize: 11 }} />
                      <Legend wrapperStyle={{ fontSize: 10 }} />
                      <SeasonalChartElements show={seasonal.show} />
                      {storeNames.map((store, i) => (
                        <Line key={store} type="monotone" dataKey={store} stroke={STORE_COLORS[i % STORE_COLORS.length]} strokeWidth={2} dot={false} connectNulls />
                      ))}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Velocity Chart */}
            {velocity && velocity.velocity?.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-white mb-2">
                  {t("chart_velocity")} <span className="font-normal text-[#A1E4DB]">({velocity.avg_daily} {t("units_day")} avg)</span>
                </h4>
                <div className="border border-white/10 rounded-md p-3">
                  <ResponsiveContainer width="100%" height={140}>
                    <BarChart data={velocity.velocity}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                      <XAxis dataKey="date" tick={{ fontSize: 9 }} tickFormatter={(d) => d.slice(5)} />
                      <YAxis tick={{ fontSize: 9 }} />
                      <Tooltip contentStyle={{ fontSize: 11 }} />
                      <Bar dataKey="units" fill="#002DF5" radius={[2, 2, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        ) : null}
      </SheetContent>
    </Sheet>
  );
}
