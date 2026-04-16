import { NavLink } from "react-router-dom";
import { useAuth } from "@/App";
import { useI18n } from "@/lib/i18n";
import { Package, BarChart3, Store, LogOut, Languages, Bell, Percent, Zap, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";

const navItems = [
  { to: "/", icon: Package, labelKey: "nav_products" },
  { to: "/insights", icon: BarChart3, labelKey: "nav_insights" },
  { to: "/scanner", icon: Zap, labelKey: "nav_scanner" },
  { to: "/discounts", icon: Percent, labelKey: "nav_discounts" },
  { to: "/alerts", icon: Bell, labelKey: "nav_alerts" },
  { to: "/stores", icon: Store, labelKey: "nav_stores" },
];

export default function Sidebar() {
  const { logout, user } = useAuth();
  const { t, toggleLang, lang } = useI18n();

  return (
    <aside
      data-testid="sidebar-nav"
      className="fixed inset-y-0 start-0 w-[240px] bg-white border-e border-[#E5E7EB] flex flex-col z-40"
    >
      <div className="px-5 py-5 border-b border-[#E5E7EB]">
        <h1 className="text-lg font-bold tracking-tight text-[#0A0A0A]">
          {t("app_name")}
        </h1>
        <p className="text-[11px] text-[#9CA3AF] mt-0.5">{t("subtitle")}</p>
      </div>

      <nav className="flex-1 py-3 px-3 space-y-0.5">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            data-testid={`nav-${item.labelKey}`}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-200 ${
                isActive
                  ? "bg-[#002DF5] text-white font-medium"
                  : "text-[#4B5563] hover:bg-[#F3F4F6] hover:text-[#0A0A0A]"
              }`
            }
          >
            <item.icon className="w-4 h-4 shrink-0" />
            <span>{t(item.labelKey)}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[#E5E7EB] space-y-1.5">
        <Button
          variant="ghost"
          size="sm"
          onClick={toggleLang}
          className="w-full justify-start gap-2 text-xs text-[#4B5563]"
          data-testid="lang-toggle-btn"
        >
          <Languages className="w-3.5 h-3.5" />
          {t("lang_switch")}
        </Button>
        <NavLink
          to="/settings"
          data-testid="nav-settings"
          className={({ isActive }) =>
            `flex items-center gap-2 w-full px-3 py-2 rounded-md text-xs transition-colors duration-200 ${
              isActive
                ? "bg-[#002DF5] text-white font-medium"
                : "text-[#4B5563] hover:bg-[#F3F4F6] hover:text-[#0A0A0A]"
            }`
          }
        >
          <Settings className="w-3.5 h-3.5" />
          {t("lang_switch") === "English" ? "الإعدادات" : "Settings"}
        </NavLink>
        {user && (
          <>
            <div className="px-3 py-1">
              <p className="text-[11px] text-[#9CA3AF] truncate">{user.email}</p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={logout}
              className="w-full justify-start gap-2 text-xs text-red-500 hover:text-red-600 hover:bg-red-50"
              data-testid="logout-btn"
            >
              <LogOut className="w-3.5 h-3.5" />
              {t("logout")}
            </Button>
          </>
        )}
      </div>
    </aside>
  );
}
