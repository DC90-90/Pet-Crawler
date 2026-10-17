/**
 * Promotions calendar (17 Oct 2026): for each store, the share of its products
 * on sale each day (one cell per day, darker = more on sale), its usual level,
 * average depth, and the campaigns detected above that usual level.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { RequestError } from "@/components/RequestError";
import { StoreLogo } from "@/components/StoreLogo";

const cellColor = (share) => {
  if (share == null) return "rgba(255,255,255,0.04)";
  const a = Math.min(1, share / 50);
  return `rgba(239, 68, 68, ${0.08 + a * 0.85})`;
};

export default function PromotionsCalendar() {
  const { isRTL } = useI18n();
  const [days, setDays] = useState(90);
  const q = useQuery({ queryKey: ["promotions", days], queryFn: async () => (await api.get("/promotions/calendar", { params: { days }, timeout: 90000 })).data });
  if (q.isError) return <RequestError id="promotions-request" error={q.error} onRetry={() => q.refetch()} />;
  const stores = q.data?.stores || [];
  const allDates = [...new Set(stores.flatMap((s) => s.daily.map((d) => d.date)))].sort();

  return (
    <div className="glass-card rounded-md p-5 space-y-4" data-testid="promotions-calendar">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-[#A1E4DB] max-w-2xl">
          {isRTL ? "نسبة منتجات كل متجر المخفّضة يومياً (الأغمق = تخفيضات أكثر)، ومستواه المعتاد، ومتوسط عمق الخصم، والحملات التي تجاوزت مستواه المعتاد بوضوح."
            : "The share of each store's products on sale each day (darker = more on sale), its usual level, average discount depth, and campaigns clearly above its usual level."}
        </p>
        <div className="flex gap-1">
          {[30, 60, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} className={`text-xs rounded-full h-7 px-3 ${days === d ? "bg-[#1E988E] text-[#090E1C]" : "text-[#A1E4DB] hover:bg-white/5"}`}>{d}D</button>
          ))}
        </div>
      </div>
      {q.isLoading ? <p className="text-xs text-[#A1E4DB]">…</p> : (
        <div className="space-y-4">
          {stores.map((s) => {
            const byDate = Object.fromEntries(s.daily.map((d) => [d.date, d]));
            return (
              <div key={s.store_id} data-testid={`promo-store-${s.store_id}`}>
                <div className="flex flex-wrap items-baseline gap-3 mb-1">
                  <span className="inline-flex items-center gap-1.5 text-sm text-white font-medium"><StoreLogo storeId={s.store_id} name={s.name} size={18} />{s.name}</span>
                  <span className="text-[11px] text-[#A1E4DB]">{isRTL ? `عادةً ${s.usual_share_pct ?? "—"}% من المنتجات مخفّضة` : `usually ${s.usual_share_pct ?? "—"}% of products on sale`}</span>
                  <span className="text-[11px] text-[#A1E4DB]">{isRTL ? `متوسط الخصم ${s.avg_discount_pct ?? "—"}%` : `average discount ${s.avg_discount_pct ?? "—"}%`}</span>
                </div>
                <div className="flex gap-[2px] overflow-x-auto">
                  {allDates.map((date) => {
                    const d = byDate[date];
                    return <div key={date} className="w-2.5 h-6 shrink-0 rounded-[2px]" style={{ background: cellColor(d && d.read >= 50 ? d.share_pct : null) }}
                      title={d ? `${date}: ${d.on_sale}/${d.read} on sale (${d.share_pct}%)${d.avg_discount_pct ? `, avg -${d.avg_discount_pct}%` : ""}` : `${date}: no reading`} />;
                  })}
                </div>
                {s.campaigns.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-1.5">
                    {s.campaigns.map((c) => (
                      <span key={c.start} className="text-[10px] px-2 py-0.5 rounded-full bg-[#EF4444]/15 text-[#FCA5A5] border border-[#EF4444]/30">
                        {c.start === c.end ? c.start : `${c.start} → ${c.end}`} · {isRTL ? `${c.length_days} يوم` : `${c.length_days}d`} · {isRTL ? `ذروة ${c.peak_share_pct}%` : `peak ${c.peak_share_pct}%`} · -{c.avg_discount_pct}%
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {allDates.length > 0 && <p className="text-[10px] text-[#A1E4DB]/70">{allDates[0]} → {allDates[allDates.length - 1]}</p>}
        </div>
      )}
    </div>
  );
}
