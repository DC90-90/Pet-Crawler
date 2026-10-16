/**
 * A store's logo (its site icon) with the store's initials as the fallback, and
 * the shared store list behind it. One request per session: /stores/brands.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export function useStoreBrands() {
  const q = useQuery({
    queryKey: ["store-brands"],
    queryFn: async () => (await api.get("/stores/brands")).data,
    staleTime: 60 * 60 * 1000,
  });
  const list = q.data || [];
  const byId = {};
  const byName = {};
  list.forEach((s) => { byId[s.id] = s; byName[(s.name || "").toLowerCase()] = s; });
  return { list, byId, byName, isLoading: q.isLoading };
}

const initials = (name) => (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

export function StoreLogo({ storeId, name, size = 20, className = "" }) {
  const { byId, byName } = useStoreBrands();
  const store = byId[storeId] || byName[(name || "").toLowerCase()];
  const [failed, setFailed] = useState(false);
  const domain = store?.domain;
  const box = { width: size, height: size };
  if (!domain || failed) {
    return (
      <span className={`inline-flex items-center justify-center rounded bg-[#1E988E]/20 text-[#6AC1B5] font-bold shrink-0 ${className}`}
        style={{ ...box, fontSize: Math.max(8, size * 0.42) }} title={store?.name || name} data-testid="store-logo-fallback">
        {initials(store?.name || name)}
      </span>
    );
  }
  return (
    <img src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`} alt={store?.name || name || ""}
      title={store?.name || name} loading="lazy" onError={() => setFailed(true)}
      className={`rounded bg-white object-contain shrink-0 ${className}`} style={box} data-testid="store-logo" />
  );
}
