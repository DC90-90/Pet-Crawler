import { useState, type ReactNode } from "react";
import {
  Outlet,
  NavLink,
  Navigate,
  Link,
  useLocation,
} from "react-router-dom";
import { Spinner, Button, Drawer, Chip } from "@heroui/react";
import { ApiError } from "@/lib/api";
import { useMe, useLogout } from "@/lib/admin";
import { Toaster } from "@/components/admin/Toaster";

interface NavItem {
  to: string;
  label: string;
  icon: string;
  end?: boolean;
  ownerOnly?: boolean;
}
interface NavGroup {
  title: string;
  items: NavItem[];
}

const NAV: NavGroup[] = [
  {
    title: "Content",
    items: [
      { to: "/admin", label: "Overview", icon: "◆", end: true },
      { to: "/admin/pages", label: "Pages", icon: "▤" },
      { to: "/admin/tours", label: "Tours", icon: "⛰" },
      { to: "/admin/destinations", label: "Destinations", icon: "📍" },
      { to: "/admin/articles", label: "Travel Guide", icon: "✎" },
      { to: "/admin/reviews", label: "Reviews", icon: "★" },
      { to: "/admin/faqs", label: "FAQs", icon: "?" },
    ],
  },
  {
    title: "Media",
    items: [
      { to: "/admin/media", label: "Media Library", icon: "▦" },
      { to: "/admin/gallery", label: "Gallery", icon: "▨" },
      { to: "/admin/videos", label: "Videos", icon: "▶" },
    ],
  },
  {
    title: "Marketing",
    items: [
      { to: "/admin/banners", label: "Banners", icon: "▭" },
      { to: "/admin/offers", label: "Offers", icon: "％" },
      { to: "/admin/popups", label: "Popups", icon: "◳" },
    ],
  },
  {
    title: "Inbox",
    items: [{ to: "/admin/inquiries", label: "Inquiries", icon: "✉" }],
  },
  {
    title: "Site",
    items: [
      { to: "/admin/navigation", label: "Navigation", icon: "≣" },
      { to: "/admin/seo", label: "SEO", icon: "🔍" },
      { to: "/admin/settings", label: "Settings", icon: "⚙" },
    ],
  },
  {
    title: "System",
    items: [
      { to: "/admin/users", label: "Users", icon: "👤", ownerOnly: true },
      { to: "/admin/audit", label: "Audit Log", icon: "▤" },
    ],
  },
];

function BrandMark() {
  return (
    <Link to="/admin" className="flex items-center gap-2.5">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-alpine-deep to-copper text-sm font-bold text-white">
        SG
      </span>
      <span className="flex flex-col leading-tight">
        <span className="font-display text-sm font-semibold text-foreground">
          Svaneti
        </span>
        <span className="text-[0.7rem] uppercase tracking-widest text-muted">
          with Georgie
        </span>
      </span>
    </Link>
  );
}

function SidebarContent({
  isOwner,
  onNavigate,
}: {
  isOwner: boolean;
  onNavigate?: () => void;
}) {
  return (
    <nav className="flex flex-col gap-5 px-3 py-4" aria-label="Admin sections">
      {NAV.map((group) => {
        const items = group.items.filter((i) => !i.ownerOnly || isOwner);
        if (items.length === 0) return null;
        return (
          <div key={group.title}>
            <p className="px-2 pb-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.16em] text-muted">
              {group.title}
            </p>
            <ul className="flex flex-col gap-0.5">
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    onClick={onNavigate}
                    className={({ isActive }) =>
                      `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition ${
                        isActive
                          ? "bg-copper/12 font-medium text-copper"
                          : "text-foreground/80 hover:bg-surface hover:text-foreground"
                      }`
                    }
                  >
                    <span aria-hidden className="w-4 text-center text-xs opacity-70">
                      {item.icon}
                    </span>
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </nav>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="min-h-dvh bg-background text-foreground">{children}</div>;
}

export function Component() {
  const { data: me, isLoading, isError, error } = useMe();
  const logout = useLogout();
  const location = useLocation();
  const [drawerOpen, setDrawerOpen] = useState(false);

  if (isLoading) {
    return (
      <Shell>
        <div className="grid min-h-dvh place-items-center">
          <Spinner />
        </div>
      </Shell>
    );
  }

  // Auth guard: 401 (or any auth failure) → login, preserving intended path.
  const unauthorized =
    isError && error instanceof ApiError && (error.status === 401 || error.status === 403);
  if (unauthorized || (isError && !me) || !me) {
    return (
      <Navigate to="/admin/login" replace state={{ from: location.pathname }} />
    );
  }

  const isOwner = me.role === "owner";

  return (
    <Shell>
      {/* Top bar */}
      <header className="sticky top-0 z-40 flex h-16 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur">
        <div className="lg:hidden">
          <Button
            variant="outline"
            size="sm"
            isIconOnly
            aria-label="Open navigation"
            onPress={() => setDrawerOpen(true)}
          >
            ☰
          </Button>
        </div>
        <div className="hidden lg:block">
          <BrandMark />
        </div>
        <div className="lg:hidden">
          <BrandMark />
        </div>
        <div className="ms-auto flex items-center gap-3">
          <a
            href="/"
            target="_blank"
            rel="noreferrer"
            className="hidden text-sm text-muted hover:text-foreground sm:inline"
          >
            View site ↗
          </a>
          <div className="hidden items-center gap-2 sm:flex">
            <div className="text-end leading-tight">
              <p className="text-sm font-medium text-foreground">
                {me.name ?? me.email}
              </p>
              <p className="text-xs text-muted">{me.email}</p>
            </div>
            <Chip size="sm" variant="soft" color={isOwner ? "accent" : "default"}>
              {me.role}
            </Chip>
          </div>
          <Button
            variant="tertiary"
            size="sm"
            onPress={() => {
              logout.mutate(undefined, {
                onSuccess: () => {
                  window.location.href = "/admin/login";
                },
              });
            }}
            isDisabled={logout.isPending}
          >
            Log out
          </Button>
        </div>
      </header>

      <div className="flex">
        {/* Desktop sidebar */}
        <aside className="sticky top-16 hidden h-[calc(100dvh-4rem)] w-64 shrink-0 overflow-y-auto border-e border-border bg-surface/30 lg:block">
          <SidebarContent isOwner={isOwner} />
        </aside>

        {/* Mobile drawer */}
        <Drawer isOpen={drawerOpen} onOpenChange={setDrawerOpen}>
          <Drawer.Backdrop variant="blur">
            <Drawer.Content placement="left">
              <Drawer.Dialog className="w-72">
                <Drawer.CloseTrigger />
                <Drawer.Header>
                  <BrandMark />
                </Drawer.Header>
                <Drawer.Body>
                  <SidebarContent
                    isOwner={isOwner}
                    onNavigate={() => setDrawerOpen(false)}
                  />
                </Drawer.Body>
              </Drawer.Dialog>
            </Drawer.Content>
          </Drawer.Backdrop>
        </Drawer>

        {/* Main content */}
        <main id="admin-main" className="min-w-0 flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>

      <Toaster />
    </Shell>
  );
}
