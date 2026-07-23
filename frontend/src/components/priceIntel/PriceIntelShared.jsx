import { CheckCircle2, AlertCircle, Lock, Type, FileText, Fingerprint } from "lucide-react";

export const CONFIDENCE_LEVELS = [
  { min: 100, label: "Confirmed", labelAr: "مؤكد يدوياً", icon: CheckCircle2, color: "#10B981", bg: "bg-[#10B981]/15 text-[#10B981]", desc: "Manually verified by you — 100% reliable", descAr: "تم التحقق يدوياً — موثوق 100%" },
  { min: 99, label: "Barcode Match", labelAr: "مطابقة باركود", icon: Fingerprint, color: "#10B981", bg: "bg-[#10B981]/15 text-[#10B981]", desc: "Exact barcode/EAN match (8-14 digits) — highest automated confidence", descAr: "مطابقة باركود/EAN بالضبط — أعلى ثقة تلقائية" },
  { min: 95, label: "SKU Match", labelAr: "مطابقة SKU", icon: Lock, color: "#1E988E", bg: "bg-[#1E988E]/15 text-[#1E988E]", desc: "Exact SKU identifier match between stores", descAr: "مطابقة معرف SKU بالضبط بين المتاجر" },
  { min: 85, label: "Strong Name", labelAr: "اسم قوي", icon: Type, color: "#1E988E", bg: "bg-[#1E988E]/15 text-[#1E988E]", desc: "5+ name tokens match with weight/pack verification", descAr: "5+ كلمات مطابقة مع تحقق من الوزن والتعبئة" },
  { min: 80, label: "Good Name", labelAr: "اسم جيد", icon: Type, color: "#F59E0B", bg: "bg-[#F59E0B]/15 text-[#F59E0B]", desc: "4 name tokens match — review recommended", descAr: "4 كلمات مطابقة — يُنصح بالمراجعة" },
  { min: 75, label: "Baseline", labelAr: "بيانات أساسية", icon: FileText, color: "#F59E0B", bg: "bg-[#F59E0B]/15 text-[#F59E0B]", desc: "MySkuWatch snapshot — 17 Apr 2026 (historical, not live)", descAr: "لقطة MySkuWatch — 17 أبريل 2026 (تاريخية، غير محدثة)" },
  { min: 70, label: "Weak Name", labelAr: "اسم ضعيف", icon: AlertCircle, color: "#EF4444", bg: "bg-[#EF4444]/15 text-[#EF4444]", desc: "3 tokens match only — likely needs manual review", descAr: "3 كلمات فقط — يحتاج مراجعة يدوية غالباً" },
];

export function getConfLevel(confidence) {
  if (confidence === 100) return CONFIDENCE_LEVELS[0];
  for (const lvl of CONFIDENCE_LEVELS) {
    if (confidence >= lvl.min) return lvl;
  }
  return CONFIDENCE_LEVELS[CONFIDENCE_LEVELS.length - 1];
}

export function ConfidenceBadge({ confidence }) {
  const lvl = getConfLevel(confidence);
  const Icon = lvl.icon;
  return (
    <span className={`inline-flex items-center gap-1.5 text-[10px] font-semibold px-2.5 py-1 rounded-full ${lvl.bg}`} title={lvl.desc}>
      <Icon className="w-3 h-3" />
      {confidence}% {lvl.label}
    </span>
  );
}

export function FlagBadges({ flags }) {
  if (!flags || flags.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {flags.map((f) => (
        <span key={f} className={`text-[9px] font-bold px-1.5 py-0.5 rounded-full ${f === "SUSPICIOUS_PRICE" ? "bg-[#EF4444]/15 text-[#EF4444]" : f === "SIZE_MISMATCH" ? "bg-[#F59E0B]/15 text-[#F59E0B]" : "bg-white/10 text-[#A1E4DB]"}`}>{f.replace(/_/g, " ")}</span>
      ))}
    </div>
  );
}
