import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from "recharts";
import { SourceChip, ConfidenceBadge, Unavailable, TrendCell, fmtMoney, fmtNum, fmtPct, REASON_TEXT } from "./SourceChip";

const explain = (reason) => REASON_TEXT[reason] || reason || "";

const packReason = (x) => {
  const r = x.reason || "";
  let m = r.match(/^slug_weight_([\d.]+)g_vs_ours_([\d.]+)g$/);
  if (m) return `Seller lists ${m[1]}g — ours is ${m[2]}g`;
  m = r.match(/^slug_pack_qty_(\d+)_vs_ours_(\d+)$/);
  if (m) return `Seller lists a ${m[1]}-pack — ours is ${m[2]}`;
  if (r === "price_outlier_vs_cluster") return x.detail;
  return x.detail || r;
};

export default function ProductBreakdown({ productKey, days, includeToday, open, onClose }) {
  const [row, setRow] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!open || !productKey) return;
    setRow(null); setErr(null);
    let live = true;
    api.get(`/market-share/product/${encodeURIComponent(productKey)}`, { params: { days, include_today: includeToday } })
      .then((r) => live && setRow(r.data.product))
      .catch((e) => live && setErr(e.response?.data?.detail || "Could not load this product"));
    return () => { live = false; };
  }, [productKey, days, open, includeToday]);

  const sellers = row?.sellers || [];
  const chart = sellers.filter((s) => (s.price || 0) > 0).map((s) => ({
    name: s.store_name, price: s.price, is_own: s.is_own,
  }));
  const lowest = Math.min(...chart.map((c) => c.price), Infinity);
  const highest = Math.max(...chart.map((c) => c.price), -Infinity);

  return (
    <Sheet open={open} onOpenChange={(v) => !v && onClose()}>
      <SheetContent side="right" className="w-full sm:max-w-3xl overflow-y-auto bg-[#0B1220] border-white/10"
        data-testid="ms-product-breakdown">
        <SheetHeader>
          <SheetTitle className="text-white text-base pe-6">
            {row?.name || (err ? "Not found" : "Loading…")}
          </SheetTitle>
        </SheetHeader>

        {err && <p className="text-sm text-[#EF4444] mt-4" data-testid="ms-breakdown-error">{err}</p>}

        {row && (
          <div className="space-y-5 mt-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-mono text-[#A1E4DB]" dir="ltr">{row.sku}</span>
              {row.brand && <Badge className="text-[9px] bg-white/5 text-[#A1E4DB] border-white/15">{row.brand}</Badge>}
              {row.category && <Badge className="text-[9px] bg-white/5 text-[#A1E4DB] border-white/15">{row.category}</Badge>}
              <ConfidenceBadge level={row.confidence} reason={row.confidence_reason} />
              {!row.in_catalog && (
                <Badge className="text-[9px] bg-[#F59E0B]/12 text-[#F59E0B] border-[#F59E0B]/25">Not in my catalog</Badge>
              )}
            </div>

            {row.unavailable_reason && (
              <p className="text-[11px] text-[#F59E0B] px-3 py-2 rounded-lg bg-[#F59E0B]/10 border border-[#F59E0B]/20"
                data-testid="ms-breakdown-unavailable">
                {explain(row.unavailable_reason)} — shares are withheld rather than shown as zero.
              </p>
            )}

            {row.price_spread_warning && (
              <p className="text-[11px] text-[#F59E0B] px-3 py-2 rounded-lg bg-[#F59E0B]/10 border border-[#F59E0B]/20"
                data-testid="ms-breakdown-spread">
                {row.price_spread_warning}. Nothing is dropped — the row is marked Low confidence so
                you can judge it yourself.
              </p>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                ["My price", row.in_catalog ? fmtMoney(row.my_price) : "Not in catalog", null],
                ["My revenue share", row.revenue_share_pct === null || row.revenue_share_pct === undefined
                  ? "Unavailable" : fmtPct(row.revenue_share_pct), row.my_units_source],
                ["My units", row.my_units === null || row.my_units === undefined
                  ? "Unavailable" : fmtNum(row.my_units), row.my_units_source],
                ["Tracked market revenue", row.market_revenue === null || row.market_revenue === undefined
                  ? "Unavailable" : fmtMoney(row.market_revenue), null],
              ].map(([l, v, src]) => (
                <div key={l} className="kpi-card !p-3">
                  <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{l}</p>
                  <p className={`text-sm font-bold mt-0.5 ${String(v).startsWith("Unavailable") ? "text-[#F59E0B]" : "text-white"}`} dir="ltr">{v}</p>
                  {src && <div className="mt-1"><SourceChip source={src} compact /></div>}
                </div>
              ))}
            </div>

            {chart.length > 0 && (
              <div>
                <h4 className="text-xs font-semibold text-white mb-2">Price by seller</h4>
                <div className="h-[180px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chart}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#ffffff12" />
                      <XAxis dataKey="name" tick={{ fill: "#A1E4DB", fontSize: 9 }} interval={0} angle={-20} textAnchor="end" height={50} />
                      <YAxis tick={{ fill: "#A1E4DB", fontSize: 9 }} />
                      <Tooltip contentStyle={{ background: "#0B1220", border: "1px solid #ffffff20", fontSize: 11 }} />
                      <Bar dataKey="price" radius={[3, 3, 0, 0]}>
                        {chart.map((c, i) => (
                          <Cell key={i} fill={c.is_own ? "#FF3B30" : c.price === lowest ? "#16A34A" : c.price === highest ? "#F59E0B" : "#002DF5"} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            <div>
              <h4 className="text-xs font-semibold text-white mb-2">
                Every seller of this product ({sellers.length})
              </h4>
              <div className="overflow-x-auto rounded-md border border-white/10">
                <Table>
                  <TableHeader>
                    <TableRow className="border-white/10">
                      {["Store", "Match", "Price", "Stock", "Units", "Revenue", "Unit share",
                        "Revenue share", "Source", "Last crawl"].map((h) => (
                        <TableHead key={h} className="text-[9px] uppercase tracking-wider text-[#A1E4DB] whitespace-nowrap">{h}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sellers.map((s, i) => (
                      <TableRow key={`${s.store_id}-${s.sku_at_store}`} className="border-white/5"
                        data-testid={`ms-seller-row-${i}`}>
                        <TableCell className="text-xs text-white whitespace-nowrap">
                          {s.store_name}
                          {s.is_own && <Badge className="ms-1.5 text-[9px] bg-[#FF3B30]/15 text-[#FF3B30] border-[#FF3B30]/25">Mine</Badge>}
                        </TableCell>
                        <TableCell className="text-[10px] text-[#A1E4DB] whitespace-nowrap"
                          title={`identity key: ${s.match_source || "own"} · sku at store: ${s.sku_at_store}`}>
                          {s.match_strength}% · {(s.match_source || "own").replace(/_/g, " ")}
                        </TableCell>
                        <TableCell className="text-xs text-white whitespace-nowrap" dir="ltr">{fmtMoney(s.price)}</TableCell>
                        <TableCell className="text-[10px] whitespace-nowrap">
                          <span className={s.in_stock ? "text-[#10B981]" : "text-[#EF4444]"}>
                            {s.in_stock ? s.stock_signal : "OOS"}
                          </span>
                        </TableCell>
                        <TableCell className="text-xs whitespace-nowrap" dir="ltr">
                          {s.units === null || s.units === undefined
                            ? <Unavailable reason={s.unavailable_reason} />
                            : <span className="text-white">{fmtNum(s.units)}</span>}
                        </TableCell>
                        <TableCell className="text-xs text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                          {s.revenue === null || s.revenue === undefined ? "—" : fmtMoney(s.revenue)}
                        </TableCell>
                        <TableCell className="text-[11px] text-[#5FD3C7] whitespace-nowrap" dir="ltr">
                          {s.unit_share_pct === null || s.unit_share_pct === undefined ? "—" : fmtPct(s.unit_share_pct)}
                        </TableCell>
                        <TableCell className="text-[11px] text-[#10B981] whitespace-nowrap" dir="ltr">
                          {s.revenue_share_pct === null || s.revenue_share_pct === undefined ? "—" : fmtPct(s.revenue_share_pct)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap"><SourceChip source={s.units_source} compact /></TableCell>
                        <TableCell className="text-[10px] text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                          {s.last_crawl_at ? new Date(s.last_crawl_at).toLocaleDateString("en-GB") : "—"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>

            {(row.excluded_sellers || []).length > 0 && (
              <div data-testid="ms-excluded-sellers">
                <h4 className="text-xs font-semibold text-white mb-2">
                  Excluded from this product's market ({row.excluded_sellers.length})
                </h4>
                <div className="space-y-1">
                  {row.excluded_sellers.map((x, i) => (
                    <div key={i} className="flex items-center justify-between gap-2 px-2 py-1.5 rounded-md bg-white/[0.03]">
                      <span className="text-[11px] text-white">{x.store_name}</span>
                      <span className="text-[10px] text-[#F59E0B] text-end">{packReason(x)}</span>
                      <span className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtMoney(x.price)}</span>
                    </div>
                  ))}
                </div>
                <p className="text-[10px] text-[#A1E4DB] mt-1.5">
                  These listings are a different pack size, or a price the rest of the market contradicts.
                  They are shown here rather than dropped silently.
                </p>
              </div>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-[11px]">
              <div><p className="text-[9px] uppercase text-[#A1E4DB]">Trend units</p><TrendCell pct={row.trend?.units_pct} /></div>
              <div><p className="text-[9px] uppercase text-[#A1E4DB]">Trend revenue</p><TrendCell pct={row.trend?.revenue_pct} /></div>
              <div><p className="text-[9px] uppercase text-[#A1E4DB]">My price rank</p>
                <p className="text-white" dir="ltr">{row.price_rank ? `#${row.price_rank} of ${row.price_rank_of}` : "—"}</p></div>
              <div><p className="text-[9px] uppercase text-[#A1E4DB]">Units rank</p>
                <p className="text-white" dir="ltr">{row.units_rank ? `#${row.units_rank} of ${row.units_rank_of}` : "—"}</p></div>
            </div>

            {!row.in_catalog && row.recommended_action && (
              <p className="text-[11px] text-[#5FD3C7] px-3 py-2 rounded-lg bg-[#1E988E]/10 border border-[#1E988E]/20">
                {row.recommended_action}
              </p>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
