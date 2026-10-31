import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/lib/i18n";
const failureMessages = {
  price_query_timeout: "Price analysis timed out before a complete result was available. No partial or empty results were returned.",
  price_database_unavailable: "The price database is temporarily unavailable. Results could not be loaded.",
  price_source_changed: "Source data changed during analysis. Retry to obtain a consistent result.",
  price_freshness_changed: "Price evidence expired during analysis. Retry to recalculate using eligible observations.",
  price_cache_rebuilding: "Price analysis is being prepared in the background after a data update. This takes a few minutes on the first load; retry shortly.",
};
// Answers that clear by themselves within minutes (a view being built, data
// that moved mid-read). The client found the red "being prepared" box
// unacceptable (31 Oct 2026): these show a quiet loading line and retry on
// their own; only if they persist does the message appear.
const SELF_CLEARING = new Set(["price_cache_rebuilding", "price_source_changed", "price_freshness_changed"]);
const RETRY_EVERY_MS = 8000;
const QUIET_FOR_MS = 150000;       // ~2.5 minutes, across remounts of the same box
const firstSeen = new Map();       // id -> { first, last }

function quietStill(id) {
  const now = Date.now();
  let seen = firstSeen.get(id);
  if (!seen || now - seen.last > 60000) seen = { first: now };
  seen.last = now;
  firstSeen.set(id, seen);
  return now - seen.first < QUIET_FOR_MS;
}

export const RequestError = ({ id, onRetry, error, message }) => {
  const code = error?.response?.data?.detail?.code;
  const { isRTL } = useI18n() || {};
  const [tries, setTries] = useState(0);
  const quiet = !message && SELF_CLEARING.has(code) && !!onRetry && quietStill(id);
  useEffect(() => {
    if (!quiet) return undefined;
    const t = setTimeout(() => { setTries((n) => n + 1); onRetry(); }, RETRY_EVERY_MS);
    return () => clearTimeout(t);
  }, [quiet, tries, onRetry, error]);
  if (quiet) {
    return (
      <div className="flex items-center gap-2 p-3 text-sm text-[#A1E4DB]" data-testid={`${id}-loading`}>
        <Loader2 className="w-4 h-4 animate-spin" />{isRTL ? "جارٍ تحميل البيانات…" : "Loading data…"}
      </div>
    );
  }
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 p-3 border border-red-400/30 text-sm text-red-300 rounded-md" data-testid={`${id}-error`}>
      <span className="min-w-0 break-words" data-testid={`${id}-error-message`}>{message || failureMessages[code] || `Request failed${error?.response?.status ? ` (HTTP ${error.response.status})` : ""}. Results are unavailable, not empty.`}</span><Button variant="outline" size="sm" onClick={onRetry} data-testid={`${id}-retry`}>Retry</Button>
    </div>
  );
};
