import { NavLink } from "react-router-dom";
import { useAuth } from "@/App";
import { useI18n } from "@/lib/i18n";
import { Package, BarChart3, Store, LogOut, Languages, Bell, Percent, Zap, Settings, ChevronLeft, ChevronRight, Upload, Target } from "lucide-react";
import { useState } from "react";

const navItems = [
  { to: "/", icon: Package, labelKey: "nav_products", label: "Dashboard" },
  { to: "/price-intel", icon: Target, labelKey: "nav_priceintel", label: "Price Intel" },
  { to: "/insights", icon: BarChart3, labelKey: "nav_insights", label: "Insights" },
  { to: "/scanner", icon: Zap, labelKey: "nav_scanner", label: "Scanner" },
  { to: "/discounts", icon: Percent, labelKey: "nav_discounts", label: "Discounts" },
  { to: "/alerts", icon: Bell, labelKey: "nav_alerts", label: "Alerts" },
  { to: "/stores", icon: Store, labelKey: "nav_stores", label: "Stores" },
  { to: "/import", icon: Upload, labelKey: "nav_import", label: "Import" },
];

export default function Sidebar() {
  const { logout, user } = useAuth();
  const { t, toggleLang, lang, isRTL } = useI18n();
  const [collapsed, setCollapsed] = useState(false);

  const w = collapsed ? "w-[68px]" : "w-[240px]";

  return (
    <aside
      data-testid="sidebar-nav"
      className={`fixed inset-y-0 start-0 ${w} bg-[#0D1321] border-e border-white/5 flex flex-col z-40 transition-all duration-300`}
    >
      {/* Brand */}
      <div className={`px-5 py-5 border-b border-white/5 flex items-center ${collapsed ? "justify-center" : "justify-between"}`}>
        {!collapsed && (
          <div>
            <h1 className="text-lg font-bold tracking-tight text-white">
              {t("app_name")}
            </h1>
            <p className="text-[10px] text-[#00D4B4] mt-0.5 tracking-wider uppercase">{isRTL ? "سوق الحيوانات، مفكّك" : "Saudi Pet Market, Decoded"}</p>
          </div>
        )}
        {collapsed && <span className="text-lg font-bold text-[#00D4B4]">D</span>}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="text-[#9CA3AF] hover:text-white transition-colors p-1 rounded"
          data-testid="sidebar-collapse-btn"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 py-3 px-2 space-y-0.5">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            data-testid={`nav-${item.labelKey}`}
            title={collapsed ? t(item.labelKey) : undefined}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all duration-200 group relative ${
                isActive
                  ? "text-[#00D4B4] bg-[#00D4B4]/5 border-s-2 border-[#00D4B4] shadow-[-4px_0_12px_rgba(0,212,180,0.2)]"
                  : "text-[#9CA3AF] hover:text-white hover:bg-white/5 border-s-2 border-transparent"
              } ${collapsed ? "justify-center px-0" : ""}`
            }
          >
            <item.icon className="w-4.5 h-4.5 shrink-0" />
            {!collapsed && <span>{t(item.labelKey)}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-2 py-3 border-t border-white/5 space-y-1">
        <button
          onClick={toggleLang}
          className={`flex items-center gap-2 w-full px-3 py-2 rounded-xl text-xs text-[#9CA3AF] hover:text-white hover:bg-white/5 transition-all ${collapsed ? "justify-center" : ""}`}
          data-testid="lang-toggle-btn"
        >
          <Languages className="w-3.5 h-3.5 shrink-0" />
          {!collapsed && t("lang_switch")}
        </button>
        <NavLink
          to="/settings"
          data-testid="nav-settings"
          className={({ isActive }) =>
            `flex items-center gap-2 w-full px-3 py-2 rounded-xl text-xs transition-all ${
              isActive ? "text-[#00D4B4] bg-[#00D4B4]/5" : "text-[#9CA3AF] hover:text-white hover:bg-white/5"
            } ${collapsed ? "justify-center" : ""}`
          }
        >
          <Settings className="w-3.5 h-3.5 shrink-0" />
          {!collapsed && (isRTL ? "الإعدادات" : "Settings")}
        </NavLink>
        {user && !collapsed && (
          <div className="px-3 py-1">
            <p className="text-[10px] text-[#9CA3AF]/60 truncate">{user.email}</p>
          </div>
        )}
        {user && (
          <button
            onClick={logout}
            className={`flex items-center gap-2 w-full px-3 py-2 rounded-xl text-xs text-[#EF4444]/70 hover:text-[#EF4444] hover:bg-[#EF4444]/5 transition-all ${collapsed ? "justify-center" : ""}`}
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
