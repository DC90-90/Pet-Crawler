import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/App";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { ArrowRight, BarChart3, Package, Store, Zap } from "lucide-react";

export default function LoginPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const { t, toggleLang, isRTL } = useI18n();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const endpoint = isLogin ? "/auth/login" : "/auth/register";
      const payload = isLogin ? { email, password } : { email, password, name };
      const { data } = await api.post(endpoint, payload);
      login(data.token, data.user);
      navigate("/", { replace: true });
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === "string") setError(detail);
      else if (Array.isArray(detail)) setError(detail.map((d) => d.msg || JSON.stringify(d)).join(" "));
      else setError("Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const stats = [
    { icon: Package, value: "200+", label: isRTL ? "منتج متتبع" : "Products Tracked" },
    { icon: Store, value: "9", label: isRTL ? "متاجر مراقبة" : "Stores Monitored" },
    { icon: BarChart3, value: "90d", label: isRTL ? "بيانات تاريخية" : "Historical Data" },
    { icon: Zap, value: "4-Tier", label: isRTL ? "زحف ذكي" : "Smart Crawler" },
  ];

  return (
    <div className="min-h-screen flex" style={{ background: "radial-gradient(circle at top center, #0A0F1E 0%, #060B14 100%)" }} data-testid="login-page">
      {/* Left — Brand Hero */}
      <div className="hidden lg:flex flex-1 flex-col justify-center items-center p-12 relative overflow-hidden">
        <div className="absolute inset-0 opacity-20" style={{ backgroundImage: "url(https://static.prod-images.emergentagent.com/jobs/e703fccc-0c9e-4960-bc7a-841f7b4e9557/images/10760f1c33ca1363281d0fbf1bb272afb8e800265786e402e77d5ebbfd63a90f.png)", backgroundSize: "cover", backgroundPosition: "center" }} />
        <div className="relative z-10 max-w-md text-center">
          <h1 className="text-5xl font-bold text-white tracking-tight mb-2">
            {t("app_name")}
          </h1>
          <p className="text-xl text-[#00D4B4] font-medium tracking-wide mb-1">{t("app_name_ar")}</p>
          <p className="text-[#9CA3AF] text-sm mt-4 leading-relaxed">
            {isRTL
              ? "منصة استخبارات سوق الحيوانات الأليفة السعودي. تتبع الأسعار، المخزون، والمنافسين."
              : "Saudi Pet Market Intelligence Platform. Track prices, inventory, and competitors in real-time."}
          </p>
          <div className="grid grid-cols-2 gap-4 mt-10">
            {stats.map((s) => (
              <div key={s.label} className="glass-card p-4 text-center">
                <s.icon className="w-5 h-5 text-[#00D4B4] mx-auto mb-2" />
                <p className="text-2xl font-bold text-white metric-number">{s.value}</p>
                <p className="text-[10px] text-[#9CA3AF] uppercase tracking-wider mt-1">{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right — Login Form */}
      <div className="flex-1 lg:max-w-[480px] flex flex-col justify-center px-8 lg:px-16">
        <div className="flex justify-end mb-8">
          <button onClick={toggleLang} className="text-xs text-[#9CA3AF] hover:text-[#00D4B4] transition-colors px-3 py-1.5 rounded-full border border-white/10 hover:border-[#00D4B4]/30" data-testid="login-lang-toggle">
            {t("lang_switch")}
          </button>
        </div>

        <div className="lg:hidden text-center mb-8">
          <h1 className="text-3xl font-bold text-white">{t("app_name")}</h1>
          <p className="text-[#00D4B4] text-sm mt-1">{isRTL ? "سوق الحيوانات، مفكّك" : "Saudi Pet Market, Decoded"}</p>
        </div>

        <div className="glass-card p-8">
          <h2 className="text-xl font-semibold text-white mb-6">
            {isLogin ? (isRTL ? "تسجيل الدخول" : "Sign In") : (isRTL ? "إنشاء حساب" : "Create Account")}
          </h2>

          {error && (
            <div className="bg-[#EF4444]/10 border border-[#EF4444]/20 text-[#EF4444] text-xs p-3 rounded-xl mb-4" data-testid="auth-error">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label className="text-xs font-medium text-[#9CA3AF] mb-1.5 block">{t("name")}</label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={isRTL ? "اسمك" : "Your name"}
                  className="bg-white/5 border-white/10 text-white placeholder:text-[#9CA3AF]/50 rounded-xl h-11 focus:border-[#00D4B4]/50 focus:ring-[#00D4B4]/20"
                  data-testid="auth-name-input"
                />
              </div>
            )}
            <div>
              <label className="text-xs font-medium text-[#9CA3AF] mb-1.5 block">{t("email")}</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                className="bg-white/5 border-white/10 text-white placeholder:text-[#9CA3AF]/50 rounded-xl h-11 focus:border-[#00D4B4]/50 focus:ring-[#00D4B4]/20"
                required
                data-testid="auth-email-input"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-[#9CA3AF] mb-1.5 block">{t("password")}</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="********"
                className="bg-white/5 border-white/10 text-white placeholder:text-[#9CA3AF]/50 rounded-xl h-11 focus:border-[#00D4B4]/50 focus:ring-[#00D4B4]/20"
                required
                data-testid="auth-password-input"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-full bg-[#00D4B4] text-[#0A0F1E] font-semibold h-11 hover:bg-[#00E5C3] hover:shadow-[0_0_20px_rgba(0,212,180,0.4)] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
              data-testid="auth-submit-btn"
            >
              {loading ? <div className="w-4 h-4 border-2 border-[#0A0F1E] border-t-transparent rounded-full animate-spin" /> : (
                <>{isLogin ? t("btn_login") : t("btn_register")} <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </form>

          <p className="text-xs text-center text-[#9CA3AF] mt-5">
            {isLogin ? t("no_account") : t("has_account")}{" "}
            <button
              type="button"
              onClick={() => { setIsLogin(!isLogin); setError(""); }}
              className="text-[#00D4B4] font-medium hover:underline"
              data-testid="auth-toggle-btn"
            >
              {isLogin ? t("btn_register") : t("btn_login")}
            </button>
          </p>
        </div>
      </div>
    </div>
  );
}
