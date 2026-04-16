import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Zap, RefreshCw, TrendingDown, AlertTriangle, Shield, Trophy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";

const RANGE_OPTIONS = [7, 14, 30];
const BADGE_CFG = {
  quick_win: { label: "Quick Win", icon: Trophy, cls: "bg-green-50 text-green-700 border-green-200" },
  overpriced_risk: { label: "Overpriced Risk", icon: AlertTriangle, cls: "bg-red-50 text-red-700 border-red-200" },
  overpriced: { label: "Overpriced", icon: TrendingDown, cls: "bg-yellow-50 text-yellow-700 border-yellow-200" },
};

export default function ScannerPage() {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(14);
  const [selectedOpp, setSelectedOpp] = useState(null);

  const fetchData = useCallback(() => {
    setLoading(true);
    api.get("/scanner/opportunities", { params: { days } })
      .then((r) => setData(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [days]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading || !data) return <div className="p-6 text-sm text-[#9CA3AF]">{t("loading")}</div>;
  const { summary, opportunities, well_positioned, undercut } = data;

  // Build price distribution for selected opportunity
  const buildPriceDist = () => {
    if (!selectedOpp) return [];
    // Find all store prices for this SKU from opportunities
    const related = opportunities.filter((o) => o.sku === selectedOpp.sku);
    return related.map((r) => ({ store: r.store_name, price: r.my_price }));
  };

  return (
    <div className="p-6 space-y-5" data-testid="scanner-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0A0A0A]">Price Opportunity Scanner</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">Find revenue you're leaving on the table</p>
        </div>
        <div className="flex gap-2 items-center">
          <div className="flex gap-1" data-testid="scanner-range">
            {RANGE_OPTIONS.map((d) => (
              <Button key={d} size="sm" variant={days === d ? "default" : "outline"}
                onClick={() => setDays(d)}
                className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#002DF5] text-white" : ""}`}>{d}D</Button>
            ))}
          </div>
          <Button variant="outline" size="sm" onClick={fetchData} className="rounded-md text-xs h-7" data-testid="scanner-refresh">
            <RefreshCw className="w-3 h-3 me-1" />Refresh
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="kpi-card border-s-4 border-s-red-500">
          <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">Overpriced Products (10%+)</p>
          <p className="text-2xl font-bold text-[#0A0A0A] mt-1">{summary.overpriced_count}</p>
          <p className="text-[10px] text-[#9CA3AF] mt-0.5">products priced above market</p>
        </div>
        <div className="kpi-card border-s-4 border-s-green-500">
          <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">Potential Revenue Uplift</p>
          <p className="text-2xl font-bold text-green-600 mt-1">{summary.total_uplift_sar.toLocaleString()} ﷼</p>
          <p className="text-[10px] text-[#9CA3AF] mt-0.5">if you matched market prices</p>
        </div>
        <div className="kpi-card border-s-4 border-s-yellow-500">
          <p className="text-[10px] uppercase tracking-[0.15em] font-semibold text-[#9CA3AF]">Zero Sales + Overpriced</p>
          <p className="text-2xl font-bold text-yellow-600 mt-1">{summary.zero_sales_overpriced}</p>
          <p className="text-[10px] text-[#9CA3AF] mt-0.5">immediate action recommended</p>
        </div>
      </div>

      {/* Opportunities Table */}
      <div className="bg-white border border-[#E5E7EB] rounded-md overflow-hidden">
        <div className="px-4 py-3 border-b border-[#E5E7EB] bg-[#F9FAFB]">
          <h3 className="text-sm font-semibold text-[#0A0A0A]">Overpriced Products — Sorted by Revenue Uplift</h3>
        </div>
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-[#F9FAFB]">
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Product</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Store</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">My Price</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Market Low</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Gap %</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Sales ({days}d)</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Revenue Uplift</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Badge</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {opportunities.length === 0 ? (
              <TableRow><TableCell colSpan={8} className="text-center py-12"><Shield className="w-8 h-8 text-green-400 mx-auto mb-2" /><p className="text-sm text-green-600 font-medium">All products well-positioned!</p></TableCell></TableRow>
            ) : opportunities.map((o, i) => {
              const bcfg = BADGE_CFG[o.badge] || BADGE_CFG.overpriced;
              const BIcon = bcfg.icon;
              return (
                <TableRow key={`${o.sku}-${o.store_id}-${i}`} className="cursor-pointer hover:bg-[#F9FAFB]" onClick={() => setSelectedOpp(o)} data-testid={`opp-row-${i}`}>
                  <TableCell><div><p className="text-xs font-medium text-[#0A0A0A]">{o.name_ar}</p><p className="text-[10px] text-[#9CA3AF] font-mono">{o.sku}</p></div></TableCell>
                  <TableCell><span className="text-xs">{o.store_name}</span></TableCell>
                  <TableCell><span className="text-sm font-semibold text-red-500">{o.my_price} ﷼</span></TableCell>
                  <TableCell><span className="text-sm font-semibold text-green-600">{o.market_lowest} ﷼</span></TableCell>
                  <TableCell><span className="text-xs font-bold text-red-500">+{o.gap_pct}%</span></TableCell>
                  <TableCell><span className="text-xs">{o.units_sold}</span></TableCell>
                  <TableCell><span className="text-sm font-bold text-green-600">{o.revenue_uplift.toLocaleString()} ﷼</span></TableCell>
                  <TableCell><Badge variant="outline" className={`text-[9px] gap-1 ${bcfg.cls}`}><BIcon className="w-2.5 h-2.5" />{bcfg.label}</Badge></TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Well Positioned + Undercut */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3 flex items-center gap-1.5"><Shield className="w-4 h-4 text-green-500" />Well Positioned ({well_positioned.length})</h3>
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {well_positioned.slice(0, 10).map((w) => (
              <div key={`wp-${w.sku}-${w.store_name}`} className="flex items-center justify-between py-1.5 border-b border-[#F3F4F6] last:border-0">
                <div><p className="text-xs font-medium text-[#0A0A0A]">{w.name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{w.store_name}</p></div>
                <div className="text-end"><p className="text-xs font-semibold">{w.price} ﷼</p><p className="text-[10px] text-[#9CA3AF]">avg {w.market_avg} ﷼</p></div>
              </div>
            ))}
            {well_positioned.length === 0 && <p className="text-xs text-[#9CA3AF]">{t("no_data")}</p>}
          </div>
        </div>
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3 flex items-center gap-1.5"><Zap className="w-4 h-4 text-[#002DF5]" />Undercut Opportunities ({undercut.length})</h3>
          <div className="space-y-2 max-h-[250px] overflow-y-auto">
            {undercut.slice(0, 10).map((u) => (
              <div key={`uc-${u.sku}-${u.store_name}`} className="flex items-center justify-between py-1.5 border-b border-[#F3F4F6] last:border-0">
                <div><p className="text-xs font-medium text-[#0A0A0A]">{u.name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{u.store_name} — lowest price</p></div>
                <div className="text-end"><p className="text-xs font-semibold text-[#002DF5]">{u.price} ﷼</p><p className="text-[10px] text-[#9CA3AF]">mkt avg {u.market_avg} ﷼</p></div>
              </div>
            ))}
            {undercut.length === 0 && <p className="text-xs text-[#9CA3AF]">{t("no_data")}</p>}
          </div>
        </div>
      </div>

      {/* Detail Sheet */}
      <Sheet open={!!selectedOpp} onOpenChange={(o) => { if (!o) setSelectedOpp(null); }}>
        <SheetContent className="w-[480px] sm:max-w-[480px] overflow-y-auto p-0" data-testid="opp-detail-panel">
          <SheetHeader className="px-5 py-4 border-b border-[#E5E7EB] sticky top-0 bg-white z-10">
            <SheetTitle className="text-base font-bold">{selectedOpp?.name_ar}</SheetTitle>
          </SheetHeader>
          {selectedOpp && (
            <div className="p-5 space-y-5">
              <div className="flex gap-2"><Badge variant="outline" className="text-[10px] font-mono">{selectedOpp.sku}</Badge><Badge variant="secondary" className="text-[10px]">{selectedOpp.category}</Badge></div>
              <div className="grid grid-cols-2 gap-3">
                <div className="kpi-card !p-3"><p className="text-[9px] uppercase text-[#9CA3AF]">Your Price</p><p className="text-lg font-bold text-red-500">{selectedOpp.my_price} ﷼</p></div>
                <div className="kpi-card !p-3"><p className="text-[9px] uppercase text-[#9CA3AF]">Market Lowest</p><p className="text-lg font-bold text-green-600">{selectedOpp.market_lowest} ﷼</p></div>
              </div>
              <div className="bg-[#F9FAFB] rounded-md p-3 space-y-2 text-xs">
                <p>Lower to <span className="font-bold text-green-600">{selectedOpp.market_lowest} ﷼</span> to become the cheapest seller</p>
                <p>Lower to <span className="font-bold text-[#002DF5]">{selectedOpp.market_avg} ﷼</span> to match market average</p>
                <p>Estimated uplift: <span className="font-bold text-green-600">{selectedOpp.revenue_uplift.toLocaleString()} ﷼</span> per period</p>
              </div>
              {/* Price Distribution */}
              {buildPriceDist().length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold mb-2">Price Distribution — All Sellers</h4>
                  <ResponsiveContainer width="100%" height={140}>
                    <BarChart data={buildPriceDist()}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                      <XAxis dataKey="store" tick={{ fontSize: 9 }} />
                      <YAxis tick={{ fontSize: 9 }} />
                      <Tooltip contentStyle={{ fontSize: 11 }} formatter={(v) => [`${v} ﷼`, "Price"]} />
                      <Bar dataKey="price" radius={[2, 2, 0, 0]}>
                        {buildPriceDist().map((entry) => (
                          <Cell key={entry.store} fill={entry.store === selectedOpp.store_name ? "#FF3B30" : "#002DF5"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
