import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useState, useEffect, createContext, useContext } from "react";
import { Toaster } from "@/components/ui/sonner";
import { I18nProvider } from "@/lib/i18n";
import api from "@/lib/api";
import Sidebar from "@/components/Sidebar";
import LoginPage from "@/pages/LoginPage";
import MyProductsPage from "@/pages/MyProductsPage";
import InsightsPage from "@/pages/InsightsPage";
import StoreRegistryPage from "@/pages/StoreRegistryPage";
import AlertsPage from "@/pages/AlertsPage";
import CompetitorProfilePage from "@/pages/CompetitorProfilePage";
import DiscountsPage from "@/pages/DiscountsPage";
import ScannerPage from "@/pages/ScannerPage";
import SettingsPage from "@/pages/SettingsPage";
import ImportPage from "@/pages/ImportPage";
import PriceIntelPage from "@/pages/PriceIntelPage";
import NotificationBell from "@/components/NotificationBell";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

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
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, checking }}>
      {children}
    </AuthContext.Provider>
  );
}

function ProtectedRoute({ children }) {
  const { user, checking } = useAuth();
  if (checking) return <div className="flex items-center justify-center min-h-screen bg-[#090E1C]"><div className="w-8 h-8 rounded-full border-2 border-[#1E988E] border-t-transparent animate-spin" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppLayout() {
  return (
    <div className="flex min-h-screen" style={{ background: "radial-gradient(circle at top center, #090E1C 0%, #090E1C 100%)" }} data-testid="app-layout">
      <Sidebar />
      <main className="flex-1 ms-[240px] min-h-screen flex flex-col">
        {/* Top Bar */}
        <div className="flex items-center justify-end px-6 py-3 border-b border-white/5">
          <NotificationBell />
        </div>
        <div className="flex-1">
        <Routes>
          <Route path="/" element={<ProtectedRoute><MyProductsPage /></ProtectedRoute>} />
          <Route path="/insights" element={<ProtectedRoute><InsightsPage /></ProtectedRoute>} />
          <Route path="/alerts" element={<ProtectedRoute><AlertsPage /></ProtectedRoute>} />
          <Route path="/discounts" element={<ProtectedRoute><DiscountsPage /></ProtectedRoute>} />
          <Route path="/scanner" element={<ProtectedRoute><ScannerPage /></ProtectedRoute>} />
          <Route path="/stores" element={<ProtectedRoute><StoreRegistryPage /></ProtectedRoute>} />
          <Route path="/stores/:storeId" element={<ProtectedRoute><CompetitorProfilePage /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><SettingsPage /></ProtectedRoute>} />
          <Route path="/import" element={<ProtectedRoute><ImportPage /></ProtectedRoute>} />
          <Route path="/price-intel" element={<ProtectedRoute><PriceIntelPage /></ProtectedRoute>} />
        </Routes>
        </div>
      </main>
    </div>
  );
}

function App() {
  return (
    <I18nProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/*" element={<AppLayout />} />
          </Routes>
          <Toaster position="top-right" />
        </BrowserRouter>
      </AuthProvider>
    </I18nProvider>
  );
}

export default App;
