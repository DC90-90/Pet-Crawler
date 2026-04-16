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

  if (loading) return <div className="p-6 text-sm text-[#9CA3AF]">{t("loading")}</div>;

  return (
    <div className="p-6 space-y-5" data-testid="discounts-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0A0A0A]">Discounts</h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">Track competitor discount strategies</p>
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
      <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
        <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">Store Discount Aggression Leaderboard</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {aggression.map((a, i) => (
            <div key={a.store} className="border border-[#E5E7EB] rounded-md p-3 hover:shadow-sm transition-all" data-testid={`aggression-${a.store}`}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 bg-[#002DF5] text-white text-[10px] font-bold rounded flex items-center justify-center">{a.store[0]}</div>
                  <span className="text-sm font-medium">{a.store}</span>
                </div>
                <span className={`text-lg font-bold ${a.score > 30 ? "text-red-500" : a.score > 15 ? "text-yellow-600" : "text-green-600"}`}>{a.score}</span>
              </div>
              {a.label && <Badge variant="outline" className={`text-[9px] mb-2 ${a.label === "Most Aggressive" ? "bg-red-50 text-red-600 border-red-200" : a.label === "Most Stable Pricing" ? "bg-green-50 text-green-600 border-green-200" : "bg-yellow-50 text-yellow-600 border-yellow-200"}`}>{a.label}</Badge>}
              <div className="space-y-1 text-[10px] text-[#4B5563]">
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
        <TabsList className="bg-[#F3F4F6] p-1 rounded-md">
          <TabsTrigger value="pct" className="text-xs rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm">By Percentage</TabsTrigger>
          <TabsTrigger value="amount" className="text-xs rounded-md data-[state=active]:bg-white data-[state=active]:shadow-sm">By SAR Saved</TabsTrigger>
        </TabsList>
        {["pct", "amount"].map((tab) => {
          const data = tab === "pct" ? topPct : topAmt;
          return (
            <TabsContent key={tab} value={tab} className="mt-3">
              <div className="bg-white border border-[#E5E7EB] rounded-md overflow-hidden">
                <Table className="dense-table">
                  <TableHeader><TableRow className="bg-[#F9FAFB]">
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Product</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Store</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Original</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">Sale Price</TableHead>
                    <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">{tab === "pct" ? "Discount %" : "Savings ﷼"}</TableHead>
                    {tab === "pct" && <TableHead className="text-[10px] uppercase tracking-[0.12em] font-semibold text-[#9CA3AF]">On Sale</TableHead>}
                  </TableRow></TableHeader>
                  <TableBody>
                    {data.length === 0 ? <TableRow><TableCell colSpan={6} className="text-center py-8 text-[#9CA3AF] text-xs">{t("no_data")}</TableCell></TableRow> :
                    data.map((d, i) => (
                      <TableRow key={`${d.sku}-${d.store_name}-${i}`}>
                        <TableCell><div><p className="text-xs font-medium text-[#0A0A0A]">{d.name_ar}</p><p className="text-[10px] text-[#9CA3AF] font-mono">{d.sku}</p></div></TableCell>
                        <TableCell><span className="text-xs">{d.store_name}</span></TableCell>
                        <TableCell><span className="text-xs text-[#9CA3AF] line-through">{d.original_price} ﷼</span></TableCell>
                        <TableCell><span className="text-xs font-semibold text-green-600">{d.price} ﷼</span></TableCell>
                        <TableCell><span className="text-xs font-bold text-red-500">{tab === "pct" ? `${d.discount_pct}%` : `${d.savings_sar} ﷼`}</span></TableCell>
                        {tab === "pct" && <TableCell><span className="text-[10px] text-[#9CA3AF]">{d.days_on_sale}d</span></TableCell>}
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
        <div className="bg-white border border-[#E5E7EB] rounded-md p-5">
          <h3 className="text-sm font-semibold text-[#0A0A0A] mb-3">Discount Timeline (90 Days)</h3>
          <ResponsiveContainer width="100%" height={Math.max(180, timeline.stores.length * 35 + 40)}>
            <BarChart data={timeline.timeline} layout="vertical" margin={{ left: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis type="number" tick={{ fontSize: 9 }} />
              <YAxis type="category" dataKey="week" tick={{ fontSize: 8 }} width={70} tickFormatter={(w) => w.slice(-3)} />
              <Tooltip contentStyle={{ fontSize: 11 }} />
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
