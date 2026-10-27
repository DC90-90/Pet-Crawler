import { useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { CATEGORY_LABELS } from "@/lib/i18n";
import DataTable from "@/components/DataTable";
import { fmtNum } from "./SourceChip";
import { groupColumns } from "./groupColumns";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");
const COLUMNS = groupColumns("brand", "Brand");

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
      .catch((failure) => live && setError(failure))
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [days, filters, includeToday, retry]);

  const rows = data?.rows || [];
  if (error) return <RequestError id="ms-brands" error={error} onRetry={() => setRetry(n => n + 1)} />;
  if (loading) return <p data-testid="ms-brands-loading" className="text-sm text-[#A1E4DB]">Loading…</p>;

  return (
    <div className="space-y-3" data-testid="ms-brands">
      <p className="text-sm text-[#A1E4DB]">
        {fmtNum(rows.length)} brand(s) resolved from the tracked catalog
        {filters?.category && ` inside ${catLabel(filters.category)}`}.
        A product with no brand from any store is left out of this table rather than bucketed as
        "Unknown"; its value still counts in Categories.
      </p>

      <DataTable columns={COLUMNS} rows={rows} storageKey="ms-brands" exportName="daleel-brands"
        rowKey={(r) => r.brand} initialSort={{ id: "revenue", dir: "desc" }}
        emptyText="No brand could be resolved for this selection" />
    </div>
  );
}
