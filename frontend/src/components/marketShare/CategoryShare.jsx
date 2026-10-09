import { useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { ConfidenceBadge, TrendCell, fmtMoney, fmtNum, fmtPct } from "./SourceChip";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");

export default function CategoryShare({ days, includeToday, filters }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let live = true;
    setRows(null);
    setError(false);
    api.get("/market-share/categories", { params: { days, include_today: includeToday, ...(filters || {}) } })
      .then((r) => live && setRows(r.data.rows || []))
      .catch(() => live && setError(true));
    return () => { live = false; };
  }, [days, includeToday, filters, retry]);

  if (error) return <RequestError id="ms-categories" onRetry={() => setRetry(n => n + 1)} />;
  if (!rows) return <p className="text-sm text-[#A1E4DB]" data-testid="ms-categories-loading">Loading…</p>;
  if (rows.length === 0) return (
    <p className="text-sm text-[#A1E4DB]" data-testid="ms-categories-empty">No category could be resolved yet</p>
  );

  return (
    <div className="grid md:grid-cols-2 gap-4" data-testid="ms-categories">
      {rows.map((r, i) => (
        <div key={r.category} className="glass-card p-4" data-testid={`ms-category-card-${i}`}>
          <div className="flex items-start justify-between mb-3">
            <div>
              <h3 className="text-sm font-semibold text-white">{catLabel(r.category)}</h3>
              <p className="text-[10px] text-[#A1E4DB] mt-0.5">{r.coverage}</p>
            </div>
            <ConfidenceBadge level={r.confidence} reason={r.coverage} />
          </div>

          <div className="grid grid-cols-2 gap-3 mb-3">
            {[
              ["Tracked observed value / proxy", fmtMoney(r.revenue)],
              ["Tracked units / movement", fmtNum(r.units)],
              ["My share of category", r.my_revenue_share_pct === null || r.my_revenue_share_pct === undefined
                ? "Unavailable" : fmtPct(r.my_revenue_share_pct)],
              ["Gap opportunity", fmtMoney(r.missing_opportunity_value)],
            ].map(([l, v]) => (
              <div key={l}>
                <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{l}</p>
                <p className={`text-sm font-bold mt-0.5 ${v === "Unavailable" ? "text-[#F59E0B]" : "text-white"}`} dir="ltr">{v}</p>
              </div>
            ))}
          </div>

          <div className="grid sm:grid-cols-2 gap-3 text-[10px]">
            <div>
              <p className="text-[9px] uppercase tracking-wide text-[#A1E4DB] mb-1">Top products</p>
              {(r.top_products || []).slice(0, 4).map((p) => (
                <p key={p.sku} className="truncate text-[#A1E4DB]">
                  {p.in_catalog ? "" : "＋ "}{p.name} · <span dir="ltr" className="text-white">{fmtMoney(p.revenue)}</span>
                </p>
              ))}
              {(r.top_products || []).length === 0 && <p className="text-[#A1E4DB]">No eligible observation signals</p>}
            </div>
            <div>
              <p className="text-[9px] uppercase tracking-wide text-[#A1E4DB] mb-1">Top stores</p>
              {(r.top_stores || []).slice(0, 4).map((s) => (
                <p key={s.store_name} className="truncate text-[#A1E4DB]">
                  {s.store_name} · <span dir="ltr" className="text-white">{fmtMoney(s.revenue)}</span>
                </p>
              ))}
              {(r.top_stores || []).length === 0 && <p className="text-[#A1E4DB]">—</p>}
            </div>
          </div>

          <div className="flex items-center justify-between mt-3 pt-3 border-t border-white/5 text-[10px] text-[#A1E4DB]">
            <span>{fmtNum(r.my_products_count)} of {fmtNum(r.products)} products are mine · {fmtNum(r.missing_products)} gaps</span>
            <TrendCell pct={r.trend?.revenue_pct} />
          </div>
        </div>
      ))}
    </div>
  );
}
