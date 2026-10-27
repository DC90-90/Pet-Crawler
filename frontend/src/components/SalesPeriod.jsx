/**
 * The period behind a sales or movement figure, stated in full (client
 * request, 27 Oct 2026): the exact dates, how many complete days (Saudi
 * time), how many of them were measured, and what the figure rests on.
 *
 * Dates come from the server's window when it sends one; otherwise
 * `days` gives the last N complete KSA days, the same window the server uses
 * (ledger.sealed_ksa_window: ends at today's KSA midnight).
 */
import { CalendarDays } from "lucide-react";
import { useI18n } from "@/lib/i18n";

const KSA_OFFSET_MS = 3 * 3600 * 1000;

// [start, end) of the last `days` complete KSA days, as KSA calendar dates.
export function sealedWindow(days, now = new Date()) {
  const ksaNow = new Date(now.getTime() + KSA_OFFSET_MS);
  const end = new Date(Date.UTC(ksaNow.getUTCFullYear(), ksaNow.getUTCMonth(), ksaNow.getUTCDate()));
  const start = new Date(end.getTime() - days * 86400000);
  const last = new Date(end.getTime() - 86400000);
  return { from: start.toISOString().slice(0, 10), to: last.toISOString().slice(0, 10), days };
}

// A server window edge to a KSA calendar date ("2026-10-26").
function ksaDate(value, isEnd) {
  if (!value) return null;
  const s = String(value);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  const t = new Date(s.endsWith("Z") || /[+-]\d\d:?\d\d$/.test(s) ? s : s + "Z").getTime();
  if (Number.isNaN(t)) return null;
  // An exclusive end at KSA midnight belongs to the day before.
  return new Date(t + KSA_OFFSET_MS - (isEnd ? 1 : 0)).toISOString().slice(0, 10);
}

function show(d, isRTL) {
  return new Date(d + "T12:00:00Z").toLocaleDateString(isRTL ? "ar-SA" : "en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

export function SalesPeriod({ from, to, days, measured, expected, basis, label, className = "", testId = "sales-period" }) {
  const { isRTL } = useI18n();
  let a = ksaDate(from, false), b = ksaDate(to, true);
  if ((!a || !b) && days) ({ from: a, to: b } = sealedWindow(days));
  if (!a || !b) return null;
  const n = days || Math.round((new Date(b) - new Date(a)) / 86400000) + 1;
  const parts = [
    `${show(a, isRTL)} – ${show(b, isRTL)}`,
    isRTL ? `${n} يوماً مكتملاً (بتوقيت السعودية)` : `${n} complete days (Saudi time)`,
  ];
  if (measured != null && expected) parts.push(isRTL ? `قيست المبيعات في ${measured} من ${expected} يوماً` : `sales measured on ${measured} of ${expected} days`);
  if (basis) parts.push(basis);
  return (
    <p className={`inline-flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[#A1E4DB] ${className}`} data-testid={testId}>
      <CalendarDays className="w-3.5 h-3.5 text-[#6AC1B5] shrink-0" />
      <span className="font-semibold text-white">{label || (isRTL ? "فترة المبيعات:" : "Sales period:")}</span>
      {parts.map((p, i) => <span key={i}>{i > 0 && <span className="opacity-50 me-2">·</span>}{p}</span>)}
    </p>
  );
}
