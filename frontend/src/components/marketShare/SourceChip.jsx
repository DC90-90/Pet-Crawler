import { Badge } from "@/components/ui/badge";
import { ShieldCheck, Activity, MinusCircle, HelpCircle, Receipt } from "lucide-react";

// Every number on the Market Share tab declares where it came from. The label
// wording is the client's: Actual / Estimated / Unavailable — with
// "Measured (approx.)" for the counter and stock-depletion diffs, which are
// real observations but not exact unit counts.
export const SOURCE_META = {
  orders_exact: {
    label: "Actual", icon: Receipt,
    cls: "bg-[#10B981]/12 text-[#10B981] border-[#10B981]/25",
    tip: "My own Zid orders ledger — real invoices",
  },
  sold_counter_diff: {
    label: "Counter proxy", icon: Activity,
    cls: "bg-[#1E988E]/12 text-[#5FD3C7] border-[#1E988E]/25",
    tip: "Difference between two crawls of the store's published units-sold counter. The platform buckets and caps that badge, so it approximates real sales",
  },
  stock_depletion: {
    label: "Inventory proxy", icon: Activity,
    cls: "bg-[#1E988E]/12 text-[#5FD3C7] border-[#1E988E]/25",
    tip: "Observed inventory depletion, not verified sales. Restocks, adjustments, transfers, and missed observations can change this signal",
  },
  measured_zero: {
    label: "No observed movement", icon: MinusCircle,
    cls: "bg-white/5 text-[#A1E4DB] border-white/15",
    tip: "Repeated valid observations showed no movement; this does not prove zero sales",
  },
  unavailable: {
    label: "Unavailable", icon: HelpCircle,
    cls: "bg-[#F59E0B]/12 text-[#F59E0B] border-[#F59E0B]/25",
    tip: "No sales signal for this seller in this window — the number is withheld, not zeroed",
  },
};

export const REASON_TEXT = {
  store_publishes_no_sales_signal: "This store publishes neither a sold counter nor stock levels",
  fewer_than_two_crawls_in_window: "Only one crawl in this window — a change needs two",
  no_seller_in_this_market_has_sales_data: "No seller of this product publishes sales data",
  store_not_crawled_in_window: "Store was not crawled in this window",
};

const CONF_META = {
  high: { label: "High", cls: "bg-[#10B981]/12 text-[#10B981] border-[#10B981]/25" },
  medium: { label: "Medium", cls: "bg-[#1E988E]/12 text-[#5FD3C7] border-[#1E988E]/25" },
  low: { label: "Low", cls: "bg-[#F59E0B]/12 text-[#F59E0B] border-[#F59E0B]/25" },
  unavailable: { label: "Unavailable", cls: "bg-white/5 text-[#A1E4DB] border-white/15" },
};

export function SourceChip({ source, compact = false, testId }) {
  const m = SOURCE_META[source] || SOURCE_META.unavailable;
  const Icon = m.icon;
  return (
    <span title={m.tip} data-testid={testId}
      className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[9px] uppercase tracking-wide ${m.cls}`}>
      <Icon className="w-2.5 h-2.5" />
      {compact ? m.label.replace(" (approx.)", "~") : m.label}
    </span>
  );
}

export function ConfidenceBadge({ level, reason, testId }) {
  const m = CONF_META[level] || CONF_META.unavailable;
  return (
    <Badge title={reason || undefined} data-testid={testId}
      className={`text-[9px] uppercase tracking-wide border ${m.cls}`}>
      <ShieldCheck className="w-2.5 h-2.5 me-1" />{m.label}
    </Badge>
  );
}

export const fmtNum = (v, dash = "—") =>
  v === null || v === undefined ? dash : Number(v).toLocaleString("en-US");

export const fmtMoney = (v, dash = "—") =>
  v === null || v === undefined ? dash
    : `${Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ﷼`;

export const fmtPct = (v, dash = "—") =>
  v === null || v === undefined ? dash : `${Number(v).toFixed(1)}%`;

export function Unavailable({ reason }) {
  return (
    <span className="text-[11px] text-[#F59E0B]" title={REASON_TEXT[reason] || reason}>
      Unavailable
    </span>
  );
}

export function TrendCell({ pct }) {
  if (pct === null || pct === undefined) return <span className="text-[11px] text-[#A1E4DB]">—</span>;
  const up = pct >= 0;
  return (
    <span className={`text-[11px] font-medium ${up ? "text-[#10B981]" : "text-[#EF4444]"}`} dir="ltr">
      {up ? "▲" : "▼"} {Math.abs(pct).toFixed(1)}%
    </span>
  );
}
