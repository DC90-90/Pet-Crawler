import { createContext, useContext, useEffect, useState, useCallback } from "react";
import api from "./api";

const MySkusContext = createContext({ mySkus: new Set(), refresh: () => {}, loading: false });

export function MySkusProvider({ children }) {
  const [mySkus, setMySkus] = useState(new Set());
  const [loading, setLoading] = useState(false);
  const [authTick, setAuthTick] = useState(() => localStorage.getItem("daleel_token") || "");

  const refresh = useCallback(async () => {
    if (!localStorage.getItem("daleel_token")) {
      setMySkus(new Set());
      return;
    }
    setLoading(true);
    try {
      const r = await api.get("/my-skus");
      setMySkus(new Set(r.data.skus || []));
    } catch {
      // silently fail; the rest of the app keeps working without highlighting
    } finally {
      setLoading(false);
    }
  }, []);

  // Re-fetch whenever the auth token changes (login / logout)
  useEffect(() => { refresh(); }, [refresh, authTick]);

  // Watch localStorage for token changes (login fires inside the same tab)
  useEffect(() => {
    const interval = setInterval(() => {
      const t = localStorage.getItem("daleel_token") || "";
      setAuthTick((prev) => (prev === t ? prev : t));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <MySkusContext.Provider value={{ mySkus, refresh, loading }}>
      {children}
    </MySkusContext.Provider>
  );
}

export function useMySkus() {
  return useContext(MySkusContext);
}

/** Convenience: returns true if the given sku is in the user's catalog. */
export function useIsMyProduct(sku) {
  const { mySkus } = useMySkus();
  return !!sku && mySkus.has(sku);
}
