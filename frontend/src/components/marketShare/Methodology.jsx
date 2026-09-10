import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { BookOpen, CheckCircle2, XCircle, Clock } from "lucide-react";
import { SourceChip, fmtNum } from "./SourceChip";

export default function Methodology({ days, includeToday }) {
  const [d, setD] = useState(null);

  useEffect(() => {
    let live = true;
    api.get("/market-share/methodology", { params: { days, include_today: includeToday } })
      .then((r) => live && setD(r.data));
    return () => { live = false; };
  }, [days, includeToday]);

  if (!d) return <p className="text-sm text-[#A1E4DB]">Loading…</p>;

  return (
    <div className="space-y-4 max-w-4xl" data-testid="ms-methodology">
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 mb-2">
          <BookOpen className="w-4 h-4 text-[#1E988E]" />
          <h3 className="text-sm font-semibold text-white">What "tracked market" means</h3>
        </div>
        <p className="text-xs text-[#A1E4DB]" data-testid="ms-methodology-tracked-market">{d.tracked_market}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {(d.stores || []).map((s) => (
            <Badge key={s.store_id}
              className={`text-[10px] border ${s.sales_data_available
                ? "bg-[#10B981]/10 text-[#10B981] border-[#10B981]/25"
                : "bg-white/5 text-[#A1E4DB] border-white/15"}`}>
              {s.store_name} · {s.days_observed}d
            </Badge>
          ))}
        </div>
        <p className="text-[11px] text-[#A1E4DB] mt-3 inline-flex items-center gap-1.5">
          <Clock className="w-3 h-3" /> Window {d.window?.date_from} → {d.window?.date_to}
          {" · last computed "}
          <span dir="ltr">{d.last_updated ? new Date(d.last_updated).toLocaleString("en-GB") : "just now"}</span>
        </p>
      </div>

      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Where every number comes from</h3>
        <div className="space-y-3">
          {(d.sources || []).map((s) => (
            <div key={s.id} className="flex gap-3">
              <div className="pt-0.5 shrink-0"><SourceChip source={s.id} /></div>
              <div className="min-w-0">
                <p className="text-xs text-white">{s.what}</p>
                <p className="text-[11px] text-[#A1E4DB] mt-0.5">Applies to: {s.applies_to}</p>
                {s.caveat && <p className="text-[11px] text-[#F59E0B] mt-0.5">Caveat: {s.caveat}</p>}
                {s.available === false && s.unavailable_reason && (
                  <p className="text-[11px] text-[#F59E0B] mt-0.5 inline-flex items-center gap-1">
                    <XCircle className="w-3 h-3" /> {s.unavailable_reason}
                  </p>
                )}
                {s.available === true && (
                  <p className="text-[11px] text-[#10B981] mt-0.5 inline-flex items-center gap-1">
                    <CheckCircle2 className="w-3 h-3" /> Connected
                  </p>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">What we deliberately do NOT use</h3>
        {(d.not_used || []).map((n) => (
          <div key={n.id}>
            <p className="text-xs text-white font-mono">{n.id}</p>
            <p className="text-[11px] text-[#A1E4DB] mt-0.5">{n.why}</p>
          </div>
        ))}
      </div>

      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Formulas</h3>
        <div className="space-y-2">
          {Object.entries(d.formulas || {}).map(([k, v]) => (
            <div key={k} className="grid sm:grid-cols-[180px_1fr] gap-1 sm:gap-3">
              <code className="text-[11px] text-[#5FD3C7] font-mono">{k}</code>
              <p className="text-[11px] text-[#A1E4DB]">{v}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-2">How a competitor listing is matched to my product</h3>
        <ol className="list-decimal ms-4 space-y-1">
          {(d.identity?.order || []).map((o) => (
            <li key={o} className="text-[11px] text-[#A1E4DB]">{o}</li>
          ))}
        </ol>
        <p className="text-[11px] text-[#A1E4DB] mt-2">{d.identity?.note}</p>
      </div>

      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Confidence levels</h3>
        <div className="space-y-2">
          {Object.entries(d.confidence || {}).map(([k, v]) => (
            <div key={k} className="grid sm:grid-cols-[110px_1fr] gap-1 sm:gap-3">
              <span className="text-[11px] uppercase tracking-wide text-white">{k}</span>
              <p className="text-[11px] text-[#A1E4DB]">{v}</p>
            </div>
          ))}
        </div>
      </div>

      <div className="glass-card p-5">
        <h3 className="text-sm font-semibold text-white mb-3">Why some numbers are unavailable</h3>
        <ul className="space-y-1 text-[11px] text-[#A1E4DB]">
          <li>• Units are a DIFFERENCE between two crawls. One crawl in the window means no change can exist yet.</li>
          <li>• A store that publishes neither a sold counter nor stock levels cannot have its sales measured at all —
            it still appears as a seller, with its price and stock status.</li>
          <li>• My own exact units need the Zid orders ledger. Without it my figures fall back to stock depletion,
            which is a floor rather than a total.</li>
          <li>• A withheld number is never rendered as 0: a zero would claim "sold nothing", which is a different fact.</li>
        </ul>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">
          {Object.entries(d.data_quality || {}).map(([k, v]) => (
            <div key={k}>
              <p className="text-[9px] uppercase tracking-[0.12em] text-[#A1E4DB]">{k.replace(/_/g, " ")}</p>
              <p className="text-sm font-bold text-white mt-0.5" dir="ltr">
                {typeof v === "boolean" ? (v ? "yes" : "no") : fmtNum(v)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
