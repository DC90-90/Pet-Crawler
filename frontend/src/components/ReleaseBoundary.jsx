import { useRelease } from "@/contexts/ReleaseContext";

export const ReleaseBoundary = ({ children }) => {
  const release = useRelease();
  return <>
    {release.mode !== "active" && <div role="status" className="mx-4 md:mx-6 mt-4 border-s-2 border-amber-400/70 bg-amber-400/5 px-4 py-3 text-xs text-[#A1E4DB]" data-testid="release-readonly-notice">
      Read-only mode · Viewing and filtering are available. Changes, imports, source refreshes and delivery are disabled.
    </div>}
    {children}
  </>;
};

export const ObservationNotice = () => {
  const r = useRelease();
  return <div className="border-l-2 border-amber-400/70 bg-amber-400/5 px-4 py-3 text-xs text-[#A1E4DB] space-y-1" data-testid="observation-mode-notice">
    <p data-testid="automatic-refresh-status">Automatic refresh {r.capabilities.automatic_refresh ? "ON" : "OFF"} · observed prices, not live quotes</p>
    <p data-testid="offer-age-policy">Offers older than {r.maximum_offer_age_days} days are excluded. Exact sales and email delivery are unavailable.</p>
    {r.mode !== "observer" && <p data-testid="write-freeze-state">Write state: {r.mode} · active writers: {r.active_writer_count}</p>}
  </div>;
};