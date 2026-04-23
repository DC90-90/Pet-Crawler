import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/App";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { ArrowRight, BarChart3, Store, Activity, Layers } from "lucide-react";

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
    { icon: Layers, value: "200+", label: isRTL ? "منتج متتبع" : "Products Tracked" },
    { icon: Store, value: "9", label: isRTL ? "متاجر مراقبة" : "Stores Monitored" },
    { icon: BarChart3, value: "90d", label: isRTL ? "بيانات تاريخية" : "Historical Data" },
    { icon: Activity, value: "4-Tier", label: isRTL ? "زحف ذكي" : "Smart Crawler" },
  ];

  const headingClass = `text-5xl font-bold mb-2 ${isRTL ? "" : "uppercase tracking-[0.05em]"}`;

  return (
    <div className="min-h-screen flex" style={{ background: "#090E1C" }} data-testid="login-page">
      {/* Left — Brand Hero (flat dark, no gradients) */}
      <div
        className="hidden lg:flex flex-1 flex-col justify-center items-center p-12 relative"
        style={{ background: "#090E1C", borderInlineEnd: "1px solid #13625F" }}
      >
        <div className="relative z-10 max-w-md text-center">
          <h1 className={headingClass} style={{ color: "#FFFFFF" }} data-testid="login-brand-heading">
            {t("app_name")}
          </h1>
          <p
            className="text-xl font-medium tracking-wide mb-1"
            style={{ color: "#6AC1B5", fontFamily: isRTL ? undefined : "'Space Grotesk', sans-serif", letterSpacing: isRTL ? 0 : "0.05em", textTransform: isRTL ? "none" : "uppercase" }}
          >
            {t("app_name_ar")}
          </p>
          <p className="text-sm mt-4 leading-relaxed" style={{ color: "#A1E4DB" }}>
            {t("tagline")}
          </p>
          <div className="grid grid-cols-2 gap-4 mt-10">
            {stats.map((s) => (
              <div
                key={s.label}
                className="p-4 text-center"
                style={{ background: "#0A2728", border: "1px solid #13625F", borderRadius: 8 }}
              >
                <s.icon className="w-5 h-5 mx-auto mb-2" style={{ color: "#1E988E" }} />
                <p className="text-2xl font-bold metric-number" style={{ color: "#FFFFFF" }}>{s.value}</p>
                <p className="text-[10px] uppercase tracking-[0.12em] mt-1" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>{s.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right — Login Form */}
      <div className="flex-1 lg:max-w-[480px] flex flex-col justify-center px-8 lg:px-16" style={{ background: "#090E1C" }}>
        <div className="flex justify-end mb-8">
          <button
            onClick={toggleLang}
            className="text-xs px-3 py-1.5 rounded transition-colors"
            style={{ color: "#A1E4DB", border: "1px solid #13625F", background: "transparent", fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase", letterSpacing: "0.08em" }}
            data-testid="login-lang-toggle"
          >
            {t("lang_switch")}
          </button>
        </div>

        <div className="lg:hidden text-center mb-8">
          <h1 className={headingClass} style={{ color: "#FFFFFF" }}>{t("app_name")}</h1>
          <p className="text-sm mt-1" style={{ color: "#6AC1B5" }}>{t("tagline_short")}</p>
        </div>

        <div className="p-8" style={{ background: "#0A2728", border: "1px solid #13625F", borderRadius: 8 }}>
          <h2
            className="text-xl mb-6"
            style={{
              color: "#FFFFFF",
              fontFamily: isRTL ? undefined : "'Space Grotesk', sans-serif",
              fontWeight: 700,
              letterSpacing: isRTL ? 0 : "0.05em",
              textTransform: isRTL ? "none" : "uppercase",
            }}
          >
            {isLogin ? (isRTL ? "تسجيل الدخول" : "Sign In") : (isRTL ? "إنشاء حساب" : "Create Account")}
          </h2>

          {error && (
            <div
              className="text-xs p-3 mb-4"
              style={{ background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", color: "#EF4444", borderRadius: 4 }}
              data-testid="auth-error"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label className="text-xs mb-1.5 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase", letterSpacing: "0.08em" }}>{t("name")}</label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={isRTL ? "اسمك" : "Your name"}
                  className="hrm-input h-11 rounded"
                  style={{ background: "#0A2728", border: "1px solid #13625F", color: "#FFFFFF", borderRadius: 4 }}
                  data-testid="auth-name-input"
                />
              </div>
            )}
            <div>
              <label className="text-xs mb-1.5 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase", letterSpacing: "0.08em" }}>{t("email")}</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                className="hrm-input h-11 rounded"
                style={{ background: "#0A2728", border: "1px solid #13625F", color: "#FFFFFF", borderRadius: 4 }}
                required
                data-testid="auth-email-input"
              />
            </div>
            <div>
              <label className="text-xs mb-1.5 block" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace", textTransform: "uppercase", letterSpacing: "0.08em" }}>{t("password")}</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="********"
                className="hrm-input h-11 rounded"
                style={{ background: "#0A2728", border: "1px solid #13625F", color: "#FFFFFF", borderRadius: 4 }}
                required
                data-testid="auth-password-input"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="hrm-btn-primary w-full h-11 flex items-center justify-center gap-2"
              data-testid="auth-submit-btn"
            >
              {loading ? <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" /> : (
                <>{isLogin ? t("btn_login") : t("btn_register")} <ArrowRight className="w-4 h-4" /></>
              )}
            </button>
          </form>

          <p className="text-xs text-center mt-5" style={{ color: "#A1E4DB" }}>
            {isLogin ? t("no_account") : t("has_account")}{" "}
            <button
              type="button"
              onClick={() => { setIsLogin(!isLogin); setError(""); }}
              style={{ color: "#6AC1B5", fontWeight: 500 }}
              className="hover:underline"
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
