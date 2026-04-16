import { useEffect, useState, useCallback, useRef } from "react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import { ShieldAlert, RefreshCw } from "lucide-react";

export default function OtpBanner() {
  const { isRTL } = useI18n();
  const [pending, setPending] = useState([]);
  const [modalOtp, setModalOtp] = useState(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [canResend, setCanResend] = useState(false);
  const inputRef = useRef(null);

  const fetchPending = useCallback(() => {
    api.get("/otp/pending")
      .then((r) => setPending(r.data || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchPending();
    const iv = setInterval(fetchPending, 5000);
    return () => clearInterval(iv);
  }, [fetchPending]);

  useEffect(() => {
    if (!modalOtp) return;
    const expires = new Date(modalOtp.expires_at);
    const tick = () => {
      const remaining = Math.max(0, Math.floor((expires - Date.now()) / 1000));
      setCountdown(remaining);
      if (remaining <= 0) {
        setPending((p) => p.filter((x) => x.id !== modalOtp.id));
        setModalOtp(null);
      }
    };
    tick();
    const iv = setInterval(tick, 1000);
    const resendTimer = setTimeout(() => setCanResend(true), 60000);
    return () => { clearInterval(iv); clearTimeout(resendTimer); };
  }, [modalOtp]);

  useEffect(() => {
    if (modalOtp && inputRef.current) inputRef.current.focus();
  }, [modalOtp]);

  const handleSubmit = async () => {
    if (!code || code.length < 4 || !modalOtp) return;
    setSubmitting(true);
    try {
      await api.post("/otp/submit", { store_id: modalOtp.store_id, otp_code: code });
      setCode("");
      setModalOtp(null);
      setPending((p) => p.filter((x) => x.id !== modalOtp.id));
    } catch (e) {
      const msg = e.response?.data?.detail || "Failed";
      alert(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleResend = async (storeId) => {
    try {
      await api.post(`/otp/retry/${storeId}`);
      setCanResend(false);
      fetchPending();
    } catch {}
  };

  const formatTime = (secs) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  if (pending.length === 0) return null;

  return (
    <>
      {/* Persistent orange banner */}
      {pending.map((otp) => (
        <div
          key={otp.id}
          onClick={() => { setModalOtp(otp); setCode(""); setCanResend(false); }}
          className="bg-orange-50 border border-orange-200 text-orange-800 px-4 py-2.5 flex items-center gap-3 cursor-pointer hover:bg-orange-100 transition-colors"
          data-testid={`otp-banner-${otp.store_id}`}
        >
          <ShieldAlert className="w-4 h-4 text-orange-600 shrink-0" />
          <span className="text-sm font-medium flex-1">
            {isRTL
              ? `OTP مطلوب لـ ${otp.store_name} — أدخل الرمز`
              : `OTP Required for ${otp.store_name} — Enter Code`}
          </span>
          <Badge variant="outline" className="text-[10px] bg-orange-100 text-orange-700 border-orange-300">
            ****{otp.phone_last4}
          </Badge>
        </div>
      ))}

      {/* OTP Input Modal */}
      <Dialog open={!!modalOtp} onOpenChange={(o) => { if (!o) setModalOtp(null); }}>
        <DialogContent className="sm:max-w-md rounded-md" data-testid="otp-modal">
          <DialogHeader>
            <DialogTitle className="font-bold flex items-center gap-2">
              <ShieldAlert className="w-5 h-5 text-orange-500" />
              {modalOtp?.store_name} — OTP
            </DialogTitle>
            <DialogDescription>
              {isRTL
                ? `رمز OTP أُرسل إلى ****${modalOtp?.phone_last4}`
                : `OTP sent to ****${modalOtp?.phone_last4}`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-3">
            <div className="flex flex-col items-center gap-3">
              <Input
                ref={inputRef}
                type="text"
                inputMode="numeric"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="000000"
                className="text-center text-2xl tracking-[0.5em] font-mono h-14 w-48 rounded-md"
                dir="ltr"
                data-testid="otp-code-input"
              />
              <div className={`text-sm font-mono ${countdown <= 60 ? "text-red-500" : "text-[#4B5563]"}`}>
                {countdown > 0
                  ? formatTime(countdown)
                  : (isRTL ? "انتهت صلاحية الرمز — اضغط لإعادة المحاولة" : "OTP Expired — click to retry")}
              </div>
            </div>
          </div>
          <DialogFooter className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="sm"
              disabled={!canResend || countdown <= 0}
              onClick={() => modalOtp && handleResend(modalOtp.store_id)}
              className="text-xs gap-1"
              data-testid="otp-resend-btn"
            >
              <RefreshCw className="w-3 h-3" />
              {isRTL ? "إعادة الإرسال" : "Resend OTP"}
            </Button>
            <Button
              size="sm"
              onClick={handleSubmit}
              disabled={submitting || code.length < 4 || countdown <= 0}
              className="bg-[#002DF5] hover:bg-blue-700 text-white rounded-md"
              data-testid="otp-submit-btn"
            >
              {submitting ? "..." : (isRTL ? "إرسال" : "Submit OTP")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
