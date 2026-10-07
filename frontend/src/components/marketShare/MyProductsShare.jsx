import { useEffect, useState } from "react";
import api from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { SourceChip, ConfidenceBadge, Unavailable, TrendCell, fmtMoney, fmtNum, fmtPct, REASON_TEXT } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");

const SORTS = [
  ["market_revenue_desc", "Market revenue"],
  ["revenue_share_desc", "My share (high)"],
  ["revenue_share_asc", "My share (low)"],
  ["my_revenue_desc", "My revenue"],
  ["units_desc", "Market units"],
  ["competitors_desc", "Competitors"],
  ["name_asc", "Name"],
];

export default function MyProductsShare({ days, includeToday, filters, onPickProduct }) {
  const [data, setData] = useState(null);
  const [sort, setSort] = useState("market_revenue_desc");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const limit = 50;

  useEffect(() => { setPage(0); }, [filters, days]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    api.get("/market-share/my-products", {
      params: { days, sort, include_today: includeToday, limit, offset: page * limit, ...filters },
    })
      .then((r) => live && setData(r.data))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [days, sort, page, filters, includeToday]);

  const rows = data?.rows || [];
  const total = data?.total || 0;

  return (
    <div className="space-y-3" data-testid="ms-my-products">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-[#A1E4DB]" data-testid="ms-my-products-count">
          {fmtNum(total)} product(s) · showing {rows.length} · my observed value{" "}
          <span dir="ltr">{fmtMoney(data?.totals?.my_revenue)}</span> of{" "}
          <span dir="ltr">{fmtMoney(data?.totals?.market_revenue)}</span> tracked
        </p>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wide text-[#A1E4DB]">Sort</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1"
            data-testid="ms-my-products-sort">
            {SORTS.map(([v, l]) => <option key={v} value={v} className="bg-[#0B1220]">{l}</option>)}
          </select>
        </div>
      </div>

      <div className="glass-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-white/10">
              {["Product", "SKU / GTIN", "Category", "Brand", "My price", "My units",
                "My revenue", "Market units", "Market revenue", "Unit share", "Revenue share",
                "Stores carrying", "Sales data available", "Top competitor", "Competitor range",
                "My price rank", "Trend (rev)", "Confidence"].map((h) => (
                <TableHead key={h} className="text-[9px] uppercase tracking-wider text-[#A1E4DB] whitespace-nowrap">
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={18} className="text-xs text-[#A1E4DB] py-6 text-center">Loading…</TableCell></TableRow>
            )}
            {!loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={18} className="text-xs text-[#A1E4DB] py-6 text-center" data-testid="ms-my-products-empty">
                No product matches these filters
              </TableCell></TableRow>
            )}
            {rows.map((r, i) => (
              <TableRow key={r.sku} onClick={() => onPickProduct(r)}
                className="border-white/5 cursor-pointer hover:bg-white/[0.04]"
                data-testid={`ms-product-row-${i}`}>
                <TableCell className="text-xs text-white max-w-[240px]">
                  <p className="truncate">{r.name}</p>
                  {r.name_ar && <p className="truncate text-[10px] text-[#A1E4DB]">{r.name_ar}</p>}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] font-mono whitespace-nowrap" dir="ltr">{r.sku}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap">
                  {catLabel(r.category)}
                  {r.category_source === "derived_from_name" && (
                    <span title="Derived from the product name — my catalog carries no category"
                      className="ms-1 text-[9px] text-[#5FD3C7]">~</span>
                  )}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap">
                  {r.brand || <span className="text-[#F59E0B]">unresolved</span>}
                  {r.brand_source === "derived_from_name" && (
                    <span title="Derived from the product name" className="ms-1 text-[9px] text-[#5FD3C7]">~</span>
                  )}
                </TableCell>
                <TableCell className="text-xs text-white whitespace-nowrap" dir="ltr">{fmtMoney(r.my_price)}</TableCell>
                <TableCell className="text-xs whitespace-nowrap" dir="ltr">
                  {r.my_units === null || r.my_units === undefined
                    ? <Unavailable reason={r.my_unavailable_reason} />
                    : <span className="text-white">{fmtNum(r.my_units)}</span>}
                </TableCell>
                <TableCell className="text-xs whitespace-nowrap" dir="ltr">
                  {r.my_revenue === null || r.my_revenue === undefined
                    ? <Unavailable reason={r.my_unavailable_reason} />
                    : <span className="text-white">{fmtMoney(r.my_revenue)}</span>}
                </TableCell>
                <TableCell className="text-xs text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                  {r.market_units === null ? <Unavailable reason={r.unavailable_reason} /> : fmtNum(r.market_units)}
                </TableCell>
                <TableCell className="text-xs text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                  {r.market_revenue === null ? <Unavailable reason={r.unavailable_reason} /> : fmtMoney(r.market_revenue)}
                </TableCell>
                <TableCell className="text-xs whitespace-nowrap" dir="ltr">
                  {r.unit_share_pct === null || r.unit_share_pct === undefined
                    ? <span className="text-[#A1E4DB]">—</span>
                    : <span className="font-semibold text-[#5FD3C7]">{fmtPct(r.unit_share_pct)}</span>}
                </TableCell>
                <TableCell className="text-xs whitespace-nowrap" dir="ltr">
                  {r.revenue_share_pct === null || r.revenue_share_pct === undefined
                    ? <span className="text-[#A1E4DB]">—</span>
                    : <span className="font-semibold text-[#10B981]">{fmtPct(r.revenue_share_pct)}</span>}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap" dir="ltr"
                  data-testid={`ms-stores-carrying-${i}`}>
                  <span className="text-white">{r.sellers_total}</span>
                  <span className="text-[9px] ms-1" title="Stores whose listing is matched to this product, mine included">
                    ({r.competitor_count} rival{r.competitor_count === 1 ? "" : "s"} + me)
                  </span>
                </TableCell>
                <TableCell className="text-[11px] whitespace-nowrap" dir="ltr"
                  data-testid={`ms-sales-data-available-${i}`}>
                  <span className={r.sellers_with_sales ? "text-white" : "text-[#F59E0B]"}>
                    {r.sellers_with_sales} of {r.sellers_total}
                  </span>
                  {!r.sellers_with_sales && (
                    <span className="block text-[9px] text-[#F59E0B]"
                      title="Carrying a product and publishing sales data are two different things — no seller here publishes one">
                      no seller publishes sales data
                    </span>
                  )}
                  {r.sole_seller && (
                    <span className="block text-[9px] text-[#F59E0B]"
                      title="No other tracked seller's sales are measurable, so a share here is 100% by default">
                      sole measurable seller
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] max-w-[130px] truncate">
                  {r.top_competitor?.store_name || "—"}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                  {r.competitor_price_min === null ? "—"
                    : `${r.competitor_price_min} – ${r.competitor_price_max}`}
                  {r.price_spread_warning && (
                    <span className="block text-[9px] text-[#F59E0B]" title={r.price_spread_warning}>
                      {r.price_spread_ratio}× spread — check pack size
                    </span>
                  )}
                </TableCell>
                <TableCell className="text-[11px] whitespace-nowrap" dir="ltr">
                  {r.price_rank ? (
                    <Badge className={`text-[9px] border ${r.price_rank === 1
                      ? "bg-[#10B981]/12 text-[#10B981] border-[#10B981]/25"
                      : "bg-white/5 text-[#A1E4DB] border-white/15"}`}>
                      #{r.price_rank} of {r.price_rank_of}
                    </Badge>
                  ) : "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap"><TrendCell pct={r.trend?.revenue_pct} /></TableCell>
                <TableCell className="whitespace-nowrap">
                  <div className="flex flex-col gap-1 items-start">
                    <ConfidenceBadge level={r.confidence} reason={r.confidence_reason}
                      testId={`ms-product-confidence-${i}`} />
                    {r.my_units_source && <SourceChip source={r.my_units_source} compact />}
                    {r.unavailable_reason && (
                      <span className="text-[9px] text-[#F59E0B] max-w-[160px]">
                        {REASON_TEXT[r.unavailable_reason] || r.unavailable_reason}
                      </span>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {total > limit && (
        <div className="flex items-center justify-between">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-prev-page">Previous</Button>
          <span className="text-[11px] text-[#A1E4DB]" dir="ltr">
            {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {fmtNum(total)}
          </span>
          <Button variant="outline" size="sm" disabled={(page + 1) * limit >= total}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-next-page">Next</Button>
        </div>
      )}
    </div>
  );
}
