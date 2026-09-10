import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { Shield, KeyRound, CheckCircle2, XCircle, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/App";
import DemoCleanupPanel from "@/components/DemoCleanupPanel";
import ArchivePanel from "@/components/ArchivePanel";
import ZidOrdersPanel from "@/components/ZidOrdersPanel";

export default function SettingsPage() {
  const { isRTL } = useI18n();
  const { user } = useAuth();
  const [encryptionOk, setEncryptionOk] = useState(null);
  const [importStatus, setImportStatus] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      const r = await api.get("/import/status");
      setImportStatus(r.data);
    } catch {}
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const verifyEncryption = async () => {
    try {
      const r = await api.get("/encryption/verify");
      setEncryptionOk(r.data.ok);
      toast[r.data.ok ? "success" : "error"](r.data.ok ? "Encryption active" : "Encryption error");
    } catch {
      setEncryptionOk(false);
      toast.error("Encryption check failed");
    }
  };

  const autoGenerateAlerts = async () => {
    try {
      const r = await api.post("/alerts/auto-generate");
      toast.success(r.data.message);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to generate alerts");
    }
  };

  return (
    <div className="p-6 space-y-5" data-testid="settings-page">
      <div>
        <h1 className="text-2xl font-semibold text-white">{isRTL ? "الإعدادات" : "Settings"}</h1>
        <p className="text-sm text-[#A1E4DB] mt-0.5">{isRTL ? "إدارة النظام والتشفير" : "System management and encryption"}</p>
      </div>

      {/* Encryption Status */}
      <div className="glass-card p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Shield className="w-5 h-5 text-[#1E988E]" />
            <h3 className="text-sm font-semibold text-white">{isRTL ? "حالة التشفير" : "Encryption Status"}</h3>
          </div>
          <Button variant="outline" size="sm" onClick={verifyEncryption}
            className="rounded-full text-xs gap-1.5 border-white/10 text-[#A1E4DB] hover:text-white hover:border-white/20"
            data-testid="verify-encryption-btn">
            <KeyRound className="w-3.5 h-3.5" />
            {isRTL ? "تحقق" : "Verify"}
            {encryptionOk === true && <CheckCircle2 className="w-3.5 h-3.5 text-[#10B981]" />}
            {encryptionOk === false && <XCircle className="w-3.5 h-3.5 text-[#EF4444]" />}
          </Button>
        </div>
        {encryptionOk !== null && (
          <div className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium ${
            encryptionOk ? "bg-[#10B981]/10 text-[#10B981] border border-[#10B981]/20" : "bg-[#EF4444]/10 text-[#EF4444] border border-[#EF4444]/20"
          }`} data-testid="encryption-status-banner">
            {encryptionOk ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
            {encryptionOk ? "Encryption Active — Fernet AES-128" : "Encryption Error — Check ENCRYPTION_KEY"}
          </div>
        )}
      </div>

      {/* External Crawler API */}
      <div className="glass-card p-5">
        <div className="flex items-center gap-2 mb-4">
          <Server className="w-5 h-5 text-[#1E988E]" />
          <h3 className="text-sm font-semibold text-white">{isRTL ? "واجهة الزاحف الخارجي" : "External Crawler API"}</h3>
        </div>
        <div className="space-y-3 text-sm">
          <div className="flex items-center justify-between py-2 border-b border-white/5">
            <span className="text-[#A1E4DB]">Endpoint</span>
            <code className="text-xs text-[#1E988E] bg-white/5 px-2 py-1 rounded font-mono">POST /api/crawler/ingest</code>
          </div>
          <div className="flex items-center justify-between py-2 border-b border-white/5">
            <span className="text-[#A1E4DB]">Authentication</span>
            <code className="text-xs text-white bg-white/5 px-2 py-1 rounded font-mono">Bearer CRAWLER_TOKEN</code>
          </div>
          <div className="flex items-center justify-between py-2">
            <span className="text-[#A1E4DB]">Data Source</span>
            <span className="text-xs text-white">Saudi IP Python Crawler</span>
          </div>
        </div>
      </div>

      {/* Zid Orders Connection (iter79) — super_admin only */}
      {user?.role === "super_admin" && <ZidOrdersPanel />}

      {/* Demo Data Cleanup (iter43) — super_admin only */}
      {user?.role === "super_admin" && <DemoCleanupPanel isRTL={isRTL} />}

      {/* Price History Archive (iter78) — super_admin only */}
      {user?.role === "super_admin" && <ArchivePanel />}

      {/* Auto-Generate Alerts */}
      <div className="glass-card p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <h3 className="text-sm font-semibold text-white">{isRTL ? "إنشاء تنبيهات تلقائية" : "Auto-Generate Alerts"}</h3>
            <p className="text-xs text-[#A1E4DB] mt-0.5">Create alerts from Price Intel data: overpriced products, OOS opportunities, catalog gaps</p>
          </div>
          <Button onClick={autoGenerateAlerts}
            className="rounded-full bg-[#F59E0B] text-[#090E1C] font-semibold hover:bg-[#FBBF24]"
            data-testid="auto-generate-alerts-btn">
            {isRTL ? "إنشاء التنبيهات" : "Generate Alerts"}
          </Button>
        </div>
      </div>

      {/* System Status */}
      {importStatus && (
        <div className="glass-card p-5">
          <h3 className="text-sm font-semibold text-white mb-3">{isRTL ? "حالة النظام" : "System Status"}</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div><p className="text-[9px] uppercase text-[#A1E4DB]">My Products</p><p className="text-lg font-bold text-white metric-number">{importStatus.my_products?.toLocaleString()}</p></div>
            <div><p className="text-[9px] uppercase text-[#A1E4DB]">Matches</p><p className="text-lg font-bold text-[#1E988E] metric-number">{importStatus.total_matches?.toLocaleString()}</p></div>
            <div><p className="text-[9px] uppercase text-[#A1E4DB]">Confirmed</p><p className="text-lg font-bold text-[#10B981] metric-number">{importStatus.confirmed_matches}</p></div>
            <div><p className="text-[9px] uppercase text-[#A1E4DB]">Blacklisted</p><p className="text-lg font-bold text-[#EF4444] metric-number">{importStatus.blacklisted}</p></div>
          </div>
        </div>
      )}
    </div>
  );
}
