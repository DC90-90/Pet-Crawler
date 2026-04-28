import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ConfidenceBadge, FlagBadges } from "./PriceIntelShared";
import { MineBadge } from "@/components/MineBadge";

function ActionRequiredTable({ rows, onOpen }) {
  return (
    <div className="glass-card overflow-hidden">
      <Table className="dense-table">
        <TableHeader><TableRow>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Product</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">My Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Cheapest</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Diff%</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Confidence</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Severity</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow><TableCell colSpan={6} className="text-center py-12 text-[#A1E4DB]">No overpriced products found</TableCell></TableRow>
          ) : rows.slice(0, 50).map((r) => (
            <TableRow key={r.my_sku} className="cursor-pointer" onClick={() => onOpen(r.my_sku)}>
              <TableCell><p className="text-sm text-white font-medium truncate max-w-[250px] inline-flex items-center gap-1.5"><MineBadge sku={r.my_sku} />{r.my_name_en || r.my_name_ar}</p><p className="text-[10px] text-[#A1E4DB]">{r.my_sku}</p></TableCell>
              <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
              <TableCell><span className="text-sm text-[#A1E4DB]">{r.cheapest_competitor}</span><br/><span className="text-sm font-semibold text-[#10B981] metric-number">{r.cheapest_price} SAR</span></TableCell>
              <TableCell><span className={`text-sm font-bold ${r.diff_pct > 15 ? "text-[#EF4444]" : "text-[#F59E0B]"}`}>+{r.diff_pct}%</span></TableCell>
              <TableCell><ConfidenceBadge confidence={r.confidence} /></TableCell>
              <TableCell><span className={`inline-block w-3 h-3 rounded-full ${r.severity === "red" ? "bg-[#EF4444]" : "bg-[#F59E0B]"}`} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function MyAdvantagesTable({ rows, onOpen }) {
  return (
    <div className="glass-card overflow-hidden">
      <Table className="dense-table">
        <TableHeader><TableRow>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Product</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">My Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Advantage</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Detail</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Confidence</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow><TableCell colSpan={5} className="text-center py-12 text-[#A1E4DB]">No advantages found yet</TableCell></TableRow>
          ) : rows.slice(0, 50).map((r, i) => (
            <TableRow key={`${r.my_sku}-${r.advantage}-${i}`} className="cursor-pointer" onClick={() => onOpen(r.my_sku)}>
              <TableCell><p className="text-sm text-white font-medium truncate max-w-[250px] inline-flex items-center gap-1.5"><MineBadge sku={r.my_sku} />{r.my_name_en || r.my_name_ar}</p></TableCell>
              <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
              <TableCell>
                {r.advantage === "cheapest" ? <Badge className="bg-[#10B981]/15 text-[#10B981] border-0 text-xs">I'm Cheapest</Badge> : <Badge className="bg-[#1E988E]/15 text-[#1E988E] border-0 text-xs">Competitor OOS</Badge>}
              </TableCell>
              <TableCell>{r.advantage === "cheapest" ? <span className="text-sm text-[#10B981]">Saving {r.saving_sar} SAR</span> : <span className="text-sm text-[#1E988E]">My stock: {r.my_stock}</span>}</TableCell>
              <TableCell><ConfidenceBadge confidence={r.confidence} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function FullComparisonTable({ rows, onOpen }) {
  return (
    <div className="glass-card overflow-hidden">
      <Table className="dense-table">
        <TableHeader><TableRow>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">My Product</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">My Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Cheapest Competitor</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Diff%</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Sellers</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Confidence</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Flags</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow><TableCell colSpan={8} className="text-center py-12 text-[#A1E4DB]">No matches found. Import products and run matching first.</TableCell></TableRow>
          ) : rows.slice(0, 100).map((r) => (
            <TableRow key={r.my_sku} className="cursor-pointer" onClick={() => onOpen(r.my_sku)}>
              <TableCell><p className="text-sm text-white font-medium truncate max-w-[200px] inline-flex items-center gap-1.5"><MineBadge sku={r.my_sku} />{r.my_name_en || r.my_name_ar}</p><p className="text-[10px] text-[#A1E4DB]">{r.my_sku}</p></TableCell>
              <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
              <TableCell><span className="text-xs text-[#A1E4DB]">{r.cheapest_competitor}</span></TableCell>
              <TableCell><span className="text-sm font-semibold metric-number" style={{ color: r.diff_pct > 0 ? "#EF4444" : "#10B981" }}>{r.cheapest_price} SAR</span></TableCell>
              <TableCell><span className={`text-sm font-bold ${r.diff_pct > 5 ? "text-[#EF4444]" : r.diff_pct < -5 ? "text-[#10B981]" : "text-[#A1E4DB]"}`}>{r.diff_pct > 0 ? "+" : ""}{r.diff_pct}%</span></TableCell>
              <TableCell><Badge className="bg-white/10 border-0 text-[#A1E4DB] text-xs">{r.sellers}</Badge></TableCell>
              <TableCell><ConfidenceBadge confidence={r.confidence} /></TableCell>
              <TableCell><FlagBadges flags={r.flags} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function UnverifiedTable({ rows, onOpen, isRTL }) {
  return (
    <div className="glass-card overflow-hidden">
      <div className="px-4 py-3 border-b border-white/5 bg-[#F59E0B]/5">
        <p className="text-xs text-[#F59E0B]">{isRTL ? "هذه المطابقات بثقة أقل من 75% — تحتاج مراجعة يدوية" : "These matches have <75% confidence — manual review required"}</p>
      </div>
      <Table className="dense-table">
        <TableHeader><TableRow>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">My Product</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">My Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Competitor</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Confidence</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Actions</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow><TableCell colSpan={6} className="text-center py-12 text-[#A1E4DB]">No unverified matches</TableCell></TableRow>
          ) : rows.slice(0, 50).map((r) => (
            <TableRow key={r.my_sku}>
              <TableCell><p className="text-sm text-white truncate max-w-[200px] inline-flex items-center gap-1.5"><MineBadge sku={r.my_sku} />{r.my_name_en || r.my_name_ar}</p><p className="text-[10px] text-[#A1E4DB]">{r.my_sku}</p></TableCell>
              <TableCell><span className="text-sm font-semibold text-white metric-number">{r.my_price} SAR</span></TableCell>
              <TableCell><span className="text-xs text-[#A1E4DB]">{r.cheapest_competitor}</span><br/><span className="text-sm metric-number text-white">{r.cheapest_price} SAR</span></TableCell>
              <TableCell><span className={`text-sm font-bold ${r.diff_pct > 5 ? "text-[#EF4444]" : "text-[#A1E4DB]"}`}>{r.diff_pct > 0 ? "+" : ""}{r.diff_pct}%</span></TableCell>
              <TableCell><ConfidenceBadge confidence={r.confidence} /></TableCell>
              <TableCell>
                <Button size="sm" variant="ghost" onClick={() => onOpen(r.my_sku)} className="text-[10px] text-[#1E988E] h-7">Review</Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CatalogGapsTable({ gaps, isRTL }) {
  return (
    <div className="glass-card overflow-hidden">
      <div className="px-4 py-3 border-b border-white/5 bg-[#1E988E]/5">
        <p className="text-xs text-[#1E988E]">{isRTL ? "منتجات رائجة لا تبيعها — فرص إيرادات فورية" : "Trending products you DON'T sell — immediate revenue opportunities"}</p>
        <Badge className="text-[8px] bg-[#F59E0B]/10 text-[#F59E0B] border-0 mt-1">Includes baseline data (expires May 17)</Badge>
      </div>
      <Table className="dense-table">
        <TableHeader><TableRow>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Priority</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Product</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Barcode</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Est. Revenue (14d)</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Units Sold</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Sellers</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Avg Price</TableHead>
          <TableHead className="text-[10px] uppercase text-[#A1E4DB]">Action</TableHead>
        </TableRow></TableHeader>
        <TableBody>
          {gaps.length === 0 ? (
            <TableRow><TableCell colSpan={8} className="text-center py-12 text-[#A1E4DB]">No catalog gaps found</TableCell></TableRow>
          ) : gaps.map((g) => (
            <TableRow key={g.barcode}>
              <TableCell>
                <Badge className={`text-[10px] border-0 ${g.priority?.includes("🔴") ? "bg-[#EF4444]/15 text-[#EF4444]" : "bg-[#F59E0B]/15 text-[#F59E0B]"}`}>{g.priority}</Badge>
              </TableCell>
              <TableCell><p className="text-sm text-white font-medium max-w-[250px] truncate">{g.product_name}</p></TableCell>
              <TableCell><span className="text-xs font-mono text-[#A1E4DB]">{g.barcode}</span></TableCell>
              <TableCell><span className="text-sm font-bold text-[#1E988E] metric-number">{g.est_revenue_sar?.toLocaleString()} SAR</span></TableCell>
              <TableCell><span className="text-sm metric-number text-white">{g.est_units_sold}</span></TableCell>
              <TableCell><Badge className="bg-white/10 border-0 text-[#A1E4DB] text-xs">{g.sellers_count}</Badge></TableCell>
              <TableCell><span className="text-sm metric-number text-white">{g.avg_price_sar} SAR</span></TableCell>
              <TableCell><span className="text-[10px] text-[#F59E0B] font-medium">{g.action}</span></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

export function PriceIntelTabContent({ tab, data, catalogGaps, isRTL, onOpen }) {
  switch (tab) {
    case "action": return <ActionRequiredTable rows={data.action_required} onOpen={onOpen} />;
    case "advantage": return <MyAdvantagesTable rows={data.my_advantages} onOpen={onOpen} />;
    case "full": return <FullComparisonTable rows={data.full_table} onOpen={onOpen} />;
    case "unverified": return <UnverifiedTable rows={data.unverified || []} onOpen={onOpen} isRTL={isRTL} />;
    case "gaps": return <CatalogGapsTable gaps={catalogGaps} isRTL={isRTL} />;
    default: return null;
  }
}
