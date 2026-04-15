import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/App";
import { useI18n } from "@/lib/i18n";
import api from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

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

  return (
    <div className="min-h-screen bg-[#F3F4F6] flex items-center justify-center p-6" data-testid="login-page">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-[#0A0A0A]">
            {t("app_name")}
          </h1>
          <p className="text-sm text-[#9CA3AF] mt-1">{t("subtitle")}</p>
        </div>

        <div className="bg-white border border-[#E5E7EB] rounded-md p-6">
          <h2 className="text-lg font-semibold text-[#0A0A0A] mb-4">
            {isLogin ? t("btn_login") : t("btn_register")}
          </h2>

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-xs p-2.5 rounded-md mb-4" data-testid="auth-error">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-3">
            {!isLogin && (
              <div>
                <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("name")}</label>
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  className="rounded-md"
                  data-testid="auth-name-input"
                />
              </div>
            )}
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("email")}</label>
              <Input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="email@example.com"
                className="rounded-md"
                required
                data-testid="auth-email-input"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-[#0A0A0A] mb-1 block">{t("password")}</label>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="********"
                className="rounded-md"
                required
                data-testid="auth-password-input"
              />
            </div>
            <Button
              type="submit"
              disabled={loading}
              className="w-full bg-[#002DF5] hover:bg-blue-700 text-white rounded-md"
              data-testid="auth-submit-btn"
            >
              {loading ? "..." : isLogin ? t("btn_login") : t("btn_register")}
            </Button>
          </form>

          <p className="text-xs text-center text-[#9CA3AF] mt-4">
            {isLogin ? t("no_account") : t("has_account")}{" "}
            <button
              type="button"
              onClick={() => { setIsLogin(!isLogin); setError(""); }}
              className="text-[#002DF5] font-medium hover:underline"
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
