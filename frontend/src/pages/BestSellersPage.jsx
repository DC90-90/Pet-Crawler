import { useEffect, useState } from "react";
import axios from "axios";
import { Trophy, TrendingUp } from "lucide-react";
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

export default function BestSellersPage() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [category, setCategory] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    axios.get(`${API}/products/categories`).then((r) => setCategories(r.data));
  }, []);

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (category !== "all") params.category = category;
    axios
      .get(`${API}/products/best-sellers`, { params })
      .then((r) => setProducts(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [category]);

  return (
    <div className="p-6 lg:p-8 space-y-5" data-testid="best-sellers-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading font-semibold tracking-tight text-foreground">
            Best Sellers
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Top performing products across competitors
          </p>
        </div>
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger
            className="w-[180px] h-8 text-sm rounded-sm"
            data-testid="bestseller-category-filter"
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
      </div>

      <div className="bg-white border border-border rounded-sm overflow-hidden">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="font-heading text-xs uppercase tracking-wider w-12">
                Rank
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Product
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Competitor
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Category
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Price (SAR)
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Sales
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Rating
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Stock
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={8}
                  className="text-center py-12 text-muted-foreground"
                >
                  Loading...
                </TableCell>
              </TableRow>
            ) : products.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center py-12">
                  <Trophy className="w-10 h-10 text-muted-foreground/40 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">
                    No best sellers found
                  </p>
                </TableCell>
              </TableRow>
            ) : (
              products.map((p, idx) => (
                <TableRow key={p.id} data-testid={`bestseller-row-${idx}`}>
                  <TableCell>
                    <div
                      className={`w-7 h-7 rounded-sm flex items-center justify-center text-xs font-bold ${
                        idx < 3
                          ? "bg-[#002CFA] text-white"
                          : "bg-muted text-muted-foreground"
                      }`}
                    >
                      {idx + 1}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground">
                        {p.name}
                      </p>
                      {idx < 3 && (
                        <TrendingUp className="w-3.5 h-3.5 text-green-500" />
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm">{p.competitor_name}</TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className="text-[11px] rounded-sm"
                    >
                      {p.category}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm font-semibold">{p.price}</span>
                    {p.discount_percentage > 0 && (
                      <span className="text-[11px] text-green-600 ml-1">
                        -{p.discount_percentage}%
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className="text-sm font-semibold text-foreground">
                      {p.sales_count.toLocaleString()}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-sm">{p.rating}</span>
                    <span className="text-[11px] text-muted-foreground ml-0.5">
                      ({p.reviews_count})
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-xs text-muted-foreground">
                      {p.stock_quantity > 0 ? `${p.stock_quantity} units` : "OOS"}
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
