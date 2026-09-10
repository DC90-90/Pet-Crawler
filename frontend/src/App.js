import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useState, useEffect, createContext, useContext, lazy, Suspense } from "react";
import { Toaster } from "@/components/ui/sonner";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "@/lib/i18n";
import { MySkusProvider } from "@/lib/mySkus";
import api from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import LoginPage from "@/pages/LoginPage";
import NotificationBell from "@/components/NotificationBell";

// Perf sprint Feb 2026 — route-based code splitting. Each page is fetched on
// demand the first time it's navigated to. Cuts initial JS bundle from ~600KB
// to ~80KB (only the login page + sidebar shell load up-front).
const MyProductsPage = lazy(() => import("@/pages/MyProductsPage"));
// Feb 2026 — Insights and Price Intel merged into a single IntelPage.
// Both `/insights` and `/price-intel` mount the same component so existing
// bookmarks keep working.
const IntelPage = lazy(() => import("@/pages/IntelPage"));
const StoreRegistryPage = lazy(() => import("@/pages/StoreRegistryPage"));
const AlertsPage = lazy(() => import("@/pages/AlertsPage"));
const CompetitorProfilePage = lazy(() => import("@/pages/CompetitorProfilePage"));
const DiscountsPage = lazy(() => import("@/pages/DiscountsPage"));
const ScannerPage = lazy(() => import("@/pages/ScannerPage"));
// iter79 — Market Share tab (measured shares, gaps, brands, categories)
const MarketSharePage = lazy(() => import("@/pages/MarketSharePage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const ImportPage = lazy(() => import("@/pages/ImportPage"));
const UsersPage = lazy(() => import("@/pages/UsersPage"));
// iter73v (Aug 8 2026) — admin-only coverage / recrawl / rematch console.
const CoverageReportPage = lazy(() => import("@/pages/CoverageReportPage"));

// Perf sprint Feb 2026 — frontend-side stale-while-revalidate cache.
// 60s staleTime matches backend's TTL cache so refetches are correctly aligned.
// Tab switches under 60s are instant; older data revalidates in background.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,           // data is fresh for 60s
      gcTime: 5 * 60 * 1000,          // keep in cache for 5min
      refetchOnWindowFocus: false,    // don't refetch every time user tabs back
      retry: 1,
    },
  },
});

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

// canHavePageAccess: super_admin sees all; everyone else must have the page in allowed_pages.
export function canAccessPage(user, pageKey) {
  if (!user) return false;
  if (user.role === "super_admin") return true;
  const pages = Array.isArray(user.allowed_pages) ? user.allowed_pages : [];
  return pages.includes(pageKey);
}

function PageLoader() {
  return (
    <div className="flex items-center justify-center min-h-[60vh]" data-testid="page-loader">
      <div className="w-8 h-8 rounded-full border-2 border-[#1E988E] border-t-transparent animate-spin" />
    </div>
  );
}

function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("daleel_token");
    if (!token) { setChecking(false); return; }
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => { localStorage.removeItem("daleel_token"); })
      .finally(() => setChecking(false));
  }, []);

  const login = (token, userData) => {
    localStorage.setItem("daleel_token", token);
    localStorage.setItem("daleel_user", JSON.stringify(userData));
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem("daleel_token");
    localStorage.removeItem("daleel_user");
    setUser(null);
    queryClient.clear();
  };

  const refreshMe = async () => {
    try {
      const { data } = await api.get("/auth/me");
      setUser(data);
      localStorage.setItem("daleel_user", JSON.stringify(data));
      return data;
    } catch (_e) {
      return null;
    }
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, checking, refreshMe }}>
      {children}
    </AuthContext.Provider>
  );
}

function ProtectedRoute({ children, pageKey }) {
  const { user, checking } = useAuth();
  if (checking) return <div className="flex items-center justify-center min-h-screen bg-[#090E1C]"><div className="w-8 h-8 rounded-full border-2 border-[#1E988E] border-t-transparent animate-spin" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (pageKey && !canAccessPage(user, pageKey)) return <Navigate to="/no-access" replace />;
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>;
}

function SuperAdminRoute({ children }) {
  const { user, checking } = useAuth();
  if (checking) return <div className="flex items-center justify-center min-h-screen bg-[#090E1C]"><div className="w-8 h-8 rounded-full border-2 border-[#1E988E] border-t-transparent animate-spin" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "super_admin") return <Navigate to="/no-access" replace />;
  return <Suspense fallback={<PageLoader />}>{children}</Suspense>;
}

function NoAccessPage() {
  const { user, logout } = useAuth();
  return (
    <div className="p-10 text-center" data-testid="no-access-page">
      <h1 className="text-2xl mb-3" style={{ color: "#FFFFFF", fontFamily: "'Space Grotesk', sans-serif", letterSpacing: "0.05em", textTransform: "uppercase" }}>
        Access Restricted
      </h1>
      <p className="text-sm mb-2" style={{ color: "#A1E4DB" }}>
        Your account doesn't have permission to view this page.
      </p>
      {user?.email && (
        <p className="text-xs mb-6" style={{ color: "#A1E4DB", opacity: 0.7 }}>
          Signed in as <span style={{ color: "#6AC1B5" }}>{user.email}</span>. Contact your super admin to request access.
        </p>
      )}
      <button onClick={logout} className="hrm-btn-primary px-6 py-2 text-xs" data-testid="no-access-logout-btn">
        Sign Out
      </button>
    </div>
  );
}

function AppLayout() {
  return (
    <div className="flex min-h-screen" style={{ background: "radial-gradient(circle at top center, #090E1C 0%, #090E1C 100%)" }} data-testid="app-layout">
      <Sidebar />
      <main className="flex-1 ms-[240px] min-h-screen flex flex-col">
        <div className="flex items-center justify-end px-6 py-3 border-b border-white/5">
          <NotificationBell />
        </div>
        <div className="flex-1">
        <Routes>
          <Route path="/" element={<ProtectedRoute pageKey="my_products"><MyProductsPage /></ProtectedRoute>} />
          <Route path="/insights" element={<ProtectedRoute pageKey="insights"><IntelPage /></ProtectedRoute>} />
          <Route path="/alerts" element={<ProtectedRoute pageKey="alerts"><AlertsPage /></ProtectedRoute>} />
          <Route path="/discounts" element={<ProtectedRoute pageKey="discounts"><DiscountsPage /></ProtectedRoute>} />
          <Route path="/scanner" element={<ProtectedRoute pageKey="scanner"><ScannerPage /></ProtectedRoute>} />
          <Route path="/market-share" element={<ProtectedRoute pageKey="market_share"><MarketSharePage /></ProtectedRoute>} />
          <Route path="/stores" element={<ProtectedRoute pageKey="stores"><StoreRegistryPage /></ProtectedRoute>} />
          <Route path="/stores/:storeId" element={<ProtectedRoute pageKey="stores"><CompetitorProfilePage /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute pageKey="settings"><SettingsPage /></ProtectedRoute>} />
          <Route path="/settings/coverage" element={<ProtectedRoute pageKey="settings"><CoverageReportPage /></ProtectedRoute>} />
          <Route path="/import" element={<ProtectedRoute pageKey="import"><ImportPage /></ProtectedRoute>} />
          {/* Backward compat: `/price-intel` bookmarks land on the same merged page.
              Uses `price_intel` page key so users historically granted only that
              permission still reach the intel page. */}
          <Route path="/price-intel" element={<ProtectedRoute pageKey="price_intel"><IntelPage /></ProtectedRoute>} />
          <Route path="/users" element={<SuperAdminRoute><UsersPage /></SuperAdminRoute>} />
          <Route path="/no-access" element={<ProtectedRoute><NoAccessPage /></ProtectedRoute>} />
        </Routes>
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <AuthProvider>
          <MySkusProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/*" element={<AppLayout />} />
              </Routes>
              <Toaster position="top-right" />
            </BrowserRouter>
          </MySkusProvider>
        </AuthProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

export default App;
