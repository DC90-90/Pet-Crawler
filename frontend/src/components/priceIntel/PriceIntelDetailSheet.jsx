import { CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { ConfidenceBadge, FlagBadges } from "./PriceIntelShared";
import { SkuLine } from "@/components/SkuLine";

export function PriceIntelDetailSheet({ selectedSku, detail, onClose, onConfirm, onReject }) {
  return (
    <Sheet open={!!selectedSku} onOpenChange={(o) => { if (!o) onClose(); }}>
      <SheetContent className="w-[600px] sm:max-w-[600px] bg-[#0A2728] border-white/10 overflow-y-auto" data-testid="product-detail-sheet">
        <SheetHeader>
          <SheetTitle className="text-white text-lg">{detail?.my_product?.name_en || detail?.my_product?.name_ar || "Loading..."}</SheetTitle>
        </SheetHeader>
        {detail && (
          <div className="space-y-5 mt-4">
            {/* My Product Info */}
            <div className="glass-card p-4">
              <p className="text-[10px] uppercase text-[#A1E4DB] tracking-wider mb-2">My Product</p>
              <div className="flex items-center gap-3">
                {detail.my_product.image_url && <img src={detail.my_product.image_url} alt="" className="w-16 h-16 rounded-lg object-cover bg-white/5" />}
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-white font-medium">{detail.my_product.name_en}</p>
                  <p className="text-xs text-[#A1E4DB]">{detail.my_product.name_ar}</p>
                  <SkuLine sku={detail.my_product.sku} barcode={detail.my_product.barcode} size="sm" className="mt-0.5" />
                  <p className="text-lg font-bold text-[#1E988E] metric-number mt-1">{detail.market_summary.my_price} SAR</p>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 mt-3 text-xs">
                <div><span className="text-[#A1E4DB]">Lowest:</span> <span className="text-white font-semibold">{detail.market_summary.lowest_price} SAR</span></div>
                <div><span className="text-[#A1E4DB]">Highest:</span> <span className="text-white font-semibold">{detail.market_summary.highest_price} SAR</span></div>
                <div><span className="text-[#A1E4DB]">Sellers:</span> <span className="text-white font-semibold">{detail.market_summary.sellers_count}</span></div>
              </div>
            </div>

            {/* Competitors */}
            {detail.competitors.map((c) => (
              <div key={`${c.competitor_sku}-${c.competitor_store_id}`} className="glass-card p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-white font-medium">{c.competitor_store_name}</p>
                    <p className="text-[10px] text-[#A1E4DB]">{c.competitor_name}</p>
                    <SkuLine sku={c.competitor_sku} barcode={c.competitor_barcode} className="mt-0.5" />
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <ConfidenceBadge confidence={c.confidence} />
                    <FlagBadges flags={c.flags} />
                  </div>
                </div>
                <div className="flex items-center justify-between mb-3">
                  <span className="text-lg font-bold text-white metric-number">{c.competitor_price} SAR</span>
                  <span className={`text-sm font-semibold ${c.diff_pct > 0 ? "text-[#10B981]" : c.diff_pct < 0 ? "text-[#EF4444]" : "text-[#A1E4DB]"}`}>
                    {c.diff_pct > 0 ? "+" : ""}{c.diff_pct}% ({c.diff_sar > 0 ? "+" : ""}{c.diff_sar} SAR)
                  </span>
                  <Badge className={`text-[10px] border-0 ${c.competitor_in_stock ? "bg-[#10B981]/15 text-[#10B981]" : "bg-[#EF4444]/15 text-[#EF4444]"}`}>
                    {c.competitor_in_stock ? "In Stock" : "OOS"}
                  </Badge>
                </div>
                {c.price_history?.length > 1 && (
                  <div className="h-24 mt-2">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={c.price_history}>
                        <XAxis dataKey="date" hide />
                        <YAxis domain={["auto", "auto"]} hide />
                        <Tooltip contentStyle={{ background: "#104745", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, fontSize: 11 }} labelStyle={{ color: "#A1E4DB" }} />
                        <ReferenceLine y={detail.market_summary.my_price} stroke="#1E988E" strokeDasharray="3 3" strokeWidth={1} />
                        <Line type="monotone" dataKey="price" stroke="#F59E0B" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                    <p className="text-[9px] text-[#A1E4DB] text-center mt-0.5">Trend: <span className={`font-semibold ${c.price_trend === "rising" ? "text-[#EF4444]" : c.price_trend === "falling" ? "text-[#10B981]" : "text-[#A1E4DB]"}`}>{c.price_trend}</span></p>
                  </div>
                )}
                <div className="flex gap-2 mt-3 pt-3 border-t border-white/5">
                  <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); onConfirm(c); }}
                    className="text-[10px] text-[#10B981] hover:bg-[#10B981]/10 gap-1 h-7" data-testid={`confirm-${c.competitor_sku}`}>
                    <CheckCircle2 className="w-3 h-3" />Confirm
                  </Button>
                  <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); onReject(c); }}
                    className="text-[10px] text-[#EF4444] hover:bg-[#EF4444]/10 gap-1 h-7" data-testid={`reject-${c.competitor_sku}`}>
                    <XCircle className="w-3 h-3" />Reject
                  </Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
