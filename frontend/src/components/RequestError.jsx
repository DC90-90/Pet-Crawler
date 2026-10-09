import { Button } from "@/components/ui/button";
export const RequestError = ({ id, onRetry, message = "Request failed. Results are unavailable, not empty." }) => (
  <div role="alert" className="flex flex-wrap items-center gap-3 p-3 border border-red-400/30 text-sm text-red-300 rounded-md" data-testid={`${id}-error`}>
    <span>{message}</span><Button variant="outline" size="sm" onClick={onRetry} data-testid={`${id}-retry`}>Retry</Button>
  </div>
);