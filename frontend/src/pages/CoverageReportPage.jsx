/**
 * CoverageReportPage — iter73v admin operations console.
 *
 * Shows per-store crawl / match coverage and lets a super-admin trigger
 * an immediate recrawl or a rematch (nuke + rebuild `product_matches`)
 * for one store or the entire fleet. Client-facing surface is at
 * `/settings/coverage`.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { RefreshCw, Zap, PackageSearch } from "lucide-react";

export default function CoverageReportPage() {
  const [busyStore, setBusyStore] = useState("");
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["coverage-report"],
    queryFn: async () => (await api.get("/admin/coverage-report")).data,
    staleTime: 30_000,
  });

  const triggerRecrawl = async (sid, name) => {
    setBusyStore(`recrawl:${sid}`);
    try {
      await api.post(`/admin/recrawl-store/${sid}`);
      toast.success(`Recrawl started for ${name}. Watch this table in a few minutes.`);
    } catch (e) { toast.error(`Recrawl failed: ${e.response?.data?.detail || e.message}`); }
    finally { setBusyStore(""); }
  };

  const triggerRematch = async (sid, name) => {
    setBusyStore(`rematch:${sid || "ALL"}`);
    try {
      await api.post("/admin/rematch", { store_id: sid || null });
      toast.success(sid
        ? `Rematch started for ${name}. Coverage will update in ~1 minute.`
        : "Fleet-wide rematch started. Coverage will update in a few minutes.");
      setTimeout(() => refetch(), 60_000);
    } catch (e) { toast.error(`Rematch failed: ${e.response?.data?.detail || e.message}`); }
    finally { setBusyStore(""); }
  };

  if (isLoading) {
    return <div className="p-6 text-[#A1E4DB] text-sm" data-testid="coverage-loading">Loading coverage report…</div>;
  }

  const rows = data?.stores || [];
  const totals = rows.reduce((a, r) => ({
    products: a.products + r.products_crawled,
    variants: a.variants + r.variants_captured,
    matched: a.matched + r.matched_products,
    unmatched: a.unmatched + r.unmatched_products,
  }), { products: 0, variants: 0, matched: 0, unmatched: 0 });

  return (
    <div className="p-6 space-y-5" data-testid="coverage-report-page">
      <div className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Crawl &amp; Match Coverage</h1>
          <p className="text-sm text-[#A1E4DB] mt-0.5">
            Per-store audit · window: {data?.window_days} days · generated {data?.generated_at ? new Date(data.generated_at).toLocaleString() : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={() => refetch()} className="text-xs" data-testid="coverage-refresh">
            <RefreshCw className="w-3 h-3 me-1" />Refresh
          </Button>
          <Button size="sm" onClick={() => triggerRematch("", "fleet")} disabled={busyStore === "rematch:ALL"} className="bg-[#F59E0B] text-black text-xs" data-testid="coverage-rematch-all">
            <PackageSearch className="w-3 h-3 me-1" />Rematch All
          </Button>
        </div>
      </div>

      {/* Fleet totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="coverage-totals">
        <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB]">Products crawled (14d)</p><p className="text-xl font-bold text-white mt-1">{totals.products.toLocaleString()}</p></div>
        <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB]">Variants captured</p><p className="text-xl font-bold text-white mt-1">{totals.variants.toLocaleString()}</p></div>
        <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB]">Matched competitor SKUs</p><p className="text-xl font-bold text-[#6AC1B5] mt-1">{totals.matched.toLocaleString()}</p></div>
        <div className="kpi-card"><p className="text-[10px] uppercase text-[#A1E4DB]">Unmatched</p><p className="text-xl font-bold text-[#F59E0B] mt-1">{totals.unmatched.toLocaleString()}</p></div>
      </div>

      {/* Per-store table */}
      <div className="glass-card rounded-md overflow-hidden">
        <table className="w-full text-sm" data-testid="coverage-table">
          <thead className="bg-white/5 text-[10px] uppercase text-[#A1E4DB] tracking-wider">
            <tr>
              <th className="text-start p-2">Store</th>
              <th className="text-end p-2">Products</th>
              <th className="text-end p-2">Variants</th>
              <th className="text-end p-2">SKU %</th>
              <th className="text-end p-2">Barcode %</th>
              <th className="text-end p-2">Synth %</th>
              <th className="text-end p-2">Matched</th>
              <th className="text-end p-2">Unmatched</th>
              <th className="text-end p-2">Last Crawl</th>
              <th className="text-end p-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.store_id} className="border-t border-white/5" data-testid={`coverage-row-${r.store_id}`}>
                <td className="p-2">
                  <div className="text-white">{r.name}</div>
                  <div className="text-[10px] text-[#A1E4DB] opacity-60 uppercase">{r.platform}{r.is_own_store ? " · own" : ""}</div>
                </td>
                <td className="p-2 text-end text-white tabular-nums">{r.products_crawled.toLocaleString()}</td>
                <td className="p-2 text-end text-white tabular-nums">{r.variants_captured.toLocaleString()}</td>
                <td className="p-2 text-end tabular-nums" style={{ color: r.sku_coverage_pct >= 95 ? "#6AC1B5" : r.sku_coverage_pct >= 70 ? "#F59E0B" : "#EF4444" }}>{r.sku_coverage_pct}%</td>
                <td className="p-2 text-end tabular-nums" style={{ color: r.barcode_coverage_pct >= 95 ? "#6AC1B5" : r.barcode_coverage_pct >= 70 ? "#F59E0B" : "#EF4444" }}>{r.barcode_coverage_pct}%</td>
                <td className="p-2 text-end tabular-nums" style={{ color: r.synthetic_sku_rate_pct <= 5 ? "#6AC1B5" : r.synthetic_sku_rate_pct <= 30 ? "#F59E0B" : "#EF4444" }}>{r.synthetic_sku_rate_pct}%</td>
                <td className="p-2 text-end text-[#6AC1B5] tabular-nums">{r.matched_products.toLocaleString()}</td>
                <td className="p-2 text-end text-[#F59E0B] tabular-nums">{r.unmatched_products.toLocaleString()}</td>
                <td className="p-2 text-end text-[10px] text-[#A1E4DB]">{r.last_full_crawl ? new Date(r.last_full_crawl).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }) : "never"}</td>
                <td className="p-2 text-end">
                  <div className="flex gap-1 justify-end">
                    <Button size="sm" variant="outline" className="text-[10px] h-6 px-2" onClick={() => triggerRecrawl(r.store_id, r.name)} disabled={busyStore === `recrawl:${r.store_id}`} data-testid={`recrawl-${r.store_id}`}>
                      <Zap className="w-3 h-3" />
                    </Button>
                    <Button size="sm" variant="outline" className="text-[10px] h-6 px-2" onClick={() => triggerRematch(r.store_id, r.name)} disabled={busyStore === `rematch:${r.store_id}`} data-testid={`rematch-${r.store_id}`}>
                      <PackageSearch className="w-3 h-3" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-[#A1E4DB] opacity-70">
        Zap = trigger immediate recrawl &middot; Package = nuke &amp; rebuild this store&apos;s matches &middot;
        Target: SKU% and Barcode% &ge; 95, Synth% &le; 5. If Synth% is high, the crawler is falling back to synthetic SKUs because neither root nor variant SKU was populated on Salla&apos;s list-API response for those products. Recrawl to trigger detail-supplement + DOM read for full coverage.
      </p>
    </div>
  );
}
