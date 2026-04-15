import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import Sidebar from "@/components/Sidebar";
import DashboardPage from "@/pages/DashboardPage";
import CompetitorsPage from "@/pages/CompetitorsPage";
import ProductsPage from "@/pages/ProductsPage";
import BestSellersPage from "@/pages/BestSellersPage";
import PriceComparisonPage from "@/pages/PriceComparisonPage";

function App() {
  return (
    <BrowserRouter>
      <div className="flex min-h-screen bg-background" data-testid="app-root">
        <Sidebar />
        <main className="flex-1 ml-[220px] min-h-screen">
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/competitors" element={<CompetitorsPage />} />
            <Route path="/products" element={<ProductsPage />} />
            <Route path="/best-sellers" element={<BestSellersPage />} />
            <Route path="/price-comparison" element={<PriceComparisonPage />} />
          </Routes>
        </main>
        <Toaster position="top-right" />
      </div>
    </BrowserRouter>
  );
}

export default App;
