import { useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";
import { CATEGORY_LABELS } from "@/lib/i18n";
import DataTable from "@/components/DataTable";
import { groupColumns } from "./groupColumns";

const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c || "—");
const COLUMNS = groupColumns("category", "Category", catLabel);

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
      .catch((failure) => live && setError(failure));
    return () => { live = false; };
  }, [days, includeToday, filters, retry]);

  if (error) return <RequestError id="ms-categories" error={error} onRetry={() => setRetry(n => n + 1)} />;
  if (!rows) return <p className="text-sm text-[#A1E4DB]" data-testid="ms-categories-loading">Loading…</p>;
  if (rows.length === 0) return (
    <p className="text-sm text-[#A1E4DB]" data-testid="ms-categories-empty">No category could be resolved yet</p>
  );

  return (
    <div data-testid="ms-categories">
      <DataTable columns={COLUMNS} rows={rows} storageKey="ms-categories" exportName="daleel-categories"
        rowKey={(r) => r.category} initialSort={{ id: "revenue", dir: "desc" }} />
    </div>
  );
}
