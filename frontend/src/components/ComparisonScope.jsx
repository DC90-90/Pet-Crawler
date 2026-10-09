import { useEffect, useMemo, useState } from "react";
import api from "@/lib/api";

export const useComparisonScope = () => {
  const [mode, setMode] = useState("all");
  const [ids, setIds] = useState([]);
  const params = useMemo(() => ({ comparison_mode: mode, competitor_ids: ids.join(",") }), [mode, ids]);
  return { mode, setMode, ids, setIds, params };
};

export const ComparisonScope = ({ scope, prefix }) => {
  const [stores, setStores] = useState([]);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setError(false);
    api.get("/comparison-stores").then(r => live && setStores(r.data.stores || []))
      .catch(() => live && setError(true));
    return () => { live = false; };
  }, [retry]);
  return <fieldset className="min-w-0 space-y-2 border-y border-white/10 py-3" data-testid={`${prefix}-comparison-scope`}>
    <legend className="text-xs text-[#A1E4DB]">Competitor comparison</legend>
    <select aria-label="Competitor comparison scope" value={scope.mode} onChange={e => scope.setMode(e.target.value)}
      className="max-w-full bg-[#0A2728] border border-white/10 rounded-md text-xs text-white px-2 py-1.5" data-testid={`${prefix}-comparison-mode`}>
      <option value="all">All tracked competitors</option><option value="selected">Selected competitors only</option>
    </select>
    {error && <div role="alert" className="text-xs text-red-400" data-testid={`${prefix}-scope-error`}>Could not load competitors. <button onClick={() => setRetry(n => n + 1)} data-testid={`${prefix}-scope-retry`}>Retry</button></div>}
    {scope.mode === "selected" && <div className="flex flex-wrap gap-x-4 gap-y-2">
      {stores.map(s => <label key={s.id} className="flex items-center gap-2 text-xs text-white">
        <input type="checkbox" checked={scope.ids.includes(s.id)} onChange={e => scope.setIds(ids => e.target.checked ? [...ids, s.id] : ids.filter(id => id !== s.id))} data-testid={`${prefix}-competitor-${s.id}`} />{s.name}
      </label>)}
    </div>}
    <p className="text-xs text-[#A1E4DB]" data-testid={`${prefix}-scope-summary`}>{scope.mode === "all" ? "All tracked competitors" : scope.ids.length ? `${scope.ids.length} selected competitor(s)` : "No competitors selected"}</p>
  </fieldset>;
};