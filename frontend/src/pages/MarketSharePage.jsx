import { useCallback, useEffect, useMemo, useState } from "react";
import api, { API_BASE } from "@/lib/api";
import { toast } from "sonner";
import { CATEGORY_LABELS } from "@/lib/i18n";
import { PieChart, Download, RefreshCw, Filter, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import ShareOverview from "@/components/marketShare/ShareOverview";
import MyProductsShare from "@/components/marketShare/MyProductsShare";
import MissingProducts from "@/components/marketShare/MissingProducts";
import BrandShare from "@/components/marketShare/BrandShare";
import CategoryShare from "@/components/marketShare/CategoryShare";
import Methodology from "@/components/marketShare/Methodology";
import ProductBreakdown from "@/components/marketShare/ProductBreakdown";
import { ComparisonScope, useComparisonScope } from "@/components/ComparisonScope";
import { RequestError } from "@/components/RequestError";

const RANGES = [7, 14, 30, 90];
const TABS = [
  ["overview", "Overview"],
  ["my-products", "My Products"],
  ["breakdown", "Competitor Breakdown"],
  ["missing", "Missing Products"],
  ["brands", "Brands"],
  ["categories", "Categories"],
  ["methodology", "Methodology"],
];
const catLabel = (c) => (CATEGORY_LABELS[c]?.en || c);

export default function MarketSharePage() {
  const scope = useComparisonScope();
  const [optionsError, setOptionsError] = useState(false);
  const [days, setDays] = useState(30);
  const [tab, setTab] = useState("overview");
  const [opts, setOpts] = useState({ categories: [], brands: [], stores: [] });
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [brand, setBrand] = useState("");
  const [storeId, setStoreId] = useState("");
  const [catalog, setCatalog] = useState("all");
  const [minConfidence, setMinConfidence] = useState("");
  const [quality, setQuality] = useState("");
  const [picked, setPicked] = useState(null);
  const [nonce, setNonce] = useState(0);
  const [includeToday, setIncludeToday] = useState(false);
  const [contested, setContested] = useState(false);

  useEffect(() => {
    setOptionsError(false);
    api.get("/market-share/overview", { params: { days, include_today: includeToday } })
      .then((r) => setOpts(r.data.filters || { categories: [], brands: [], stores: [] }))
      .catch(() => setOptionsError(true));
  }, [days, nonce, includeToday]);

  const filters = useMemo(() => {
    const f = { ...scope.params };
    if (search.trim()) f.search = search.trim();
    if (category) f.category = category;
    if (brand) f.brand = brand;
    if (storeId) f.store_id = storeId;
    if (catalog !== "all") f.catalog = catalog;
    if (minConfidence) f.min_confidence = Number(minConfidence);
    if (quality) f.quality = quality;
    if (contested) f.contested = true;
    return f;
  }, [search, category, brand, storeId, catalog, minConfidence, quality, contested, scope.params]);

  const activeFilters = Object.keys(filters).filter(k => !["comparison_mode", "competitor_ids"].includes(k)).length;

  const clearFilters = () => {
    setSearch(""); setCategory(""); setBrand(""); setStoreId("");
    setCatalog("all"); setMinConfidence(""); setQuality(""); setContested(false);
  };

  const exportCsv = useCallback(async () => {
    const section = tab === "missing" ? "missing"
      : tab === "brands" ? "brands"
        : tab === "categories" ? "categories" : "my_products";
    try {
      const r = await api.get("/market-share/export", {
        params: { days, section, include_today: includeToday, ...filters },
        responseType: "blob",
      });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `daleel_market_share_${section}_${days}d.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error("Export failed");
    }
  }, [tab, days, filters, includeToday]);

  const pickProduct = (row) => setPicked(row.sku || row.canonical_key);

  return (
    <div className="p-6 space-y-5" data-testid="market-share-page">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white flex items-center gap-2">
            <PieChart className="w-5 h-5 text-[#1E988E]" /> Market Share
          </h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">
            Tracked-store coverage · order totals where complete · inventory proxies labelled separately
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 min-w-0 max-w-full" data-testid="ms-header-controls">
          <div className="flex gap-1" data-testid="ms-range">
            {RANGES.map((d) => (
              <Button key={d} size="sm" variant={days === d ? "default" : "outline"}
                onClick={() => setDays(d)}
                className={`text-xs rounded-md h-7 px-3 ${days === d ? "bg-[#1E988E] text-white" : "border-white/10 text-[#A1E4DB]"}`}
                data-testid={`ms-range-${d}`}>{d}D</Button>
            ))}
          </div>
          <button onClick={() => setIncludeToday((v) => !v)}
            title="Includes today's partial inventory observations and available order evidence."
            className={`text-[10px] rounded-full px-2.5 h-7 border transition-colors ${includeToday
              ? "bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30"
              : "bg-white/5 text-[#A1E4DB] border-white/10 hover:text-white"}`}
            data-testid="ms-include-today">
            {includeToday ? "Including today (partial)" : "Sealed days only"}
          </button>
          <Button variant="outline" size="sm" onClick={() => setNonce((n) => n + 1)}
            className="rounded-md text-xs h-7 border-white/10 text-[#A1E4DB]" data-testid="ms-refresh">
            <RefreshCw className="w-3 h-3 me-1" /> Refresh
          </Button>
          {tab !== "overview" && tab !== "methodology" && (
            <Button size="sm" onClick={exportCsv} className="rounded-md text-xs h-7" data-testid="ms-export">
              <Download className="w-3 h-3 me-1" /> CSV
            </Button>
          )}
        </div>
      </div>

      <div className="flex flex-wrap gap-1 pb-1" data-testid="ms-tabs">
        {TABS.map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`whitespace-nowrap px-3 py-1.5 rounded-full text-xs transition-colors ${
              tab === id ? "bg-[#1E988E] text-white" : "bg-white/5 text-[#A1E4DB] hover:bg-white/10"}`}
            data-testid={`ms-tab-${id}`}>
            {label}
          </button>
        ))}
      </div>

      <ComparisonScope scope={scope} prefix="ms" />
      {optionsError && <RequestError id="ms-filter-options" onRetry={() => setNonce(n => n + 1)} />}
      {tab !== "methodology" && (
        <div className="glass-card p-3" data-testid="ms-filters">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-[#A1E4DB]">
              <Filter className="w-3.5 h-3.5" /> Filters
            </div>
            <input value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Name, SKU, barcode or brand"
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5 w-[220px] placeholder:text-[#A1E4DB]/60"
              data-testid="ms-filter-search" />
            <select value={category} onChange={(e) => setCategory(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5"
              data-testid="ms-filter-category">
              <option value="" className="bg-[#0B1220]">All categories</option>
              {opts.categories.map((c) => <option key={c} value={c} className="bg-[#0B1220]">{catLabel(c)}</option>)}
            </select>
            <select value={brand} onChange={(e) => setBrand(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5 max-w-[160px]"
              data-testid="ms-filter-brand">
              <option value="" className="bg-[#0B1220]">All brands</option>
              {opts.brands.map((b) => <option key={b} value={b} className="bg-[#0B1220]">{b}</option>)}
            </select>
            <select value={storeId} onChange={(e) => setStoreId(e.target.value)}
              aria-label="Store membership — does not change comparison scope"
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5"
              data-testid="ms-filter-store">
              <option value="" className="bg-[#0B1220]">Membership: any store</option>
              {opts.stores.map((s) => (
                <option key={s.store_id} value={s.store_id} className="bg-[#0B1220]">{s.store_name}</option>
              ))}
            </select>
            <select value={catalog} onChange={(e) => setCatalog(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5"
              data-testid="ms-filter-catalog">
              <option value="all" className="bg-[#0B1220]">In / out of catalog</option>
              <option value="mine" className="bg-[#0B1220]">In my catalog</option>
              <option value="not_mine" className="bg-[#0B1220]">Not in my catalog</option>
            </select>
            <select value={minConfidence} onChange={(e) => setMinConfidence(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5"
              data-testid="ms-filter-match">
              <option value="" className="bg-[#0B1220]">Any match strength</option>
              <option value="99" className="bg-[#0B1220]">GTIN only (99%)</option>
              <option value="95" className="bg-[#0B1220]">GTIN or exact SKU (≥95%)</option>
              <option value="88" className="bg-[#0B1220]">Including variants (≥88%)</option>
            </select>
            <select value={quality} onChange={(e) => setQuality(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-md text-xs text-white px-2 py-1.5"
              data-testid="ms-filter-quality">
              <option value="" className="bg-[#0B1220]">Any data quality</option>
              <option value="high" className="bg-[#0B1220]">High only</option>
              <option value="medium" className="bg-[#0B1220]">Medium and up</option>
              <option value="low" className="bg-[#0B1220]">Low and up</option>
            </select>
            <button onClick={() => setContested((v) => !v)}
              title="Products with another tracked seller's observation signal; exact share still requires complete transaction evidence."
              className={`text-[10px] rounded-md px-2.5 py-1.5 border transition-colors ${contested
                ? "bg-[#1E988E]/20 text-[#5FD3C7] border-[#1E988E]/40"
                : "bg-white/5 text-[#A1E4DB] border-white/10 hover:text-white"}`}
              data-testid="ms-filter-contested">
              Contested only
            </button>
            {activeFilters > 0 && (
              <Button variant="outline" size="sm" onClick={clearFilters}
                className="rounded-full text-[10px] h-7 border-white/10 text-[#A1E4DB]"
                data-testid="ms-filter-clear">
                <X className="w-3 h-3 me-1" /> Clear {activeFilters}
              </Button>
            )}
          </div>
        </div>
      )}

      {tab === "overview" && (
        <ShareOverview days={days} includeToday={includeToday} filters={filters}
          onPickProduct={pickProduct} onGoto={setTab} key={`ov-${nonce}-${includeToday}`} />
      )}
      {tab === "my-products" && (
        <MyProductsShare days={days} includeToday={includeToday} filters={filters}
          onPickProduct={pickProduct} key={`mp-${nonce}-${includeToday}`} />
      )}
      {tab === "breakdown" && (
        <div className="space-y-3" data-testid="ms-breakdown-tab">
          <p className="text-[11px] text-[#A1E4DB]">
            Pick any product to see exactly which competitors sell it, at what price, and how each
            one performs. Every seller is listed — including stores whose sales cannot be measured.
          </p>
          <MyProductsShare days={days} includeToday={includeToday} filters={filters}
            onPickProduct={pickProduct} key={`bd-${nonce}-${includeToday}`} />
        </div>
      )}
      {tab === "missing" && (
        <MissingProducts days={days} includeToday={includeToday} filters={filters}
          onPickProduct={pickProduct} key={`mi-${nonce}-${includeToday}`} />
      )}
      {tab === "brands" && <BrandShare days={days} includeToday={includeToday} filters={filters} key={`br-${nonce}-${includeToday}`} />}
      {tab === "categories" && <CategoryShare days={days} includeToday={includeToday} filters={filters} key={`ca-${nonce}-${includeToday}`} />}
      {tab === "methodology" && <Methodology days={days} includeToday={includeToday} scopeParams={scope.params} key={`me-${nonce}-${includeToday}`} />}

      <ProductBreakdown productKey={picked} days={days} includeToday={includeToday} scopeParams={scope.params}
        open={!!picked} onClose={() => setPicked(null)} />
    </div>
  );
}
