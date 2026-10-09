import { createContext, useContext, useEffect, useState } from "react";
import api from "@/lib/api";
import { RequestError } from "@/components/RequestError";

const ReleaseContext = createContext(null);
export const useRelease = () => useContext(ReleaseContext);
export const ReleaseProvider = ({ children }) => {
  const [release, setRelease] = useState(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setError(false);
    const read = () => api.get("/release", { timeout: 15000 }).then(r => { if (active) { setRelease(r.data); setError(false); } }).catch(() => active && setError(true));
    read();
    const interval = setInterval(read, 30000);
    return () => { active = false; clearInterval(interval); };
  }, [retry]);
  if (error) return <div className="p-6"><RequestError id="release-status" message="Release status is unavailable. Changes remain disabled." onRetry={() => setRetry(n => n + 1)} /></div>;
  if (!release) return <div className="p-6 text-[#A1E4DB]" data-testid="release-loading">Checking release status…</div>;
  return <ReleaseContext.Provider value={release}>{children}</ReleaseContext.Provider>;
};