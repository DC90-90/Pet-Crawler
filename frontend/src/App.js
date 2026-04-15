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
  if (checking) return <div className="flex items-center justify-center min-h-screen"><p className="text-sm text-gray-500">Loading...</p></div>;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function AppLayout() {
  return (
    <div className="flex min-h-screen bg-[#F3F4F6]" data-testid="app-layout">
      <Sidebar />
      <main className="flex-1 ms-[240px] min-h-screen">
        <Routes>
          <Route path="/" element={<ProtectedRoute><MyProductsPage /></ProtectedRoute>} />
          <Route path="/insights" element={<ProtectedRoute><InsightsPage /></ProtectedRoute>} />
          <Route path="/stores" element={<ProtectedRoute><StoreRegistryPage /></ProtectedRoute>} />
        </Routes>
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
