import { useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfidenceBadge, TrendCell, fmtMoney, fmtNum, fmtPct } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");

export default function BrandShare({ days, includeToday, filters }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(false); setData(null);
    api.get("/market-share/brands", {
      params: { days, include_today: includeToday, ...(filters || {}) },
    })
      .then((r) => live && setData(r.data))
      .catch(() => live && setError(true))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [days, filters, includeToday, retry]);

  const rows = data?.rows || [];
  if (error) return <RequestError id="ms-brands" onRetry={() => setRetry(n => n + 1)} />;
  if (loading) return <p data-testid="ms-brands-loading" className="text-sm text-[#A1E4DB]">Loading…</p>;

  return (
    <div className="space-y-3" data-testid="ms-brands">
      <p className="text-[11px] text-[#A1E4DB]">
        {fmtNum(rows.length)} brand(s) resolved from the tracked catalog
        {filters?.category && ` inside ${catLabel(filters.category)}`}.
        A product whose brand cannot be detected is left out of this table rather than
        bucketed as "Unknown" — its revenue still counts in Categories.
      </p>

      <div className="glass-card overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="border-white/10">
              {["Brand", "Units / movement", "Observed value / proxy", "Exact market share", "My units / proxy", "My value / proxy",
                "My share of brand", "Products", "In my catalog", "Measurable",
                "Top products", "Top stores", "Trend (rev)", "Confidence"].map((h) => (
                <TableHead key={h} className="text-[9px] uppercase tracking-wider text-[#A1E4DB] whitespace-nowrap">{h}</TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={14} className="text-xs text-[#A1E4DB] py-6 text-center">Loading…</TableCell></TableRow>
            )}
            {!loading && rows.length === 0 && (
              <TableRow><TableCell colSpan={14} className="text-xs text-[#A1E4DB] py-6 text-center" data-testid="ms-brands-empty">
                No brand could be resolved for this selection
              </TableCell></TableRow>
            )}
            {rows.map((r, i) => (
              <TableRow key={r.brand} className="border-white/5" data-testid={`ms-brand-row-${i}`}>
                <TableCell className="text-xs text-white whitespace-nowrap">{r.brand}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtNum(r.units)}</TableCell>
                <TableCell className="text-xs text-white whitespace-nowrap" dir="ltr">{fmtMoney(r.revenue)}</TableCell>
                <TableCell className="text-xs font-semibold text-[#5FD3C7]" dir="ltr">{fmtPct(r.revenue_share_pct)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtNum(r.my_units)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB] whitespace-nowrap" dir="ltr">{fmtMoney(r.my_revenue)}</TableCell>
                <TableCell className="text-xs font-semibold text-[#10B981]" dir="ltr">{fmtPct(r.my_revenue_share_pct)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtNum(r.products)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtNum(r.my_products_count)}</TableCell>
                <TableCell className="text-[11px] text-[#A1E4DB]" dir="ltr">{fmtNum(r.measured_products)}</TableCell>
                <TableCell className="text-[10px] text-[#A1E4DB] max-w-[200px]">
                  {(r.top_products || []).slice(0, 3).map((p) => (
                    <p key={p.sku} className="truncate">{p.name} · <span dir="ltr">{fmtMoney(p.revenue)}</span></p>
                  ))}
                  {(r.top_products || []).length === 0 && "—"}
                </TableCell>
                <TableCell className="text-[10px] text-[#A1E4DB] max-w-[170px]">
                  {(r.top_stores || []).slice(0, 3).map((s) => (
                    <p key={s.store_name} className="truncate">{s.store_name} · <span dir="ltr">{fmtMoney(s.revenue)}</span></p>
                  ))}
                  {(r.top_stores || []).length === 0 && "—"}
                </TableCell>
                <TableCell className="whitespace-nowrap"><TrendCell pct={r.trend?.revenue_pct} /></TableCell>
                <TableCell className="whitespace-nowrap">
                  <ConfidenceBadge level={r.confidence} reason={r.coverage} testId={`ms-brand-confidence-${i}`} />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
