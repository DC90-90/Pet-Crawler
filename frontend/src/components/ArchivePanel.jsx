import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { Archive, Download, RefreshCw, ChevronDown, ChevronRight, CloudOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const fmtBytes = (b) => {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(Math.floor(Math.log(b) / Math.log(1024)), u.length - 1);
  return `${(b / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${u[i]}`;
};

const KIND_LABEL = {
  snapshots: "Prices & stock",
  sku_sales_daily: "Daily sales rollup",
  daily_ledger: "Daily ledger",
  manifest: "Manifest",
};

export default function ArchivePanel() {
  const [status, setStatus] = useState(null);
  const [openDay, setOpenDay] = useState(null);
  const [files, setFiles] = useState({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.get("/admin/archive/status");
      setStatus(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load archive status");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const openFiles = async (date) => {
    if (openDay === date) { setOpenDay(null); return; }
    setOpenDay(date);
    if (files[date]) return;
    try {
      const r = await api.get("/admin/archive/files", { params: { date } });
      setFiles((f) => ({ ...f, [date]: r.data.files }));
    } catch (e) {
      toast.error("Failed to list files");
    }
  };

  const runNow = async () => {
    setBusy(true);
    try {
      const r = await api.post("/admin/archive/run");
      toast.success(`Archiving ${r.data.date} — refreshing in a moment`);
      setTimeout(load, 6000);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Archive run failed");
    } finally {
      setBusy(false);
    }
  };

  const download = async (f) => {
    try {
      const r = await api.get("/admin/archive/download", {
        params: { path: f.path }, responseType: "blob",
      });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${f.date}_${(f.store_name || f.kind).replace(/[^\w.-]+/g, "-")}.${f.path.endsWith(".json") ? "json" : "jsonl.gz"}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error("Download failed");
    }
  };

  if (!status) return null;

  return (
    <div className="glass-card p-5" data-testid="archive-panel">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Archive className="w-5 h-5 text-[#1E988E]" />
          <div>
            <h3 className="text-sm font-semibold text-white">Price History Archive</h3>
            <p className="text-[11px] text-[#A1E4DB] mt-0.5">
              Every crawl night is frozen in cloud storage — prices, stock, discounts and the daily rollups
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={load}
            className="rounded-full text-xs gap-1.5 border-white/10 text-[#A1E4DB] hover:text-white"
            data-testid="archive-refresh-btn">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </Button>
          <Button size="sm" onClick={runNow} disabled={busy || !status.configured}
            className="rounded-full text-xs gap-1.5" data-testid="archive-run-btn">
            <Archive className="w-3.5 h-3.5" /> {busy ? "Starting…" : "Archive last night"}
          </Button>
        </div>
      </div>

      {!status.configured ? (
        <div className="flex items-center gap-2 text-xs text-yellow-500" data-testid="archive-not-configured">
          <CloudOff className="w-4 h-4" /> Cloud storage key is not configured — nightly archive is off
        </div>
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
            {[["Nights archived", status.total_days],
              ["Files", status.total_files],
              ["Rows", (status.total_rows || 0).toLocaleString()],
              ["Stored", fmtBytes(status.total_bytes)]].map(([label, value]) => (
              <div key={label} className="kpi-card !p-3">
                <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p>
                <p className="text-lg font-bold text-white mt-0.5" data-testid={`archive-kpi-${label.split(" ")[0].toLowerCase()}`}>{value}</p>
              </div>
            ))}
          </div>

          {status.days.length === 0 ? (
            <p className="text-xs text-[#A1E4DB]" data-testid="archive-empty">
              Nothing archived yet — the first run happens tonight at 06:00 KSA, or press “Archive last night”
            </p>
          ) : (
            <div className="rounded-md border border-white/10 divide-y divide-white/5 max-h-[420px] overflow-y-auto">
              {status.days.map((d, i) => (
                <div key={d.date}>
                  <button onClick={() => openFiles(d.date)}
                    className="w-full flex items-center justify-between px-3 py-2 text-start transition-colors hover:bg-white/5"
                    data-testid={`archive-day-${i}`}>
                    <div className="flex items-center gap-2">
                      {openDay === d.date ? <ChevronDown className="w-3.5 h-3.5 text-[#A1E4DB]" /> : <ChevronRight className="w-3.5 h-3.5 text-[#A1E4DB]" />}
                      <span className="text-xs font-medium text-white" dir="ltr">{d.date}</span>
                      <Badge variant="outline" className="text-[9px] border-white/15 text-[#A1E4DB]">{d.files} files</Badge>
                    </div>
                    <span className="text-[11px] text-[#A1E4DB]" dir="ltr">{(d.rows || 0).toLocaleString()} rows · {fmtBytes(d.bytes)}</span>
                  </button>
                  {openDay === d.date && (
                    <div className="bg-white/[0.02] px-3 py-2 space-y-1">
                      {(files[d.date] || []).map((f, fi) => (
                        <div key={f.path} className="flex items-center justify-between gap-2"
                          data-testid={`archive-file-${fi}`}>
                          <div className="min-w-0">
                            <p className="text-xs text-white truncate">{f.store_name || KIND_LABEL[f.kind] || f.kind}</p>
                            <p className="text-[10px] text-[#A1E4DB]" dir="ltr">
                              {KIND_LABEL[f.kind] || f.kind} · {(f.rows || 0).toLocaleString()} rows · {fmtBytes(f.bytes)}
                            </p>
                          </div>
                          <Button variant="outline" size="sm" onClick={() => download(f)}
                            className="rounded-full text-[10px] h-7 gap-1 border-white/10 text-[#A1E4DB] hover:text-white shrink-0"
                            data-testid={`archive-download-${fi}`}>
                            <Download className="w-3 h-3" /> Download
                          </Button>
                        </div>
                      ))}
                      {(files[d.date] || []).length === 0 && (
                        <p className="text-[11px] text-[#A1E4DB]">Loading…</p>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
