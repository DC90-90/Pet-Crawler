import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/App";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { ArrowRight } from "lucide-react";

export default function LoginPage() {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const { t } = useI18n();
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

  const labelStyle = {
    color: "#A1E4DB",
    fontFamily: "'JetBrains Mono', monospace",
    textTransform: "uppercase",
    letterSpacing: "0.08em",
  };
  const inputStyle = {
    background: "#090E1C",
    border: "1px solid #13625F",
    color: "#FFFFFF",
    borderRadius: 4,
  };

  return (
    <div
      className="min-h-screen flex flex-col items-center justify-center px-6 py-10"
      style={{ background: "#090E1C" }}
      data-testid="login-page"
    >
      <div style={{ width: "100%", maxWidth: 420, margin: "0 auto" }}>
        {/* Wordmark */}
        <div className="flex flex-col items-center mb-10">
          <h1
            style={{
              fontFamily: "'Space Grotesk', sans-serif",
              fontSize: 56,
              fontWeight: 700,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
              color: "#FFFFFF",
              margin: 0,
              lineHeight: 1,
            }}
            data-testid="login-wordmark"
          >
            Daleel
          </h1>
        </div>

        {/* Login Card */}
        <div
          style={{
            background: "#0A2728",
            border: "1px solid #13625F",
            borderRadius: 8,
            padding: 40,
          }}
          data-testid="login-card"
        >
          <h2
            className="text-xl mb-6"
            style={{
              color: "#FFFFFF",
              fontFamily: "'Space Grotesk', sans-serif",
              fontWeight: 700,
              letterSpacing: "0.05em",
              textTransform: "uppercase",
            }}
          >
            {isLogin ? "Sign In" : "Create Account"}
          </h2>

          {error && (
            <div
              className="text-xs p-3 mb-4"
              style={{
                background: "rgba(239,68,68,0.1)",
                border: "1px solid rgba(239,68,68,0.3)",
                color: "#EF4444",
                borderRadius: 4,
              }}
              data-testid="auth-error"
            >
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {!isLogin && (
              <div>
                <label className="text-xs mb-1.5 block" style={labelStyle}>
                  {t("name")}
                </label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  className="hrm-input h-11"
                  style={inputStyle}
                  data-testid="auth-name-input"
                />
              </div>
            )}
            <div>
              <label className="text-xs mb-1.5 block" style={labelStyle}>
                {t("email")}
              </label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                className="hrm-input h-11"
                style={inputStyle}
                required
                data-testid="auth-email-input"
              />
            </div>
            <div>
              <label className="text-xs mb-1.5 block" style={labelStyle}>
                {t("password")}
              </label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="********"
                className="hrm-input h-11"
                style={inputStyle}
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
              {loading ? (
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <>
                  {isLogin ? t("btn_login") : t("btn_register")} <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </form>

          {process.env.REACT_APP_ALLOW_PUBLIC_REGISTRATION === "true" && <p className="text-xs text-center mt-5" style={{ color: "#A1E4DB" }}>
            {isLogin ? t("no_account") : t("has_account")}{" "}
            <button
              type="button"
              onClick={() => {
                setIsLogin(!isLogin);
                setError("");
              }}
              style={{ color: "#6AC1B5", fontWeight: 500 }}
              className="hover:underline"
              data-testid="auth-toggle-btn"
            >
              {isLogin ? t("btn_register") : t("btn_login")}
            </button>
          </p>}
        </div>
      </div>
    </div>
  );
}
