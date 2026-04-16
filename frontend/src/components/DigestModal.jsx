import { useEffect, useState } from "react";
import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { RefreshCw } from "lucide-react";

export default function DigestModal({ open, onClose }) {
  const [digest, setDigest] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api.get("/digests/latest").then((r) => setDigest(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, [open]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const r = await api.post("/digests/generate");
      setDigest(r.data);
    } catch {}
    finally { setGenerating(false); }
  };

  const c = digest?.content || {};
  const ms = c.market_summary || {};

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="sm:max-w-2xl max-h-[80vh] overflow-y-auto rounded-md" data-testid="digest-modal">
        <DialogHeader>
          <DialogTitle className="font-bold text-lg">Market Intelligence Digest</DialogTitle>
          {digest?.week_start && (
            <DialogDescription>
              Generated: {new Date(digest.generated_at).toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "long", year: "numeric" })} | Week of {digest.week_start} to {digest.week_end}
            </DialogDescription>
          )}
        </DialogHeader>

        {loading ? <p className="text-sm text-[#9CA3AF] py-4">Loading...</p> : !digest?.content ? (
          <div className="text-center py-8">
            <p className="text-sm text-[#9CA3AF] mb-3">No digest generated yet</p>
            <Button size="sm" onClick={handleGenerate} disabled={generating} className="bg-[#002DF5] text-white rounded-md text-xs" data-testid="generate-digest-btn">
              <RefreshCw className={`w-3 h-3 me-1 ${generating ? "animate-spin" : ""}`} />Generate Now
            </Button>
          </div>
        ) : (
          <div className="space-y-5 py-2">
            {/* Market Summary */}
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: "SKUs Tracked", val: ms.total_skus },
                { label: "Price Drops", val: ms.total_price_drops },
                { label: "New Products", val: ms.total_new_products },
                { label: "OOS Events", val: ms.total_oos_events },
                { label: "Most Active", val: ms.most_active_store },
                { label: "Snapshots", val: ms.snapshots_this_week },
              ].map((k) => (
                <div key={k.label} className="bg-[#F9FAFB] rounded-md p-2.5">
                  <p className="text-[9px] uppercase tracking-wider text-[#9CA3AF]">{k.label}</p>
                  <p className="text-sm font-bold text-[#0A0A0A] mt-0.5">{k.val ?? "-"}</p>
                </div>
              ))}
            </div>

            {/* Price Drops */}
            <Section title="Top Price Drops" items={c.top_price_drops} renderItem={(d) => (
              <div className="flex items-center justify-between">
                <div><p className="text-xs font-medium">{d.name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{d.store_name}</p></div>
                <div className="text-end"><span className="text-xs line-through text-[#9CA3AF]">{d.old_price} ﷼</span> <span className="text-xs font-bold text-green-600">{d.new_price} ﷼</span><Badge variant="outline" className="text-[9px] ms-1.5 bg-green-50 text-green-700 border-green-200">-{d.drop_pct}%</Badge></div>
              </div>
            )} />

            {/* New Products */}
            <Section title="New Products Spotted" items={c.new_products} renderItem={(p) => (
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium">{p.name_ar}</p>
                <Badge variant="secondary" className="text-[10px]">{p.category}</Badge>
              </div>
            )} />

            {/* OOS Events */}
            <Section title="Competitor Out-of-Stock" items={c.oos_events} renderItem={(e) => (
              <div className="flex items-center justify-between">
                <div><p className="text-xs font-medium">{e.name_ar}</p><p className="text-[10px] text-[#9CA3AF]">{e.store_name}</p></div>
                <Badge variant="outline" className="text-[9px] bg-red-50 text-red-600 border-red-200">OOS</Badge>
              </div>
            )} />

            <div className="flex justify-end">
              <Button size="sm" variant="outline" onClick={handleGenerate} disabled={generating} className="rounded-md text-xs" data-testid="regen-digest-btn">
                <RefreshCw className={`w-3 h-3 me-1 ${generating ? "animate-spin" : ""}`} />Regenerate
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, items, renderItem }) {
  if (!items || items.length === 0) return null;
  return (
    <div>
      <h4 className="text-xs font-semibold text-[#0A0A0A] mb-2">{title}</h4>
      <div className="space-y-2 border border-[#E5E7EB] rounded-md divide-y divide-[#F3F4F6]">
        {items.map((item, i) => <div key={i} className="px-3 py-2">{renderItem(item)}</div>)}
      </div>
    </div>
  );
}
