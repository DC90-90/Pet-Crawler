import { NavLink } from "react-router-dom";
import { useAuth, canAccessPage } from "@/App";
import { useI18n } from "@/lib/i18n";
import { Package, BarChart3, Store, LogOut, Languages, Bell, Percent, Zap, Settings, ChevronLeft, ChevronRight, Upload, Sun, Moon, ShieldCheck } from "lucide-react";
import { useState, useEffect } from "react";

// Feb 2026 — Insights + Price Intel merged into a single "Price & Market Intel"
// entry. The item shows when the user has EITHER `insights` OR `price_intel`
// in their allowed_pages (super_admin always sees it).
const navItems = [
  { to: "/", pageKey: "my_products", icon: Package, labelKey: "nav_products", label: "Dashboard" },
  { to: "/insights", pageKeys: ["insights", "price_intel"], icon: BarChart3, labelKey: "nav_intel", label: "Price & Market Intel" },
  { to: "/scanner", pageKey: "scanner", icon: Zap, labelKey: "nav_scanner", label: "Scanner" },
  { to: "/discounts", pageKey: "discounts", icon: Percent, labelKey: "nav_discounts", label: "Discounts" },
  { to: "/alerts", pageKey: "alerts", icon: Bell, labelKey: "nav_alerts", label: "Alerts" },
  { to: "/stores", pageKey: "stores", icon: Store, labelKey: "nav_stores", label: "Stores" },
  { to: "/import", pageKey: "import", icon: Upload, labelKey: "nav_import", label: "Import" },
];

export default function Sidebar() {
  const { logout, user } = useAuth();
  const { t, toggleLang, lang, isRTL } = useI18n();
  const [collapsed, setCollapsed] = useState(false);
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "dark";
    return localStorage.getItem("daleel_theme") || "dark";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("daleel_theme", theme);
  }, [theme]);

  const toggleTheme = () => setTheme((t) => (t === "dark" ? "light" : "dark"));

  const w = collapsed ? "w-[68px]" : "w-[240px]";

  return (
    <aside
      data-testid="sidebar-nav"
      className={`fixed inset-y-0 start-0 ${w} flex flex-col z-40 transition-all duration-300`}
      style={{ background: "#090E1C", borderInlineEnd: "1px solid #13625F" }}
    >
      {/* Brand */}
      <div className={`px-5 py-5 flex items-center ${collapsed ? "justify-center" : "justify-between"}`} style={{ borderBottom: "1px solid #13625F" }}>
        {!collapsed && (
          <div>
            <h1
              className="text-lg font-bold tracking-[0.05em]"
              style={{ color: "#FFFFFF", fontFamily: isRTL ? undefined : "'Space Grotesk', sans-serif", textTransform: isRTL ? "none" : "uppercase", letterSpacing: isRTL ? 0 : "0.05em" }}
            >
              {t("app_name")}
            </h1>
            <p className="text-[10px] mt-0.5 tracking-[0.12em] uppercase" style={{ color: "#A1E4DB", fontFamily: "'JetBrains Mono', monospace" }}>{t("tagline_short")}</p>
          </div>
        )}
        {collapsed && <span className="text-lg font-bold" style={{ color: "#1E988E", fontFamily: "'Space Grotesk', sans-serif" }}>D</span>}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="transition-colors p-1 rounded"
          style={{ color: "#A1E4DB" }}
          data-testid="sidebar-collapse-btn"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2 space-y-0.5">
        {navItems
          .filter((item) => {
            // Support either a single `pageKey` or a `pageKeys` array (any match).
            if (item.pageKeys) return item.pageKeys.some((k) => canAccessPage(user, k));
            return canAccessPage(user, item.pageKey);
          })
          .map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              data-testid={`nav-${item.labelKey}`}
              title={collapsed ? t(item.labelKey) : undefined}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded text-sm transition-all duration-200 group relative ${
                  isActive
                    ? "text-[#6AC1B5] bg-[#104745] border-s-2 border-[#1E988E]"
                    : "text-[#A1E4DB] hover:text-white hover:bg-[#104745]/60 border-s-2 border-transparent"
                } ${collapsed ? "justify-center px-0" : ""}`
              }
            >
              <item.icon className="w-4.5 h-4.5 shrink-0" />
              {!collapsed && <span>{t(item.labelKey)}</span>}
            </NavLink>
          ))}
        {user?.role === "super_admin" && (
          <NavLink
            to="/users"
            data-testid="nav-users"
            title={collapsed ? "Users" : undefined}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded text-sm transition-all duration-200 group relative ${
                isActive
                  ? "text-[#6AC1B5] bg-[#104745] border-s-2 border-[#1E988E]"
                  : "text-[#A1E4DB] hover:text-white hover:bg-[#104745]/60 border-s-2 border-transparent"
              } ${collapsed ? "justify-center px-0" : ""}`
            }
          >
            <ShieldCheck className="w-4.5 h-4.5 shrink-0" />
            {!collapsed && <span>Users</span>}
          </NavLink>
        )}
      </nav>

      {/* Footer */}
      <div className="px-2 py-3 space-y-1" style={{ borderTop: "1px solid #13625F" }}>
        <button
          onClick={toggleLang}
          className={`flex items-center gap-2 w-full px-3 py-2 rounded text-xs transition-all hover:bg-[#104745]/60 ${collapsed ? "justify-center" : ""}`}
          style={{ color: "#A1E4DB" }}
          data-testid="lang-toggle-btn"
        >
          <Languages className="w-3.5 h-3.5 shrink-0" />
          {!collapsed && t("lang_switch")}
        </button>
        <button
          onClick={toggleTheme}
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className={`flex items-center gap-2 w-full px-3 py-2 rounded text-xs transition-all hover:bg-[#104745]/60 ${collapsed ? "justify-center" : ""}`}
          style={{ color: "#A1E4DB" }}
          data-testid="theme-toggle-btn"
        >
          {theme === "dark" ? <Sun className="w-3.5 h-3.5 shrink-0" /> : <Moon className="w-3.5 h-3.5 shrink-0" />}
          {!collapsed && (
            <span data-testid="theme-toggle-label">
              {theme === "dark"
                ? (isRTL ? "الوضع النهاري" : "Light Mode")
                : (isRTL ? "الوضع الليلي" : "Dark Mode")}
            </span>
          )}
        </button>
        {canAccessPage(user, "settings") && (
          <NavLink
            to="/settings"
            data-testid="nav-settings"
            className={({ isActive }) =>
              `flex items-center gap-2 w-full px-3 py-2 rounded text-xs transition-all ${
                isActive ? "text-[#6AC1B5] bg-[#104745]" : "text-[#A1E4DB] hover:text-white hover:bg-[#104745]/60"
              } ${collapsed ? "justify-center" : ""}`
            }
          >
            <Settings className="w-3.5 h-3.5 shrink-0" />
            {!collapsed && (isRTL ? "الإعدادات" : "Settings")}
          </NavLink>
        )}
        {user && !collapsed && (
          <div className="px-3 py-1">
            <p className="text-[10px] truncate" style={{ color: "#A1E4DB", opacity: 0.6 }}>{user.email}</p>
          </div>
        )}
        {user && (
          <button
            onClick={logout}
            className={`flex items-center gap-2 w-full px-3 py-2 rounded text-xs text-[#EF4444]/70 hover:text-[#EF4444] hover:bg-[#EF4444]/5 transition-all ${collapsed ? "justify-center" : ""}`}
            data-testid="logout-btn"
          >
            <LogOut className="w-3.5 h-3.5 shrink-0" />
            {!collapsed && t("logout")}
          </button>
        )}
      </div>
    </aside>
  );
}
