import { NavLink, useLocation } from "react-router-dom";
import { useAuth, canAccessPage } from "@/App";
import { useI18n } from "@/lib/i18n";
import { Package, Store, LogOut, Languages, Bell, Tag, Settings, ChevronLeft, ChevronRight, Upload, Sun, Moon, ShieldCheck, PieChart, X, LayoutDashboard, FileText, Users } from "lucide-react";
import { useState, useEffect } from "react";
import { SECTIONS } from "@/components/SectionTabs";

// 25 Oct 2026 — the client found 12 equal menu items confusing. Five everyday
// places, then a smaller "Manage" group. No page is removed: Market opens
// market share, key brands and opportunities as tabs (SectionTabs).
const MAIN = [
  { to: "/", pageKeys: ["overview"], icon: LayoutDashboard, en: "Overview", ar: "نظرة عامة", end: true },
  { to: "/products", pageKeys: ["my_products"], icon: Package, en: "My products", ar: "منتجاتي" },
  { to: "/pricing", pageKeys: ["pricing"], icon: Tag, en: "Pricing", ar: "التسعير" },
  { section: "market", pageKeys: ["market_share", "key_brands", "opportunities"], icon: PieChart, en: "Market", ar: "السوق" },
  { to: "/stores", pageKeys: ["competitors"], icon: Store, en: "Competitors", ar: "المنافسون" },
];
const MANAGE = [
  { to: "/reports", pageKeys: ["reports"], icon: FileText, en: "Reports", ar: "التقارير" },
  { to: "/alerts", pageKeys: ["alerts"], icon: Bell, en: "Alerts", ar: "التنبيهات" },
  { to: "/data-quality", pageKeys: ["data_quality"], icon: ShieldCheck, en: "Data quality", ar: "جودة البيانات" },
  { to: "/import", pageKeys: ["import"], icon: Upload, en: "Import", ar: "استيراد" },
  { to: "/settings", pageKeys: ["settings"], icon: Settings, en: "Settings", ar: "الإعدادات" },
];

function linkClass(active, collapsed, small) {
  return `flex items-center gap-3 rounded-lg transition-colors ${small ? "px-3 py-2 text-[13px]" : "px-3 py-2.5 text-[15px] font-medium"} ${
    active ? "bg-[#104745] text-white" : "text-[#A1E4DB] hover:text-white hover:bg-[#104745]/50"} ${collapsed ? "justify-center px-0" : ""}`;
}

export default function Sidebar({ mobileOpen = false, onClose, onCollapse }) {
  const { logout, user } = useAuth();
  const { t, toggleLang, isRTL } = useI18n();
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => { onCollapse?.(collapsed); }, [collapsed, onCollapse]);
  const [theme, setTheme] = useState(() => {
    if (typeof window === "undefined") return "dark";
    return localStorage.getItem("daleel_theme") || "dark";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("daleel_theme", theme);
  }, [theme]);
  const toggleTheme = () => setTheme((v) => (v === "dark" ? "light" : "dark"));

  const may = (item) => item.pageKeys.some((k) => canAccessPage(user, k));
  // A section opens on the first of its pages the user may see.
  const target = (item) => item.to || (SECTIONS[item.section].find((s) => canAccessPage(user, s.pageKey)) || {}).to;
  const inSection = (item) => item.section && SECTIONS[item.section].some((s) => pathname.startsWith(s.to));
  const label = (item) => (isRTL ? item.ar : item.en);
  const w = collapsed ? "w-[68px]" : "w-[232px]";

  const item = (it, small) => (
    <NavLink key={it.en} to={target(it)} end={it.end} onClick={onClose} title={collapsed ? label(it) : undefined}
      data-testid={`nav-${it.en.toLowerCase().replace(/\s+/g, "-")}`}
      className={({ isActive }) => linkClass(isActive || inSection(it), collapsed, small)}>
      <it.icon className={small ? "w-4 h-4 shrink-0" : "w-[18px] h-[18px] shrink-0"} />
      {!collapsed && <span>{label(it)}</span>}
    </NavLink>
  );
  const manage = MANAGE.filter(may);

  return (
    <aside data-testid="sidebar-nav"
      className={`fixed inset-y-0 start-0 ${w} max-w-[85vw] ${mobileOpen ? "flex" : "hidden"} md:flex flex-col z-40 overflow-y-auto transition-[width] duration-300 bg-[#090E1C] border-e border-white/10`}>
      <div className={`px-5 py-5 flex items-center ${collapsed ? "justify-center" : "justify-between"}`}>
        {!collapsed && (
          <div>
            <p className="text-[20px] font-bold text-white leading-tight">{t("app_name")}</p>
            <p className="text-[12px] text-[#A1E4DB] mt-0.5">{isRTL ? "السوق السعودي بوضوح" : "Saudi market, decoded"}</p>
          </div>
        )}
        {collapsed && <span className="text-lg font-bold text-[#1E988E]">D</span>}
        <button onClick={() => setCollapsed(!collapsed)} className="hidden md:block p-1 rounded text-[#A1E4DB] hover:text-white" data-testid="sidebar-collapse-btn"
          aria-label={collapsed ? "Expand menu" : "Collapse menu"}>
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
        <button onClick={onClose} className="md:hidden p-1 text-[#A1E4DB]" aria-label="Close navigation" data-testid="mobile-nav-close"><X className="w-5 h-5" /></button>
      </div>

      <nav className="flex-1 px-3 space-y-1">
        {MAIN.filter(may).map((it) => item(it, false))}
        {(manage.length > 0 || user?.role === "super_admin") && (
          <div className="pt-5">
            {!collapsed && <p className="px-3 pb-1.5 text-[12px] font-semibold text-[#A1E4DB]/70">{isRTL ? "الإدارة" : "Manage"}</p>}
            <div className="space-y-0.5">
              {manage.map((it) => item(it, true))}
              {user?.role === "super_admin" && item({ to: "/users", pageKeys: [], icon: Users, en: "Users", ar: "المستخدمون" }, true)}
            </div>
          </div>
        )}
      </nav>

      <div className="px-3 py-3 space-y-0.5 border-t border-white/10">
        <button onClick={toggleLang} data-testid="lang-toggle-btn"
          className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-[13px] text-[#A1E4DB] hover:text-white hover:bg-[#104745]/50 ${collapsed ? "justify-center" : ""}`}>
          <Languages className="w-4 h-4 shrink-0" />{!collapsed && t("lang_switch")}
        </button>
        <button onClick={toggleTheme} data-testid="theme-toggle-btn" title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-[13px] text-[#A1E4DB] hover:text-white hover:bg-[#104745]/50 ${collapsed ? "justify-center" : ""}`}>
          {theme === "dark" ? <Sun className="w-4 h-4 shrink-0" /> : <Moon className="w-4 h-4 shrink-0" />}
          {!collapsed && <span data-testid="theme-toggle-label">{theme === "dark" ? (isRTL ? "الوضع النهاري" : "Light mode") : (isRTL ? "الوضع الليلي" : "Dark mode")}</span>}
        </button>
        {user && !collapsed && <p className="px-3 pt-1 text-[12px] text-[#A1E4DB]/60 truncate">{user.email}</p>}
        {user && (
          <button onClick={logout} data-testid="logout-btn"
            className={`flex items-center gap-3 w-full px-3 py-2 rounded-lg text-[13px] text-[#EF4444]/80 hover:text-[#EF4444] hover:bg-[#EF4444]/5 ${collapsed ? "justify-center" : ""}`}>
            <LogOut className="w-4 h-4 shrink-0" />{!collapsed && t("logout")}
          </button>
        )}
      </div>
    </aside>
  );
}
