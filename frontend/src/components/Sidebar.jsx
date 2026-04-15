import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Store,
  Package,
  Trophy,
  GitCompareArrows,
} from "lucide-react";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Overview" },
  { to: "/competitors", icon: Store, label: "Competitors" },
  { to: "/products", icon: Package, label: "Products" },
  { to: "/best-sellers", icon: Trophy, label: "Best Sellers" },
  { to: "/price-comparison", icon: GitCompareArrows, label: "Price Compare" },
];

export default function Sidebar() {
  return (
    <aside
      data-testid="sidebar-nav"
      className="fixed left-0 top-0 h-screen w-[220px] bg-white border-r border-border flex flex-col z-40"
    >
      <div className="px-5 py-5 border-b border-border">
        <h1 className="font-heading text-lg font-semibold tracking-tight text-foreground">
          PetTracker
        </h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          KSA Market Monitor
        </p>
      </div>

      <nav className="flex-1 py-3 px-3 space-y-0.5">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2.5 rounded-sm text-sm font-body transition-all duration-200 ${
                isActive
                  ? "bg-[#002CFA] text-white font-medium"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
              }`
            }
          >
            <item.icon className="w-4 h-4 shrink-0" />
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 border-t border-border">
        <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-medium">
          Pets & Supplies
        </p>
        <p className="text-[10px] text-muted-foreground mt-0.5">
          Saudi Arabia Market
        </p>
      </div>
    </aside>
  );
}
