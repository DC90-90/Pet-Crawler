/**
 * CardPeriod — iter73j (Aug 3 2026).
 *
 * A small, consistent subheader shown under every Insights card title that
 * tells the operator WHAT PERIOD the numbers in the card were measured over.
 *
 * Two modes:
 *   • window={days} — the card queries a sliding N-day window from today.
 *     Renders "Last N days" (localized). If dateFrom/dateTo are set, that
 *     custom range replaces the sliding window ("Jul 5 → Aug 3").
 *   • window="current" — the card is a point-in-time snapshot of the latest
 *     crawled state (Data Freshness, Gaps, Price Wars, Restock). Renders
 *     "Current snapshot".
 *
 * Styling is intentionally muted (10px, dimmed) so it never competes with
 * the card title. Placement: directly under the card <h3>. Every instance
 * carries a stable data-testid so tests can assert period presence.
 */
import { useI18n } from "@/lib/i18n";

function fmtDate(iso, isRTL) {
  if (!iso) return iso;
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleDateString(isRTL ? "ar-SA" : "en-GB", {
      day: "numeric",
      month: "short",
      year: undefined,
    });
  } catch (_e) {
    return iso;
  }
}

export function CardPeriod({ window, dateFrom, dateTo, testId }) {
  const { t, isRTL } = useI18n();

  let label = "";
  if (window === "current") {
    label = t("period_current");
  } else if (dateFrom && dateTo) {
    label = t("period_custom_range")
      .replace("{from}", fmtDate(dateFrom, isRTL))
      .replace("{to}", fmtDate(dateTo, isRTL));
  } else if (typeof window === "number" && window > 0) {
    label = t("period_last_days").replace("{n}", String(window));
  } else {
    return null;
  }

  return (
    <p
      className="text-[10px] tracking-[0.1em] text-[#A1E4DB] opacity-60 -mt-2 mb-3 uppercase"
      data-testid={testId || "card-period"}
    >
      {label}
    </p>
  );
}

export default CardPeriod;
