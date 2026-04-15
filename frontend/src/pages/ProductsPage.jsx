import { useEffect, useState, useCallback } from "react";
import axios from "axios";
import { Search, ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

function StockBadge({ status, qty }) {
  const styles = {
    in_stock: "bg-green-50 text-green-700 border-green-200",
    low_stock: "bg-yellow-50 text-yellow-700 border-yellow-200",
    out_of_stock: "bg-red-50 text-red-700 border-red-200",
  };
  const labels = {
    in_stock: "In Stock",
    low_stock: "Low Stock",
    out_of_stock: "OOS",
  };
  return (
    <Badge variant="outline" className={`text-[11px] ${styles[status]}`}>
      {labels[status]} {status !== "out_of_stock" && `(${qty})`}
    </Badge>
  );
}

function SortIcon({ field, sortBy, sortOrder }) {
  if (sortBy !== field)
    return <ArrowUpDown className="w-3 h-3 ml-1 opacity-30" />;
  return sortOrder === "asc" ? (
    <ArrowUp className="w-3 h-3 ml-1 text-[#002CFA]" />
  ) : (
    <ArrowDown className="w-3 h-3 ml-1 text-[#002CFA]" />
  );
}

export default function ProductsPage() {
  const [products, setProducts] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState([]);
  const [competitors, setCompetitors] = useState([]);
  const [filters, setFilters] = useState({
    category: "all",
    competitor_id: "all",
    stock_status: "all",
    search: "",
    sort_by: "name",
    sort_order: "asc",
  });

  useEffect(() => {
    Promise.all([
      axios.get(`${API}/products/categories`),
      axios.get(`${API}/competitors`),
    ]).then(([catRes, compRes]) => {
      setCategories(catRes.data);
      setCompetitors(compRes.data);
    });
  }, []);

  const fetchProducts = useCallback(() => {
    setLoading(true);
    const params = {};
    if (filters.category !== "all") params.category = filters.category;
    if (filters.competitor_id !== "all")
      params.competitor_id = filters.competitor_id;
    if (filters.stock_status !== "all")
      params.stock_status = filters.stock_status;
    if (filters.search) params.search = filters.search;
    params.sort_by = filters.sort_by;
    params.sort_order = filters.sort_order;
    params.limit = 200;

    axios
      .get(`${API}/products`, { params })
      .then((r) => {
        setProducts(r.data.products);
        setTotal(r.data.total);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filters]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  const handleSort = (field) => {
    setFilters((f) => ({
      ...f,
      sort_by: field,
      sort_order: f.sort_by === field && f.sort_order === "asc" ? "desc" : "asc",
    }));
  };

  return (
    <div className="p-6 lg:p-8 space-y-5" data-testid="products-page">
      <div>
        <h1 className="text-2xl font-heading font-semibold tracking-tight text-foreground">
          Product Tracking
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          {total} products tracked across all competitors
        </p>
      </div>

      {/* Filters */}
      <div
        className="flex flex-wrap items-center gap-3 bg-white border border-border rounded-sm p-3"
        data-testid="product-filters"
      >
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
          <Input
            placeholder="Search products..."
            value={filters.search}
            onChange={(e) =>
              setFilters((f) => ({ ...f, search: e.target.value }))
            }
            className="pl-8 h-8 text-sm rounded-sm"
            data-testid="product-search-input"
          />
        </div>
        <Select
          value={filters.category}
          onValueChange={(v) => setFilters((f) => ({ ...f, category: v }))}
        >
          <SelectTrigger
            className="w-[160px] h-8 text-sm rounded-sm"
            data-testid="filter-category"
          >
            <SelectValue placeholder="Category" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Categories</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={filters.competitor_id}
          onValueChange={(v) =>
            setFilters((f) => ({ ...f, competitor_id: v }))
          }
        >
          <SelectTrigger
            className="w-[160px] h-8 text-sm rounded-sm"
            data-testid="filter-competitor"
          >
            <SelectValue placeholder="Competitor" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Competitors</SelectItem>
            {competitors.map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select
          value={filters.stock_status}
          onValueChange={(v) =>
            setFilters((f) => ({ ...f, stock_status: v }))
          }
        >
          <SelectTrigger
            className="w-[140px] h-8 text-sm rounded-sm"
            data-testid="filter-stock"
          >
            <SelectValue placeholder="Stock" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Stock</SelectItem>
            <SelectItem value="in_stock">In Stock</SelectItem>
            <SelectItem value="low_stock">Low Stock</SelectItem>
            <SelectItem value="out_of_stock">Out of Stock</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="bg-white border border-border rounded-sm overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead
                className="sort-header font-heading text-xs uppercase tracking-wider"
                onClick={() => handleSort("name")}
              >
                <span className="flex items-center">
                  Product
                  <SortIcon
                    field="name"
                    sortBy={filters.sort_by}
                    sortOrder={filters.sort_order}
                  />
                </span>
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Competitor
              </TableHead>
              <TableHead
                className="sort-header font-heading text-xs uppercase tracking-wider"
                onClick={() => handleSort("category")}
              >
                <span className="flex items-center">
                  Category
                  <SortIcon
                    field="category"
                    sortBy={filters.sort_by}
                    sortOrder={filters.sort_order}
                  />
                </span>
              </TableHead>
              <TableHead
                className="sort-header font-heading text-xs uppercase tracking-wider"
                onClick={() => handleSort("price")}
              >
                <span className="flex items-center">
                  Price (SAR)
                  <SortIcon
                    field="price"
                    sortBy={filters.sort_by}
                    sortOrder={filters.sort_order}
                  />
                </span>
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Stock
              </TableHead>
              <TableHead
                className="sort-header font-heading text-xs uppercase tracking-wider"
                onClick={() => handleSort("rating")}
              >
                <span className="flex items-center">
                  Rating
                  <SortIcon
                    field="rating"
                    sortBy={filters.sort_by}
                    sortOrder={filters.sort_order}
                  />
                </span>
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Shipping
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={7}
                  className="text-center py-12 text-muted-foreground"
                >
                  Loading products...
                </TableCell>
              </TableRow>
            ) : products.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-12">
                  <img
                    src="https://static.prod-images.emergentagent.com/jobs/e703fccc-0c9e-4960-bc7a-841f7b4e9557/images/0d7e3378028be99612eeff64c9aa7c7891b1189248d635feac4b981aba59c56f.png"
                    alt="No products"
                    className="w-24 h-24 mx-auto mb-3 opacity-70"
                  />
                  <p className="text-sm text-muted-foreground">
                    No products match your filters
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              products.map((p) => (
                <TableRow key={p.id} data-testid={`product-row-${p.id}`}>
                  <TableCell>
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {p.name}
                      </p>
                      {p.is_best_seller && (
                        <Badge className="bg-amber-50 text-amber-700 border-amber-200 text-[10px] mt-0.5" variant="outline">
                          Best Seller
                        </Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm">{p.competitor_name}</span>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className="text-[11px] rounded-sm"
                    >
                      {p.category}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div>
                      <span className="text-sm font-semibold text-foreground">
                        {p.price}
                      </span>
                      {p.discount_percentage > 0 && (
                        <div className="flex items-center gap-1.5">
                          <span className="text-[11px] text-muted-foreground line-through">
                            {p.original_price}
                          </span>
                          <span className="text-[11px] text-green-600 font-medium">
                            -{p.discount_percentage}%
                          </span>
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <StockBadge
                      status={p.stock_status}
                      qty={p.stock_quantity}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <span className="text-sm font-medium">{p.rating}</span>
                      <span className="text-[11px] text-muted-foreground">
                        ({p.reviews_count})
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      {p.shipping_info}
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
