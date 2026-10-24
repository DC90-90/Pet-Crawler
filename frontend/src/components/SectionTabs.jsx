/**
 * Tabs across the top of a menu section that groups several pages (Market:
 * market share, key brands, opportunities). Each tab is its own page and
 * permission; a tab shows only when the user may open it (25 Oct 2026).
 */
import { NavLink } from "react-router-dom";
import { useAuth, canAccessPage } from "@/App";
import { useI18n } from "@/lib/i18n";

export const SECTIONS = {
  market: [
    { to: "/market-share", pageKey: "market_share", en: "Market share", ar: "الحصة السوقية" },
    { to: "/key-brands", pageKey: "key_brands", en: "Key brands", ar: "العلامات الرئيسية" },
    { to: "/opportunities", pageKey: "opportunities", en: "Opportunities", ar: "الفرص" },
  ],
};

export function SectionTabs({ section }) {
  const { user } = useAuth();
  const { isRTL } = useI18n();
  const tabs = (SECTIONS[section] || []).filter((t) => canAccessPage(user, t.pageKey));
  if (tabs.length < 2) return null;
  return (
    <nav className="flex flex-wrap gap-1 border-b border-white/10 -mt-1" data-testid={`section-tabs-${section}`}>
      {tabs.map((t) => (
        <NavLink key={t.to} to={t.to}
          className={({ isActive }) => `px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
            isActive ? "border-[#1E988E] text-white" : "border-transparent text-[#A1E4DB] hover:text-white"}`}>
          {isRTL ? t.ar : t.en}
        </NavLink>
      ))}
    </nav>
  );
}
