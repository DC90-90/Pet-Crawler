import { useEffect, useState } from "react";
import axios from "axios";
import {
  Store,
  Package,
  AlertTriangle,
  Trophy,
  TrendingUp,
  Star,
  Tag,
  Percent,
} from "lucide-react";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function MetricCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div
      data-testid={`metric-${label.toLowerCase().replace(/\s+/g, "-")}`}
      className="bg-white border border-border rounded-sm p-4 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-sm"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground font-medium">
            {label}
          </p>
          <p className="text-3xl font-bold tracking-tighter font-heading mt-1 text-foreground">
            {value}
          </p>
          {sub && (
            <p className="text-xs text-muted-foreground mt-1">{sub}</p>
          )}
        </div>
        <div
          className="w-9 h-9 rounded-sm flex items-center justify-center"
          style={{ backgroundColor: color + "14" }}
        >
          <Icon className="w-4 h-4" style={{ color }} />
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [overview, setOverview] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios
      .get(`${API}/dashboard/overview`)
      .then((r) => setOverview(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="p-8" data-testid="dashboard-loading">
        <div className="animate-pulse space-y-6">
          <div className="h-8 bg-muted rounded w-48" />
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-28 bg-muted rounded-sm" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!overview) return null;

  return (
    <div className="p-6 lg:p-8 space-y-6" data-testid="dashboard-page">
      <div>
        <h1 className="text-2xl font-heading font-semibold tracking-tight text-foreground">
          Market Overview
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          KSA Pets & Supplies competitive landscape
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          icon={Store}
          label="Competitors"
          value={overview.total_competitors}
          sub="Active stores tracked"
          color="#002CFA"
        />
        <MetricCard
          icon={Package}
          label="Total Products"
          value={overview.total_products}
          sub={`Across ${overview.total_categories} categories`}
          color="#002CFA"
        />
        <MetricCard
          icon={TrendingUp}
          label="Avg. Price"
          value={`${overview.avg_price} SAR`}
          sub={`Avg discount ${overview.avg_discount}%`}
          color="#00C853"
        />
        <MetricCard
          icon={AlertTriangle}
          label="Out of Stock"
          value={overview.out_of_stock_count}
          sub={`${overview.low_stock_count} low stock`}
          color="#FF3B30"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          icon={Trophy}
          label="Best Sellers"
          value={overview.best_seller_count}
          sub="High volume products"
          color="#FFB300"
        />
        <MetricCard
          icon={Star}
          label="Avg. Rating"
          value={overview.avg_rating}
          sub="Across all products"
          color="#FFB300"
        />
        <MetricCard
          icon={Tag}
          label="Categories"
          value={overview.total_categories}
          sub="Product categories"
          color="#002CFA"
        />
        <MetricCard
          icon={Percent}
          label="Avg. Discount"
          value={`${overview.avg_discount}%`}
          sub="Market average"
          color="#00C853"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Categories Breakdown */}
        <div className="bg-white border border-border rounded-sm p-5">
          <h3 className="text-sm font-heading font-medium tracking-tight text-foreground mb-4">
            Products by Category
          </h3>
          <div className="space-y-3">
            {overview.categories.map((cat) => {
              const pct = Math.round(
                (cat.count / overview.total_products) * 100
              );
              return (
                <div key={cat.name} data-testid={`cat-${cat.name}`}>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-foreground font-medium">
                      {cat.name}
                    </span>
                    <span className="text-muted-foreground">
                      {cat.count} ({pct}%)
                    </span>
                  </div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: "#002CFA",
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Competitor Product Counts */}
        <div className="bg-white border border-border rounded-sm p-5">
          <h3 className="text-sm font-heading font-medium tracking-tight text-foreground mb-4">
            Products by Competitor
          </h3>
          <div className="space-y-3">
            {overview.competitor_product_counts.map((comp) => {
              const maxCount = Math.max(
                ...overview.competitor_product_counts.map((c) => c.total_products)
              );
              const pct = Math.round((comp.total_products / maxCount) * 100);
              return (
                <div key={comp.name} data-testid={`comp-bar-${comp.name}`}>
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-foreground font-medium">
                      {comp.name}
                    </span>
                    <span className="text-muted-foreground">
                      {comp.total_products} products
                    </span>
                  </div>
                  <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: "#002CFA",
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Platform Distribution */}
      <div className="bg-white border border-border rounded-sm p-5">
        <h3 className="text-sm font-heading font-medium tracking-tight text-foreground mb-4">
          Store Platforms
        </h3>
        <div className="flex gap-6">
          {overview.platform_distribution.map((p) => (
            <div
              key={p.name}
              className="flex items-center gap-2"
              data-testid={`platform-${p.name}`}
            >
              <div className="w-2.5 h-2.5 rounded-full bg-[#002CFA]" />
              <span className="text-sm text-foreground font-medium">
                {p.name}
              </span>
              <span className="text-xs text-muted-foreground">
                ({p.count})
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
