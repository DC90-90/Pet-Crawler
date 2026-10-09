import { useLocation, Link } from "react-router-dom";
import { useRelease } from "@/contexts/ReleaseContext";

const allowed = ["/", "/price-intel", "/insights", "/settings"];
export const ReleaseBoundary = ({ children }) => {
  const release = useRelease();
  const { pathname } = useLocation();
  if (pathname === "/alerts" && !release.capabilities.email) return <section className="p-6 text-[#A1E4DB]" data-testid="release-feature-disabled">Outbound notifications are unavailable in this release.</section>;
  if (!release.price_comparison_only || allowed.includes(pathname)) return children;
  return <section className="p-6 space-y-4" data-testid="release-feature-disabled">
    <h1 className="text-4xl text-white font-bold">Unavailable in this release</h1>
    <p className="text-sm text-[#A1E4DB]" data-testid="release-disabled-reason">Order analytics, outbound email and automated monitoring are disabled.</p>
    <Link to="/price-intel" className="text-[#1E988E] underline" data-testid="release-back-to-prices">Observed price comparisons</Link>
  </section>;
};

export const ObservationNotice = () => {
  const r = useRelease();
  return <div className="border-l-2 border-amber-400/70 bg-amber-400/5 px-4 py-3 text-xs text-[#A1E4DB] space-y-1" data-testid="observation-mode-notice">
    <p data-testid="automatic-refresh-status">Automatic refresh {r.capabilities.automatic_refresh ? "ON" : "OFF"} · observed prices, not live quotes</p>
    <p data-testid="offer-age-policy">Offers older than {r.maximum_offer_age_days} days are excluded. Exact sales and email delivery are unavailable.</p>
    {r.mode !== "observer" && <p data-testid="write-freeze-state">Write state: {r.mode} · active writers: {r.active_writer_count}</p>}
  </div>;
};