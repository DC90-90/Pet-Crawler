import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";

const SCORE_COLORS = ["#FF3B30", "#FF6D00", "#FFB300", "#00C853", "#002DF5", "#8B5CF6", "#EC4899"];

export default function DiscountsPage() {
  const { t } = useI18n();
  const [topPct, setTopPct] = useState([]);
  const [topAmt, setTopAmt] = useState([]);
  const [timeline, setTimeline] = useState({ timeline: [], stores: [] });
  const [aggression, setAggression] = useState([]);
  const [storeFilter, setStoreFilter] = useState("all");
  const [catFilter, setCatFilter] = useState("all");
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.get("/discounts/top-pct", { params: { store_id: storeFilter !== "all" ? storeFilter : undefined, category: catFilter !== "all" ? catFilter : undefined } }),
      api.get("/discounts/top-amount", { params: { store_id: storeFilter !== "all" ? storeFilter : undefined, category: catFilter !== "all" ? catFilter : undefined } }),
      api.get("/discounts/timeline"),
      api.get("/discounts/aggression"),
      api.get("/stores"),
    ]).then(([p, a, tl, ag, st]) => {
      setTopPct(p.data); setTopAmt(a.data); setTimeline(tl.data); setAggression(ag.data);
      const stData = st.data;
      setStores(Array.isArray(stData) ? stData : stData.stores || []);
    }).catch(console.error).finally(() => setLoading(false));
  }, [storeFilter, catFilter]);

  if (loading) return <div className="p-6 text-sm text-[#A1E4DB]">{t("loading")}</div>;

  return (
    <div className="p-6 space-y-5" data-testid="discounts-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Discounts</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">Track competitor discount strategies</p>
        </div>
        <div className="flex gap-2">
          <Select value={storeFilter} onValueChange={setStoreFilter}>
            <SelectTrigger className="w-[150px] h-8 text-xs rounded-md" data-testid="disc-store-filter"><SelectValue placeholder="All Stores" /></SelectTrigger>
            <SelectContent><SelectItem value="all">All Stores</SelectItem>{stores.map((s) => <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>)}</SelectContent>
          </Select>
          <Select value={catFilter} onValueChange={setCatFilter}>
            <SelectTrigger className="w-[150px] h-8 text-xs rounded-md" data-testid="disc-cat-filter"><SelectValue placeholder="All Categories" /></SelectTrigger>
            <SelectContent><SelectItem value="all">All Categories</SelectItem>{["cat_food","dog_food","accessories","grooming","healthcare","litter","toys"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
          </Select>
        </div>
      </div>

      {/* Aggression Leaderboard */}
      <div className="glass-card rounded-md p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Store Discount Aggression Leaderboard</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {aggression.map((a, i) => (
            <div key={a.store} className="border border-white/10 rounded-md p-3 hover:shadow-sm transition-all" data-testid={`aggression-${a.store}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 bg-[#1E988E] text-white text-[10px] font-bold rounded flex items-center justify-center">{a.store[0]}</div>
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

      {/* Top Discounts Tabs */}
      <Tabs defaultValue="pct" className="w-full">
        <TabsList className="bg-[#0A2728]/80/5 p-1 rounded-md">
          <TabsTrigger value="pct" className="text-xs rounded-md data-[state=active]:bg-[#0A2728]/80 data-[state=active]:shadow-sm">By Percentage</TabsTrigger>
          <TabsTrigger value="amount" className="text-xs rounded-md data-[state=active]:bg-[#0A2728]/80 data-[state=active]:shadow-sm">By SAR Saved</TabsTrigger>
        </TabsList>
        {["pct", "amount"].map((tab) => {
          const data = tab === "pct" ? topPct : topAmt;
          return (
            <TabsContent key={tab} value={tab} className="mt-3">
              <div className="glass-card rounded-md overflow-hidden">
                <Table className="dense-table">
                  <TableHeader><TableRow className="bg-[#0A2728]/80/5">
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">Product</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">Store</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">Original</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">Sale Price</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">{tab === "pct" ? "Discount %" : "Savings ﷼"}</TableHead>
                    {tab === "pct" && <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#A1E4DB]">On Sale</TableHead>}
                  </TableRow></TableHeader>
                  <TableBody>
                    {data.length === 0 ? <TableRow><TableCell colSpan={6} className="text-center py-8 text-[#A1E4DB] text-xs">{t("no_data")}</TableCell></TableRow> :
                    data.map((d, i) => (
                      <TableRow key={`${d.sku}-${d.store_name}-${i}`}>
                        <TableCell><div><p className="text-xs font-medium text-white">{d.name_ar}</p><p className="text-[10px] text-[#A1E4DB] font-mono">{d.sku}</p></div></TableCell>
                        <TableCell><span className="text-xs">{d.store_name}</span></TableCell>
                        <TableCell><span className="text-xs text-[#A1E4DB] line-through">{d.original_price} ﷼</span></TableCell>
                        <TableCell><span className="text-xs font-semibold text-green-600">{d.price} ﷼</span></TableCell>
                        <TableCell><span className="text-xs font-bold text-red-500">{tab === "pct" ? `${d.discount_pct}%` : `${d.savings_sar} ﷼`}</span></TableCell>
                        {tab === "pct" && <TableCell><span className="text-[10px] text-[#A1E4DB]">{d.days_on_sale}d</span></TableCell>}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </TabsContent>
          );
        })}
      </Tabs>

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
