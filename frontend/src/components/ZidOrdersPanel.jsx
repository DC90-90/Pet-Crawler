import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { Link2, Link2Off, RefreshCw, ShoppingBag, AlertTriangle, CheckCircle2, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

const fmtDate = (v) => (v ? new Date(v).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function ZidOrdersPanel() {
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    try {
      const r = await api.get("/admin/zid/oauth/status");
      setStatus(r.data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to load Zid connection status");
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("zid");
    if (!p) return;
    if (p === "connected") toast.success("Zid orders connected — pulling the ledger next");
    else if (p === "denied") toast.error("Authorisation was declined in Zid");
    else toast.error(`Zid authorisation failed (${p})`);
    window.history.replaceState({}, "", window.location.pathname);
    load();
  }, [load]);

  const connect = async () => {
    setBusy("connect");
    try {
      const r = await api.post("/admin/zid/oauth/start", null, { params: { origin: window.location.origin } });
      window.location.href = r.data.authorize_url;
    } catch (e) {
      toast.error(e.response?.data?.detail || "Could not start authorisation");
      setBusy("");
    }
  };

  const disconnect = async () => {
    setBusy("disconnect");
    try {
      await api.post("/admin/zid/oauth/disconnect");
      toast.success("Disconnected");
      load();
    } catch (e) {
      toast.error("Disconnect failed");
    } finally { setBusy(""); }
  };

  const sync = async (full) => {
    setBusy(full ? "full" : "sync");
    try {
      const r = await api.post("/admin/zid/orders/sync", null, { params: { full } });
      const d = r.data || {};
      if (d.status === "ok") toast.success(`Synced ${d.upserted} order(s) across ${d.pages} page(s)`);
      else if (d.status === "auth_failed") toast.error("Zid rejected the credentials — authorise the app again");
      else if (d.status === "missing_token") toast.error("ZID_API_TOKEN / ZID_STORE_ID missing in the backend environment");
      else toast.error(`Sync ${d.status} (${d.upserted || 0} stored)`);
      load();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Sync failed");
    } finally { setBusy(""); }
  };

  if (!status) return null;
  const callback = `${window.location.origin}${status.callback_path}`;

  return (
    <div className="glass-card p-5" data-testid="zid-orders-panel">
      <div className="flex items-start justify-between mb-4 gap-3">
        <div className="flex items-center gap-2">
          <ShoppingBag className="w-5 h-5 text-[#1E988E]" />
          <div>
            <h3 className="text-sm font-semibold text-white">Zid Orders Connection</h3>
            <p className="text-[11px] text-[#A1E4DB] mt-0.5">
              Exact units and revenue for my own store — the denominator every market-share number rests on
            </p>
          </div>
        </div>
        <Badge
          className={`text-[10px] shrink-0 ${status.connected
            ? "bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30"
            : "bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30"}`}
          data-testid="zid-connection-badge">
          {status.connected ? "Connected" : status.configured ? "Not connected" : "Not configured"}
        </Badge>
      </div>

      {status.action_required && (
        <div className="flex items-start gap-2 px-3 py-2.5 mb-4 rounded-xl bg-[#F59E0B]/10 border border-[#F59E0B]/20"
          data-testid="zid-action-required">
          <AlertTriangle className="w-4 h-4 text-[#F59E0B] mt-0.5 shrink-0" />
          <p className="text-xs text-[#F59E0B]">{status.action_required}</p>
        </div>
      )}

      {!status.connected && status.configured && (
        <div className="mb-4 space-y-2">
          <p className="text-[11px] text-[#A1E4DB]">
            Register this exact callback URL in the Zid Partner dashboard (App settings → Callback URL),
            enable the <code className="text-[#1E988E]">orders.read</code> scope, then press Connect:
          </p>
          <div className="flex items-center gap-2">
            <code className="text-[11px] text-white bg-white/5 px-2 py-1.5 rounded font-mono truncate flex-1" dir="ltr"
              data-testid="zid-callback-url">{callback}</code>
            <Button variant="outline" size="sm"
              onClick={() => { navigator.clipboard.writeText(callback); toast.success("Copied"); }}
              className="rounded-full text-[10px] h-7 gap-1 border-white/10 text-[#A1E4DB] hover:text-white shrink-0"
              data-testid="zid-copy-callback-btn">
              <Copy className="w-3 h-3" /> Copy
            </Button>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        {[["Orders stored", (status.orders_stored || 0).toLocaleString()],
          ["Latest order", status.latest_order_at ? fmtDate(status.latest_order_at).split(",")[0] : "—"],
          ["Scope", status.scope || "—"],
          ["Token expires", status.expires_at ? fmtDate(status.expires_at).split(",")[0] : "—"]].map(([label, value]) => (
          <div key={label} className="kpi-card !p-3">
            <p className="text-[9px] uppercase tracking-[0.15em] text-[#A1E4DB]">{label}</p>
            <p className="text-sm font-bold text-white mt-0.5 truncate" dir="ltr"
              data-testid={`zid-kpi-${label.split(" ")[0].toLowerCase()}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {status.connected ? (
          <>
            <Button size="sm" onClick={() => sync(false)} disabled={!!busy}
              className="rounded-full text-xs gap-1.5" data-testid="zid-sync-btn">
              <RefreshCw className={`w-3.5 h-3.5 ${busy === "sync" ? "animate-spin" : ""}`} />
              {busy === "sync" ? "Syncing…" : "Sync recent orders"}
            </Button>
            <Button variant="outline" size="sm" onClick={() => sync(true)} disabled={!!busy}
              className="rounded-full text-xs gap-1.5 border-white/10 text-[#A1E4DB] hover:text-white"
              data-testid="zid-full-sync-btn">
              {busy === "full" ? "Backfilling…" : "Full backfill"}
            </Button>
            <Button variant="outline" size="sm" onClick={disconnect} disabled={!!busy}
              className="rounded-full text-xs gap-1.5 border-white/10 text-[#EF4444] hover:text-[#EF4444]"
              data-testid="zid-disconnect-btn">
              <Link2Off className="w-3.5 h-3.5" /> Disconnect
            </Button>
            <span className="text-[10px] text-[#A1E4DB] inline-flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3 text-[#10B981]" /> connected {fmtDate(status.connected_at)}
            </span>
          </>
        ) : (
          <Button size="sm" onClick={connect} disabled={!status.configured || busy === "connect"}
            className="rounded-full text-xs gap-1.5" data-testid="zid-connect-btn">
            <Link2 className="w-3.5 h-3.5" /> {busy === "connect" ? "Opening Zid…" : "Connect Zid orders"}
          </Button>
        )}
      </div>

      {status.last_error && (
        <p className="text-[10px] text-[#EF4444] mt-3" data-testid="zid-last-error">
          Last error: {typeof status.last_error === "string" ? status.last_error : JSON.stringify(status.last_error)}
        </p>
      )}
    </div>
  );
}
