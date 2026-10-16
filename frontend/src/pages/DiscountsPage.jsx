import { useEffect, useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { MineBadge } from "@/components/MineBadge";
import { SkuLine } from "@/components/SkuLine";
import { StoreLogo } from "@/components/StoreLogo";
import { FacetTabs, StoreTabs, facetCounts, facetMatch, storesOf } from "@/components/MarketTabs";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";

const SCORE_COLORS = ["#FF3B30", "#FF6D00", "#FFB300", "#00C853", "#002DF5", "#8B5CF6", "#EC4899"];

const fetchData = (path, params) => async () => {
  try {
    const { data } = await api.get(path, { params });
    return data;
  } catch (_e) {
    return null;
  }
};

export default function DiscountsPage({ embedded = false }) {
  const { t, isRTL } = useI18n();
  const [store, setStore] = useState("all");
  const [animal, setAnimal] = useState("all");
  const [ptype, setPtype] = useState("all");
  const [sortBy, setSortBy] = useState("pct");
  const [shown, setShown] = useState(50);

  // 16 Oct 2026 — one list of current discounts for every store; the store,
  // animal/type and sort tabs work on it in the browser (was two server lists
  // of 30 and a store dropdown).
  const results = useQueries({
    queries: [
      { queryKey: ["discounts", "current", 300], queryFn: fetchData("/discounts/top-pct", { limit: 300 }) },
      { queryKey: ["discounts", "timeline"], queryFn: fetchData("/discounts/timeline") },
      { queryKey: ["discounts", "aggression"], queryFn: fetchData("/discounts/aggression") },
    ],
  });

  const [curQ, tlQ, aggQ] = results;
  const current = useMemo(() => curQ.data || [], [curQ.data]);
  const timeline = tlQ.data || { timeline: [], stores: [] };
  const aggression = aggQ.data || [];
  const inStore = useMemo(() => current.filter((d) => store === "all" || d.store_id === store), [current, store]);
  const rows = useMemo(() => inStore.filter((d) => facetMatch(d, animal, ptype))
    .sort((a, b) => (sortBy === "pct" ? b.discount_pct - a.discount_pct : b.discount_amount_sar - a.discount_amount_sar)), [inStore, animal, ptype, sortBy]);
  useEffect(() => { setShown(50); }, [store, animal, ptype, sortBy]);
  const loading = results.some((r) => r.isLoading);

  if (loading) return <div className={`${embedded ? "" : "p-6 "}text-sm text-[#A1E4DB]`}>{t("loading")}</div>;
  const failed = results.find((r) => r.isError);

  return (
    <div className={embedded ? "space-y-5" : "p-6 space-y-5"} data-testid="discounts-page">
      {failed && <RequestError id="discounts-request" error={failed.error} onRetry={() => results.filter((r) => r.isError).forEach((r) => r.refetch())} />}
      <div>
        {!embedded && <h1 className="text-2xl font-bold tracking-tight text-white">Discounts</h1>}
        <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "التخفيضات الحالية لدى المنافسين: السعر قبل وبعد، ومنذ متى" : "Competitors' current discounts: price before and after, and since when"}</p>
      </div>

      {/* Aggression Leaderboard */}
      <div className="glass-card rounded-md p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Store Discount Aggression Leaderboard</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {aggression.map((a, i) => (
            <div key={a.store_id || `${a.store}-${i}`} className="border border-white/10 rounded-md p-3 hover:shadow-sm transition-all" data-testid={`aggression-${a.store}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <StoreLogo storeId={a.store_id} name={a.store} size={28} />
                  <span className="text-sm font-medium">{a.store}</span>
                </div>
                <span className={`text-lg font-bold ${a.score > 30 ? "text-red-500" : a.score > 15 ? "text-yellow-600" : "text-green-600"}`}>{a.score}</span>
              </div>
              {a.label && <Badge variant="outline" className={`text-[9px] mb-2 ${a.label === "Most Aggressive" ? "bg-[#EF4444]/10 text-[#EF4444] border-[#EF4444]/20" : a.label === "Most Stable Pricing" ? "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/20" : "bg-[#F59E0B]/10 text-[#F59E0B] border-[#F59E0B]/20"}`}>{a.label}</Badge>}
              <div className="space-y-1 text-[10px] text-[#A1E4DB]">
                <div className="flex justify-between"><span>Avg Depth</span><span className="font-semibold">{a.avg_depth}%</span></div>
                <div className="flex justify-between"><span>Frequency</span><span className="font-semibold">{a.frequency}%</span></div>
                <div className="flex justify-between"><span>Max Discount</span><span className="font-semibold">{a.max_discount}%</span></div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Current discounts */}
      <div className="glass-card rounded-md p-4 space-y-3" data-testid="disc-current">
        <StoreTabs stores={storesOf(current)} value={store} onChange={setStore} prefix="disc-store" />
        <FacetTabs counts={facetCounts(inStore)} animal={animal} ptype={ptype} onAnimal={setAnimal} onType={setPtype} prefix="disc" />
        <div className="flex items-center gap-1">
          <span className="text-[10px] uppercase tracking-[0.12em] text-[#A1E4DB] me-1">{isRTL ? "ترتيب" : "Sort"}</span>
          {[["pct", isRTL ? "نسبة الخصم" : "Discount %"], ["amount", isRTL ? "المبلغ الموفّر" : "SAR saved"]].map(([id, label]) => (
            <button key={id} onClick={() => setSortBy(id)} data-testid={`disc-sort-${id}`}
              className={`text-xs rounded-full h-6 px-2.5 ${sortBy === id ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:bg-white/5"}`}>{label}</button>
          ))}
        </div>
        <div className="overflow-x-auto">
          <Table className="dense-table">
            <TableHeader><TableRow>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{isRTL ? "المنتج" : "Product"}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{isRTL ? "المتجر" : "Store"}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{isRTL ? "قبل" : "Was"}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{isRTL ? "الآن" : "Now"}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{isRTL ? "الخصم" : "Discount"}</TableHead>
              <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{isRTL ? "منذ" : "On sale"}</TableHead>
            </TableRow></TableHeader>
            <TableBody>
              {rows.length === 0 ? <TableRow><TableCell colSpan={6} className="text-center py-8 text-[#A1E4DB] text-xs">{t("no_data")}</TableCell></TableRow> :
              rows.slice(0, shown).map((d, i) => (
                <TableRow key={`${d.offer_id || d.sku}-${d.store_id}-${i}`} data-testid={`disc-row-${i}`}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <div className="w-9 h-9 shrink-0 rounded bg-white overflow-hidden flex items-center justify-center">
                        {d.image_url ? <img src={d.image_url} alt="" loading="lazy" className="max-w-full max-h-full object-contain" /> : null}
                      </div>
                      <div className="min-w-0">
                        <p className="text-xs font-medium text-white truncate max-w-[280px] inline-flex items-center gap-1.5"><MineBadge sku={d.sku} />
                          {d.product_url ? <a href={d.product_url} target="_blank" rel="noopener noreferrer" className="hover:text-[#6AC1B5]">{d.name_ar || d.name_en}</a> : (d.name_ar || d.name_en)}</p>
                        <SkuLine sku={d.sku} barcode={d.barcode} />
                      </div>
                    </div>
                  </TableCell>
                  <TableCell><span className="text-xs inline-flex items-center gap-1.5"><StoreLogo storeId={d.store_id} name={d.store_name} size={16} />{d.store_name}</span></TableCell>
                  <TableCell><span className="text-xs text-[#A1E4DB] line-through">{d.original_price} ﷼</span></TableCell>
                  <TableCell><span className="text-xs font-semibold text-[#10B981]">{d.price} ﷼</span></TableCell>
                  <TableCell><span className="text-xs font-bold text-[#EF4444]">-{d.discount_pct}%</span><span className="block text-[10px] text-[#A1E4DB]">{d.discount_amount_sar} ﷼</span></TableCell>
                  <TableCell><span className="text-[10px] text-[#A1E4DB]">{d.days_on_discount != null ? (isRTL ? `${d.days_on_discount} يوم` : `${d.days_on_discount}d+`) : "—"}</span></TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        {rows.length > shown && (
          <button onClick={() => setShown((n) => n + 50)} className="text-xs text-[#6AC1B5] hover:text-white" data-testid="disc-more">
            {isRTL ? `عرض المزيد (${rows.length - shown})` : `Show more (${rows.length - shown})`}
          </button>
        )}
      </div>

      {/* Discount Timeline Heatmap */}
      {timeline.timeline.length > 0 && (
        <div className="glass-card rounded-md p-5">
          <h3 className="text-sm font-semibold text-white mb-3">Discount Timeline (90 Days)</h3>
          <ResponsiveContainer width="100%" height={Math.max(180, timeline.stores.length * 35 + 40)}>
            <BarChart data={timeline.timeline} layout="vertical" margin={{ left: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis type="number" tick={{ fontSize: 9, fill: "#A1E4DB" }} />
              <YAxis type="category" dataKey="week" tick={{ fontSize: 8, fill: "#A1E4DB" }} width={70} tickFormatter={(w) => w.slice(-3)} />
              <Tooltip contentStyle={{ fontSize: 11, background: "#104745", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8 }} labelStyle={{ color: "#A1E4DB" }} />
              {timeline.stores.map((s, i) => (
                <Bar key={s} dataKey={s} stackId="a" fill={SCORE_COLORS[i % SCORE_COLORS.length]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
