import { Star } from "lucide-react";
import { useIsMyProduct } from "@/lib/mySkus";
import { useI18n } from "@/lib/i18n";

/** Tiny "MINE" badge shown next to a product when it belongs to the user's catalog. */
export function MineBadge({ sku, className = "", forceShow = false }) {
  const isMine = useIsMyProduct(sku);
  const { isRTL } = useI18n();
  if (!isMine && !forceShow) return null;
  return (
    <span
      data-testid={`mine-badge-${sku || "x"}`}
      title={isRTL ? "منتج في متجرك" : "Product in your store"}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-[#1E988E]/15 text-[#1E988E] border border-[#1E988E]/30 text-[9px] font-bold tracking-[0.1em] uppercase ${className}`}
    >
      <Star className="w-2.5 h-2.5 fill-[#1E988E]" />
      {isRTL ? "متجري" : "MINE"}
    </span>
  );
}

/** Returns extra row classes when the product belongs to the user. Use on <TableRow> */
export function useMyRowClass(sku) {
  const isMine = useIsMyProduct(sku);
  return isMine ? "bg-[#1E988E]/[0.06] border-s-2 border-s-[#1E988E]" : "";
}
