import { Button } from "@/components/ui/button";
const failureMessages = {
  price_query_timeout: "Price analysis timed out before a complete result was available. No partial or empty results were returned.",
  price_database_unavailable: "The price database is temporarily unavailable. Results could not be loaded.",
  price_source_changed: "Source data changed during analysis. Retry to obtain a consistent result.",
  price_freshness_changed: "Price evidence expired during analysis. Retry to recalculate using eligible observations.",
  price_cache_rebuilding: "Price analysis is being prepared in the background after a data update. This takes a few minutes on the first load; retry shortly.",
};
export const RequestError = ({ id, onRetry, error, message }) => (
  <div role="alert" className="flex flex-wrap items-center gap-3 p-3 border border-red-400/30 text-sm text-red-300 rounded-md" data-testid={`${id}-error`}>
    <span className="min-w-0 break-words" data-testid={`${id}-error-message`}>{message || failureMessages[error?.response?.data?.detail?.code] || `Request failed${error?.response?.status ? ` (HTTP ${error.response.status})` : ""}. Results are unavailable, not empty.`}</span><Button variant="outline" size="sm" onClick={onRetry} data-testid={`${id}-retry`}>Retry</Button>
  </div>
);