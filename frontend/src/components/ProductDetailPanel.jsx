import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend, ReferenceLine, ReferenceArea } from "recharts";
import { useSeasonalEvents, SeasonalToggle, SeasonalChartElements } from "@/components/SeasonalAnnotations";

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
  const seasonal = useSeasonalEvents();

  useEffect(() => {
    if (!sku) { setProduct(null); return; }
    setLoading(true);
    Promise.all([
      api.get(`/products/${sku}`),
      api.get(`/products/${sku}/history?days=30`),
      api.get(`/products/${sku}/velocity?days=14`),
    ]).then(([p, h, v]) => {
      setProduct(p.data);
      setHistory(h.data.history || {});
      setVelocity(v.data);
    }).catch(console.error).finally(() => setLoading(false));
  }, [sku]);

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
      <SheetContent className="w-[520px] sm:max-w-[520px] overflow-y-auto p-0" data-testid="product-detail-panel">
        <SheetHeader className="px-5 py-4 border-b border-white/10 sticky top-0 bg-[#0A2728]/80 z-10">
          <SheetTitle className="text-base font-bold text-white">
            {product?.name_ar || t("loading")}
          </SheetTitle>
        </SheetHeader>

        {loading ? (
          <div className="p-5 text-sm text-[#A1E4DB]">{t("loading")}</div>
        ) : product ? (
          <div className="p-5 space-y-5">
            {/* Product Header */}
            <div>
              <p className="text-sm text-[#A1E4DB]">{product.name_en}</p>
              <div className="flex items-center gap-2 mt-1.5">
                <Badge variant="outline" className="text-[10px] font-mono">{product.sku}</Badge>
                <Badge variant="secondary" className="text-[10px] capitalize">{product.category}</Badge>
                <Badge variant="secondary" className="text-[10px]">{product.brand}</Badge>
              </div>
            </div>

            {/* KPIs */}
            {product.price_range && (
              <div className="grid grid-cols-3 gap-3">
                <div className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{t("price_range")}</p>
                  <p className="text-sm font-bold text-white mt-0.5">{product.price_range.min}-{product.price_range.max} SAR</p>
                </div>
                <div className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{t("market_avg")}</p>
                  <p className="text-sm font-bold text-white mt-0.5">{product.price_range.avg} SAR</p>
                </div>
                <div className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{t("total_volume")}</p>
                  <p className="text-sm font-bold text-white mt-0.5">{product.total_volume}</p>
                </div>
              </div>
            )}

            {/* Confidence Badge */}
            {product.store_prices?.[0] && (
              <div>
                <TierBadge tier={product.store_prices[0].source_tier} score={product.store_prices[0].confidence_score} />
              </div>
            )}

            {/* Price by Store Table */}
            <div>
              <h4 className="text-xs font-semibold text-white mb-2">{t("stores_carrying")}</h4>
              <div className="border border-white/10 rounded-md overflow-hidden">
                <Table className="dense-table">
                  <TableHeader>
                    <TableRow className="bg-[#0A2728]/80/5">
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Store</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Price</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Stock</TableHead>
                      <TableHead className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB]">Tier</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {product.store_prices?.map((sp) => (
                      <TableRow key={sp.store_id}>
                        <TableCell className="text-xs font-medium">{sp.store_name}</TableCell>
                        <TableCell>
                          <span className="text-xs font-semibold">{sp.price} SAR</span>
                          {sp.discount_pct > 0 && <span className="text-[10px] text-green-600 ms-1">-{sp.discount_pct}%</span>}
                          {sp.tier4_member_price && sp.tier4_member_price !== sp.price && (
                            <div className="text-[10px] text-emerald-600 font-medium mt-0.5">Member: {sp.tier4_member_price} SAR</div>
                          )}
                          {sp.tier4_flash_sale && (
                            <Badge variant="outline" className="text-[8px] mt-0.5 bg-red-50 text-red-600 border-red-200">Flash Sale{sp.tier4_flash_price ? ` ${sp.tier4_flash_price} SAR` : ""}</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <StockBadge signal={sp.stock_signal} />
                          {sp.tier4_qty_exact != null && (
                            <span className="text-[10px] text-emerald-600 ms-1 font-medium">{sp.tier4_qty_exact} exact</span>
                          )}
                        </TableCell>
                        <TableCell><span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${sp.source_tier === 4 ? "bg-emerald-50 text-emerald-700" : `tier-${sp.source_tier}`}`}>T{sp.source_tier}</span></TableCell>
                      </TableRow>
                    ))}
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
