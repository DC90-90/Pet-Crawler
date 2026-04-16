import { useEffect, useState, useCallback } from "react";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { toast } from "sonner";
import { Shield, ShieldCheck, ShieldAlert, ShieldX, Eye, EyeOff, KeyRound, Trash2, TestTube, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogDescription } from "@/components/ui/dialog";

const STATUS_CFG = {
  active: { label: "Active", labelAr: "نشط", color: "bg-green-50 text-green-700 border-green-200", icon: ShieldCheck },
  otp_required: { label: "OTP Required", labelAr: "مطلوب رمز", color: "bg-orange-50 text-orange-700 border-orange-200", icon: ShieldAlert },
  expired: { label: "Expired", labelAr: "منتهي", color: "bg-red-50 text-red-700 border-red-200", icon: ShieldX },
  not_configured: { label: "Not Configured", labelAr: "غير مهيأ", color: "bg-gray-50 text-gray-500 border-gray-200", icon: Shield },
};

const PLATFORM_COLORS = {
  salla: "bg-purple-50 text-purple-700 border-purple-200",
  zid: "bg-blue-50 text-blue-700 border-blue-200",
  shopify: "bg-green-50 text-green-700 border-green-200",
  woocommerce: "bg-indigo-50 text-indigo-700 border-indigo-200",
  custom: "bg-gray-50 text-gray-600 border-gray-200",
};

export default function SettingsPage() {
  const { t, isRTL } = useI18n();
  const [stores, setStores] = useState([]);
  const [loading, setLoading] = useState(true);
  const [encryptionOk, setEncryptionOk] = useState(null);
  const [editStore, setEditStore] = useState(null);
  const [form, setForm] = useState({ email: "", password: "", phone: "" });
  const [showPw, setShowPw] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchStores = useCallback(() => {
    setLoading(true);
    api.get("/tier4/summary")
      .then((r) => setStores(r.data))
      .catch(() => toast.error("Failed to load stores"))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { fetchStores(); }, [fetchStores]);

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

  const openEdit = (store) => {
    setEditStore(store);
    setForm({ email: "", password: "", phone: "" });
    setShowPw(false);
  };

  const handleSave = async () => {
    if (!editStore) return;
    const payload = {};
    if (form.email.trim()) payload.email = form.email.trim();
    if (form.password.trim()) payload.password = form.password.trim();
    if (form.phone.trim()) payload.phone = form.phone.trim();
    if (Object.keys(payload).length === 0) {
      toast.error("Enter at least one credential");
      return;
    }
    setSaving(true);
    try {
      await api.put(`/stores/${editStore.store_id}/tier4-credentials`, payload);
      toast.success("Credentials saved (encrypted)");
      setEditStore(null);
      fetchStores();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  const handleClearSession = async (storeId, storeName) => {
    try {
      await api.post(`/stores/${storeId}/tier4-clear-session`);
      toast.success(`Session cleared for ${storeName}`);
      fetchStores();
    } catch {
      toast.error("Failed to clear session");
    }
  };

  const handleTestLogin = async (storeId, storeName) => {
    try {
      const r = await api.post(`/stores/${storeId}/tier4-test-login`);
      toast.info(r.data.message);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Test login failed");
    }
  };

  return (
    <div className="p-6 space-y-5" data-testid="settings-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-[#0A0A0A]" data-testid="settings-title">
            {isRTL ? "الإعدادات" : "Settings"}
          </h1>
          <p className="text-sm text-[#9CA3AF] mt-0.5">
            {isRTL ? "إدارة حسابات المتاجر والتشفير" : "Manage store accounts and encryption"}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={verifyEncryption}
          className="rounded-md text-xs gap-1.5"
          data-testid="verify-encryption-btn"
        >
          <KeyRound className="w-3.5 h-3.5" />
          {isRTL ? "تحقق من التشفير" : "Verify Encryption"}
          {encryptionOk === true && <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />}
          {encryptionOk === false && <XCircle className="w-3.5 h-3.5 text-red-500" />}
        </Button>
      </div>

      {/* Encryption Status Banner */}
      {encryptionOk !== null && (
        <div
          className={`flex items-center gap-2 px-4 py-2.5 rounded-md text-sm font-medium ${
            encryptionOk
              ? "bg-green-50 text-green-700 border border-green-200"
              : "bg-red-50 text-red-700 border border-red-200"
          }`}
          data-testid="encryption-status-banner"
        >
          {encryptionOk ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
          {encryptionOk
            ? (isRTL ? "التشفير نشط — Fernet AES-128" : "Encryption Active — Fernet AES-128")
            : (isRTL ? "خطأ في التشفير — تحقق من ENCRYPTION_KEY" : "Encryption Error — Check ENCRYPTION_KEY")}
        </div>
      )}

      {/* Store Accounts Section */}
      <div className="bg-white border border-[#E5E7EB] rounded-md overflow-hidden">
        <div className="px-5 py-4 border-b border-[#E5E7EB] bg-[#F9FAFB]">
          <h3 className="text-sm font-semibold text-[#0A0A0A] flex items-center gap-2">
            <Shield className="w-4 h-4 text-[#002DF5]" />
            {isRTL ? "حسابات المتاجر (المستوى 4)" : "Store Accounts (Tier 4)"}
          </h3>
          <p className="text-[11px] text-[#9CA3AF] mt-0.5">
            {isRTL
              ? "بيانات تسجيل الدخول كمشتري في متاجر المنافسين — مشفرة بالكامل"
              : "Buyer login credentials for competitor stores — fully encrypted"}
          </p>
        </div>

        {loading ? (
          <div className="px-5 py-12 text-center text-sm text-[#9CA3AF]">{t("loading")}</div>
        ) : (
          <div className="divide-y divide-[#E5E7EB]">
            {stores.map((s) => {
              const cfg = STATUS_CFG[s.session_status] || STATUS_CFG.not_configured;
              const StatusIcon = cfg.icon;
              const platCls = PLATFORM_COLORS[s.platform] || PLATFORM_COLORS.custom;
              return (
                <div key={s.store_id} className="px-5 py-4 hover:bg-[#FAFBFC] transition-colors" data-testid={`tier4-store-${s.store_id}`}>
                  <div className="flex items-center gap-4">
                    {/* Store info */}
                    <div className="flex items-center gap-3 w-[200px] shrink-0">
                      <div className="w-8 h-8 bg-[#002DF5] text-white text-xs font-bold rounded flex items-center justify-center">
                        {s.store_name?.[0]?.toUpperCase()}
                      </div>
                      <div>
                        <p className="text-sm font-medium text-[#0A0A0A]">{s.store_name}</p>
                        <Badge variant="outline" className={`text-[9px] capitalize mt-0.5 ${platCls}`}>{s.platform}</Badge>
                      </div>
                    </div>

                    {/* Credentials summary */}
                    <div className="flex-1 flex items-center gap-6 text-xs text-[#4B5563]">
                      <div className="w-[160px]">
                        <span className="text-[10px] uppercase tracking-wider text-[#9CA3AF] block">{isRTL ? "البريد" : "Email"}</span>
                        <span className={s.has_email ? "font-medium" : "text-[#9CA3AF]"}>{s.email_masked || "—"}</span>
                      </div>
                      <div className="w-[100px]">
                        <span className="text-[10px] uppercase tracking-wider text-[#9CA3AF] block">{isRTL ? "الهاتف" : "Phone"}</span>
                        <span className={s.has_phone ? "font-medium" : "text-[#9CA3AF]"}>
                          {s.has_phone ? `****${s.phone_last4}` : "—"}
                        </span>
                      </div>
                      <div className="w-[130px]">
                        <span className="text-[10px] uppercase tracking-wider text-[#9CA3AF] block">{isRTL ? "الجلسة" : "Session"}</span>
                        <Badge variant="outline" className={`text-[9px] gap-1 ${cfg.color}`}>
                          <StatusIcon className="w-3 h-3" />
                          {isRTL ? cfg.labelAr : cfg.label}
                        </Badge>
                      </div>
                      {s.session_expiry && (
                        <div className="w-[120px]">
                          <span className="text-[10px] uppercase tracking-wider text-[#9CA3AF] block">{isRTL ? "ينتهي" : "Expires"}</span>
                          <span className="text-[10px]">{new Date(s.session_expiry).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" })}</span>
                        </div>
                      )}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => openEdit(s)}
                        className="text-[10px] h-7 px-2.5 rounded-md gap-1"
                        data-testid={`tier4-edit-${s.store_id}`}
                      >
                        <KeyRound className="w-3 h-3" />
                        {s.has_email || s.has_phone ? (isRTL ? "تعديل" : "Edit") : (isRTL ? "إعداد" : "Setup")}
                      </Button>
                      {(s.has_email || s.has_phone) && (
                        <>
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleTestLogin(s.store_id, s.store_name)}
                            className="text-[10px] h-7 px-2.5 rounded-md gap-1"
                            data-testid={`tier4-test-${s.store_id}`}
                          >
                            <TestTube className="w-3 h-3" />
                            {isRTL ? "اختبار" : "Test Login"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleClearSession(s.store_id, s.store_name)}
                            className="text-[10px] h-7 w-7 p-0 text-red-500 hover:bg-red-50"
                            data-testid={`tier4-clear-${s.store_id}`}
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Edit Credentials Dialog */}
      <Dialog open={!!editStore} onOpenChange={(o) => { if (!o) setEditStore(null); }}>
        <DialogContent className="sm:max-w-md rounded-md" data-testid="tier4-credentials-dialog">
          <DialogHeader>
            <DialogTitle className="font-bold flex items-center gap-2">
              <KeyRound className="w-4 h-4 text-[#002DF5]" />
              {editStore?.store_name} — {isRTL ? "بيانات المستوى 4" : "Tier 4 Credentials"}
            </DialogTitle>
            <DialogDescription>
              {isRTL
                ? "أدخل بيانات حساب المشتري — ستُشفّر تلقائياً"
                : "Enter buyer account credentials — encrypted automatically"}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">
                {isRTL ? "البريد الإلكتروني" : "Email"}
              </label>
              <Input
                type="email"
                value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                placeholder={editStore?.email_masked || "buyer@example.com"}
                className="rounded-md"
                data-testid="tier4-email-input"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">
                {isRTL ? "كلمة المرور" : "Password"}
              </label>
              <div className="relative">
                <Input
                  type={showPw ? "text" : "password"}
                  value={form.password}
                  onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
                  placeholder="********"
                  className="rounded-md pe-9"
                  data-testid="tier4-password-input"
                />
                <button
                  type="button"
                  onClick={() => setShowPw(!showPw)}
                  className="absolute end-2.5 top-1/2 -translate-y-1/2 text-[#9CA3AF] hover:text-[#4B5563]"
                  data-testid="tier4-toggle-pw"
                >
                  {showPw ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                </button>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">
                {isRTL ? "رقم الهاتف (للـ OTP)" : "Phone Number (for OTP)"}
              </label>
              <Input
                type="tel"
                value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                placeholder={editStore?.has_phone ? `****${editStore.phone_last4}` : "+966 5XX XXX XXXX"}
                className="rounded-md"
                dir="ltr"
                data-testid="tier4-phone-input"
              />
              <p className="text-[10px] text-[#9CA3AF] mt-1">
                {isRTL ? "آخر 4 أرقام فقط ستظهر" : "Only last 4 digits will be displayed"}
              </p>
            </div>
          </div>
          <DialogFooter className="relative z-[60]">
            <Button variant="outline" size="sm" onClick={() => setEditStore(null)} className="rounded-md" type="button">
              {t("btn_cancel")}
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={saving}
              className="bg-[#002DF5] hover:bg-blue-700 text-white rounded-md gap-1.5"
              data-testid="tier4-save-btn"
              type="button"
            >
              <Shield className="w-3.5 h-3.5" />
              {saving ? (isRTL ? "جارٍ الحفظ..." : "Saving...") : (isRTL ? "حفظ مشفّر" : "Save Encrypted")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
