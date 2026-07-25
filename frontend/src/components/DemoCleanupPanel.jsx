import { useEffect, useState, useCallback } from "react";
import api from "@/lib/api";
import { toast } from "sonner";
import { Trash2, ShieldAlert, CheckCircle2, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { catLabel } from "@/lib/i18n";

// iter43 — super-admin-only demo/seed cleanup panel (Settings page).
// Opens with the GET dry run (which can never delete), shows the full report,
// and arms the destructive POST only when the guard is clean — sending the
// exact reviewed count as confirm_count so the backend refuses if the catalog
// changed between review and click.
export default function DemoCleanupPanel({ isRTL }) {
  const [report, setReport] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const fetchDryRun = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.get("/admin/demo-cleanup", { params: { dry_run: true } });
      setReport(r.data);
    } catch (e) {
      setError(e.response?.data?.detail || "Failed to load dry run");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => { fetchDryRun(); }, [fetchDryRun]);

  const runCleanup = async () => {
    const n = report?.guard?.confirm_count_required ?? report?.demo_products;
    const msg = isRTL
      ? `سيؤدي هذا إلى حذف ${n} منتجاً تجريبياً وسجلّاتها نهائياً. تُكتب نسخ احتياطية أولاً. متابعة؟`
      : `This permanently deletes ${n} demo products and their history. Backups are written first. Continue?`;
    if (!window.confirm(msg)) return;
    setBusy(true);
    try {
      const r = await api.post(`/admin/demo-cleanup?dry_run=false&confirm_count=${n}`);
      setResult(r.data);
      toast.success(isRTL ? "اكتمل حذف البيانات التجريبية" : "Demo cleanup complete");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Cleanup refused");
    } finally {
      setBusy(false);
    }
  };

  if (error) {
    return (
      <div className="glass-card p-5" data-testid="demo-cleanup-panel">
        <p className="text-xs text-[#EF4444]">{error}</p>
      </div>
    );
  }
  if (!report) {
    return (
      <div className="glass-card p-5" data-testid="demo-cleanup-panel">
        <p className="text-xs text-[#A1E4DB]">{isRTL ? "جارٍ تحميل الفحص التجريبي…" : "Loading dry run…"}</p>
      </div>
    );
  }

  const guard = report.guard || {};
  const n = guard.confirm_count_required ?? report.demo_products;
  const blocked = !!guard.real_sku_match || !guard.ok;
  const after = result?.after;

  return (
    <div className="glass-card p-5" data-testid="demo-cleanup-panel">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Trash2 className="w-5 h-5 text-[#EF4444]" />
          <h3 className="text-sm font-semibold text-white">{isRTL ? "حذف البيانات التجريبية" : "Demo Data Cleanup"}</h3>
        </div>
        <Button variant="outline" size="sm" onClick={fetchDryRun} disabled={busy}
          className="rounded-full text-xs gap-1.5 border-white/10 text-[#A1E4DB] hover:text-white hover:border-white/20"
          data-testid="demo-cleanup-refresh">
          <RefreshCw className="w-3.5 h-3.5" />{isRTL ? "تحديث" : "Refresh"}
        </Button>
      </div>

      {/* guard status */}
      {blocked ? (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-medium bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/20 mb-3"
          data-testid="demo-cleanup-guard-blocked">
          <ShieldAlert className="w-4 h-4 shrink-0" />
          <span>{(guard.reasons || []).join(" · ") || (isRTL ? "محظور بواسطة الحماية" : "Blocked by safety guard")}</span>
        </div>
      ) : (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-medium bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/20 mb-3"
          data-testid="demo-cleanup-guard-ok">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{isRTL ? "الحماية سليمة — لا تطابق مع منتجات حقيقية" : "Guard clean — no real-product SKUs matched"}</span>
        </div>
      )}

      {/* dry-run report */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-3">
        <div><p className="text-[9px] uppercase text-[#A1E4DB]">{isRTL ? "منتجات تجريبية" : "Demo Products"}</p>
          <p className="text-lg font-bold text-white metric-number" data-testid="demo-count">{report.demo_products}</p></div>
        <div><p className="text-[9px] uppercase text-[#A1E4DB]">My Products</p>
          <p className="text-lg font-bold text-white metric-number">{report.before?.my_products_total?.toLocaleString()}</p></div>
        <div><p className="text-[9px] uppercase text-[#A1E4DB]">{isRTL ? "المطابقات" : "Matches"}</p>
          <p className="text-lg font-bold text-white metric-number">{report.before?.total_matches?.toLocaleString()}</p></div>
        <div><p className="text-[9px] uppercase text-[#A1E4DB]">{isRTL ? "لقطات ستُحذف" : "Snapshots to remove"}</p>
          <p className="text-lg font-bold text-[#F59E0B] metric-number">{report.cascade_counts?.product_snapshots?.toLocaleString()}</p></div>
      </div>

      {Object.keys(report.by_category || {}).length > 0 && (
        <div className="mb-3">
          <p className="text-[9px] uppercase text-[#A1E4DB] mb-1">{isRTL ? "حسب الفئة" : "By category"}</p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(report.by_category).map(([k, v]) => (
              <span key={k} className="text-[10px] px-2 py-0.5 rounded bg-white/5 text-[#A1E4DB]">
                {catLabel(k, isRTL)}: <span className="text-white metric-number">{v}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mb-4">
        <p className="text-[9px] uppercase text-[#A1E4DB] mb-1">{isRTL ? "الحذف المتسلسل" : "Cascade"}</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(report.cascade_counts || {}).map(([k, v]) => (
            <span key={k} className={`text-[10px] px-2 py-0.5 rounded font-mono ${v > 0 ? "bg-[#EF4444]/10 text-[#F87171]" : "bg-white/5 text-[#A1E4DB] opacity-60"}`}>
              {k}: {v}
            </span>
          ))}
        </div>
      </div>

      {!result && (
        <Button onClick={runCleanup} disabled={blocked || busy || n === 0}
          className="rounded-full bg-[#EF4444] text-white font-semibold hover:bg-[#DC2626] disabled:opacity-40"
          data-testid="demo-cleanup-delete-btn">
          <Trash2 className="w-4 h-4 me-1.5" />
          {isRTL ? `حذف ${n} منتجاً تجريبياً` : `Delete ${n} demo products`}
        </Button>
      )}
      {blocked && (
        <p className="text-[10px] text-[#F87171] mt-2">
          {isRTL ? "الحذف معطّل حتى تُحل أسباب الحماية أعلاه." : "Deletion is disabled until the guard reasons above are resolved."}
        </p>
      )}

      {/* after: before/after + recompute confirmation */}
      {after && (
        <div className="mt-4 border-t border-white/5 pt-3" data-testid="demo-cleanup-result">
          <p className="text-xs font-semibold text-[#10B981] mb-2">
            {isRTL ? "اكتمل الحذف — النسخ الاحتياطية:" : "Cleanup complete — backups:"}{" "}
            <code className="font-mono text-[10px]">demo_cleanup_backup_{result.backup_timestamp}_*</code>
          </p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div><p className="text-[9px] uppercase text-[#A1E4DB]">My Products</p>
              <p className="text-sm font-bold text-white metric-number">
                {result.before.my_products_total.toLocaleString()} → {after.my_products_total.toLocaleString()}</p></div>
            <div><p className="text-[9px] uppercase text-[#A1E4DB]">{isRTL ? "المطابقات" : "Matches"}</p>
              <p className="text-sm font-bold text-white metric-number">
                {result.before.total_matches.toLocaleString()} → {after.total_matches.toLocaleString()}</p></div>
            <div className="md:col-span-2"><p className="text-[9px] uppercase text-[#A1E4DB]">{isRTL ? "إعادة الحساب" : "Recompute"}</p>
              <p className="text-[10px] text-[#6AC1B5] font-mono">
                metrics: {typeof result.recompute?.store_metrics === "object" ? "ok" : String(result.recompute?.store_metrics)}
                {" · "}dash: {result.recompute?.dashboard_cache}{" · "}pages: {result.recompute?.page_caches}
              </p></div>
          </div>
        </div>
      )}
    </div>
  );
}
