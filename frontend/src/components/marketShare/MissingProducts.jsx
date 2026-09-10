import { useEffect, useState } from "react";
import api from "@/lib/api";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { ConfidenceBadge, Unavailable, TrendCell, fmtMoney, fmtNum, REASON_TEXT } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");

export default function MissingProducts({ days, includeToday, filters, onPickProduct }) {
  const [data, setData] = useState(null);
  const [sort, setSort] = useState("opportunity_desc");
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(true);
  const limit = 50;

  useEffect(() => { setPage(0); }, [filters, days]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    const { catalog, min_confidence, ...rest } = filters || {};
    api.get("/market-share/missing-products", {
      params: { days, sort, include_today: includeToday, limit, offset: page * limit, ...rest },
    })
      .then((r) => live && setData(r.data))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [days, sort, page, filters, includeToday]);

  const rows = data?.rows || [];
  const total = data?.total || 0;

  return (
    <div className="space-y-3" data-testid="ms-missing-products">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-[#A1E4DB]" data-testid="ms-missing-count">
          {fmtNum(total)} product(s) competitors sell that I don't
          {data?.total_untruncated > total && ` · top ${fmtNum(total)} of ${fmtNum(data.total_untruncated)} by opportunity`}
          {" · measured market value "}<span dir="ltr">{fmtMoney(data?.opportunity_value)}</span>
        </p>
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] uppercase tracking-wide text-[#A1E4DB]">Sort</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)}
            className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1"
            data-testid="ms-missing-sort">
            <option value="opportunity_desc" className="bg-[#0B1220]">Opportunity score</option>
            <option value="market_revenue_desc" className="bg-[#0B1220]">Market revenue</option>
            <option value="units_desc" className="bg-[#0B1220]">Market units</option>
            <option value="competitors_desc" className="bg-[#0B1220]">Competitors</option>
            <option value="name_asc" className="bg-[#0B1220]">Name</option>
          </select>
        </div>
      </div>

      <p className="text-[11px] text-[#A1E4DB]">
        My share of every row here is <span className="text-[#F59E0B]">0% — not in catalog</span>, by definition.
      </p>

      <div className="glass-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-white/10">
              {["Product", "SKU / GTIN", "Category", "Brand", "Competitors", "Market units",
                "Market revenue", "Top competitor", "Avg price", "Price range", "Trend (rev)",
                "Opportunity", "Confidence", "Recommended action"].map((h) => (
                <TableHead key={h} className="text-[9px] uppercase tracking-wider text-[#A1E4DB] whitespace-nowrap">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={14} className="text-xs text-[#A1E4DB] py-6 text-center">Loading…</TableCell></TableRow>
            )}
            {!loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={14} className="text-xs text-[#A1E4DB] py-6 text-center" data-testid="ms-missing-empty">
                Nothing matches these filters
              </TableCell></TableRow>
            )}
            {rows.map((r, i) => (
              <TableRow key={r.canonical_key} onClick={() => onPickProduct(r)}
                className="border-white/5 cursor-pointer hover:bg-white/[0.04]"
                data-testid={`ms-missing-row-${i}`}>
                <TableCell className="text-xs text-white max-w-[240px]">
                  <p className="truncate">{r.name}</p>
                  {r.name_ar && <p className="truncate text-[10px] text-[#A1E4DB]">{r.name_ar}</p>}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] font-mono whitespace-nowrap" dir="ltr">{r.sku}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap">{catLabel(r.category)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap">{r.brand || "—"}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] max-w-[160px] truncate"
                  title={(r.competitors || []).join(", ")}>
                  {r.competitor_count} · {(r.competitors || []).slice(0, 2).join(", ")}
                </TableCell>
                <TableCell className="text-xs text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                  {r.market_units === null ? <Unavailable reason={r.unavailable_reason} /> : fmtNum(r.market_units)}
                </TableCell>
                <TableCell className="text-xs text-white whitespace-nowrap" dir="ltr">
                  {r.market_revenue === null ? <Unavailable reason={r.unavailable_reason} /> : fmtMoney(r.market_revenue)}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] max-w-[120px] truncate">
                  {r.top_competitor?.store_name || "—"}
                </TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap" dir="ltr">{fmtMoney(r.avg_price)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap" dir="ltr">
                  {r.min_price === null ? "—" : `${r.min_price} – ${r.max_price}`}
                </TableCell>
                <TableCell className="whitespace-nowrap"><TrendCell pct={r.trend?.revenue_pct} /></TableCell>
                <TableCell className="whitespace-nowrap">
                  <span className="text-xs font-bold text-[#F59E0B]" dir="ltr"
                    title={r.opportunity_formula}>{r.opportunity_score}</span>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <ConfidenceBadge level={r.confidence} reason={REASON_TEXT[r.unavailable_reason]}
                    testId={`ms-missing-confidence-${i}`} />
                </TableCell>
                <TableCell className="text-[11px] text-[#5FD3C7] max-w-[230px]">{r.recommended_action}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {total > limit && (
        <div className="flex items-center justify-between">
          <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-missing-prev">Previous</Button>
          <span className="text-[11px] text-[#A1E4DB]" dir="ltr">
            {page * limit + 1}–{Math.min((page + 1) * limit, total)} of {fmtNum(total)}
          </span>
          <Button variant="outline" size="sm" disabled={(page + 1) * limit >= total}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-full text-xs border-white/10 text-[#A1E4DB]" data-testid="ms-missing-next">Next</Button>
        </div>
      )}
    </div>
  );
}
