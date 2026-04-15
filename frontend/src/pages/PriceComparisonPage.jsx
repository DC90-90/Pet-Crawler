import { useEffect, useState } from "react";
import axios from "axios";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
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

function PriceCell({ data, minPrice }) {
  if (!data)
    return (
      <span className="text-xs text-muted-foreground/40">N/A</span>
    );

  const isLowest = data.price === minPrice;
  const isOos = data.stock_status === "out_of_stock";

  return (
    <div className="text-center">
      <p
        className={`text-sm font-semibold ${
          isLowest ? "text-green-600" : "text-foreground"
        } ${isOos ? "line-through opacity-50" : ""}`}
      >
        {data.price} SAR
      </p>
      {data.discount_percentage > 0 && (
        <p className="text-[10px] text-green-600">-{data.discount_percentage}%</p>
      )}
      {isOos && (
        <p className="text-[10px] text-red-500 font-medium">Out of Stock</p>
      )}
    </div>
  );
}

export default function PriceComparisonPage() {
  const [comparison, setComparison] = useState([]);
  const [competitorNames, setCompetitorNames] = useState([]);
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
      .get(`${API}/products/price-comparison`, { params })
      .then((r) => {
        setComparison(r.data.comparison);
        setCompetitorNames(r.data.competitors);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [category]);

  return (
    <div className="p-6 lg:p-8 space-y-5" data-testid="price-comparison-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-heading font-semibold tracking-tight text-foreground">
            Price Comparison
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Compare product prices across competitors
          </p>
        </div>
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger
            className="w-[180px] h-8 text-sm rounded-sm"
            data-testid="pricecomp-category-filter"
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

      <div className="bg-white border border-border rounded-sm overflow-x-auto">
        <Table className="dense-table">
          <TableHeader>
            <TableRow className="bg-muted/40">
              <TableHead className="font-heading text-xs uppercase tracking-wider min-w-[220px] sticky left-0 bg-muted/40 z-10">
                Product
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider">
                Category
              </TableHead>
              {competitorNames.map((name) => (
                <TableHead
                  key={name}
                  className="font-heading text-xs uppercase tracking-wider text-center min-w-[120px]"
                >
                  {name}
                </TableHead>
              ))}
              <TableHead className="font-heading text-xs uppercase tracking-wider text-center">
                Spread
              </TableHead>
              <TableHead className="font-heading text-xs uppercase tracking-wider text-center">
                Avg
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell
                  colSpan={competitorNames.length + 4}
                  className="text-center py-12 text-muted-foreground"
                >
                  Loading...
                </TableCell>
              </TableRow>
            ) : comparison.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={competitorNames.length + 4}
                  className="text-center py-12 text-muted-foreground"
                >
                  No comparison data available
                </TableCell>
              </TableRow>
            ) : (
              comparison.map((item) => (
                <TableRow key={item.product_name} data-testid={`pricecomp-row-${item.product_name}`}>
                  <TableCell className="font-medium text-sm sticky left-0 bg-white z-10 min-w-[220px]">
                    {item.product_name}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="secondary"
                      className="text-[11px] rounded-sm"
                    >
                      {item.category}
                    </Badge>
                  </TableCell>
                  {competitorNames.map((name) => (
                    <TableCell key={name}>
                      <PriceCell
                        data={item.prices[name]}
                        minPrice={item.min_price}
                      />
                    </TableCell>
                  ))}
                  <TableCell className="text-center">
                    <div className="flex items-center justify-center gap-1">
                      {item.price_spread > 20 ? (
                        <ArrowUp className="w-3 h-3 text-red-500" />
                      ) : item.price_spread > 5 ? (
                        <Minus className="w-3 h-3 text-yellow-500" />
                      ) : (
                        <ArrowDown className="w-3 h-3 text-green-500" />
                      )}
                      <span
                        className={`text-sm font-semibold ${
                          item.price_spread > 20
                            ? "text-red-600"
                            : item.price_spread > 5
                            ? "text-yellow-600"
                            : "text-green-600"
                        }`}
                      >
                        {item.price_spread} SAR
                      </span>
                    </div>
                  </TableCell>
                  <TableCell className="text-center">
                    <span className="text-sm font-medium">
                      {item.avg_price} SAR
                    </span>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Legend */}
      <div className="flex items-center gap-6 text-xs text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <span className="text-green-600 font-semibold">Green</span>
          <span>= Lowest price</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="line-through">Strikethrough</span>
          <span>= Out of stock</span>
        </div>
        <div className="flex items-center gap-1.5">
          <ArrowUp className="w-3 h-3 text-red-500" />
          <span>High spread (&gt;20 SAR)</span>
        </div>
        <div className="flex items-center gap-1.5">
          <ArrowDown className="w-3 h-3 text-green-500" />
          <span>Low spread (&lt;5 SAR)</span>
        </div>
      </div>
    </div>
  );
}
