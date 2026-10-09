import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ComparisonScope, useComparisonScope } from "@/components/ComparisonScope";
import { ObservationNotice } from "@/components/ReleaseBoundary";
import { PriceIntelTabContent } from "@/components/priceIntel/PriceIntelTabs";
import { PriceIntelDetailSheet } from "@/components/priceIntel/PriceIntelDetailSheet";
import { RequestError } from "@/components/RequestError";

export default function PriceComparisonPage() {
  const scope = useComparisonScope();
  const [sku, setSku] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(false);
  const request = useRef(0);
  const query = useQuery({ queryKey: ["observed-prices", scope.params], retry: false, refetchInterval: 60000,
    queryFn: () => api.get("/price-intel/dashboard", { params: scope.params, timeout: 45000 }).then(r => r.data) });
  const close = () => { request.current += 1; setSku(null); setDetail(null); setError(false); };
  useEffect(() => { request.current += 1; setSku(null); setDetail(null); setError(false); }, [scope.params]);
  const open = async value => {
    const id = ++request.current;
    setSku(value); setDetail(null); setError(false);
    try {
      const r = await api.get(`/price-intel/product/${encodeURIComponent(value)}`, { params: scope.params, timeout: 45000 });
      if (id === request.current) setDetail(r.data);
    } catch { if (id === request.current) setError(true); }
  };
  return <div className="p-4 sm:p-6 space-y-5" data-testid="intel-page">
    <h1 className="text-4xl font-semibold text-white">Observed prices</h1>
    <ObservationNotice />
    <ComparisonScope scope={scope} prefix="intel" />
    {query.isError ? <RequestError id="intel-request" onRetry={query.refetch} /> : query.isLoading ?
      <p className="text-sm text-[#A1E4DB]" data-testid="intel-loading">Loading observations…</p> :
      <PriceIntelTabContent activeTab="full" data={query.data} onOpen={open} />}
    <PriceIntelDetailSheet selectedSku={sku} detail={detail} onClose={close} error={error} onRetry={() => open(sku)} readOnly />
  </div>;
}