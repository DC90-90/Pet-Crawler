/**
 * Tabs for the market lists (16 Oct 2026): by store (with its logo) and by
 * animal and product type. The facets come from the backend
 * (category_map.facets: the offer's store category and its name).
 */
import { useI18n } from "@/lib/i18n";
import { StoreLogo } from "@/components/StoreLogo";

const ANIMALS = [["cat", "Cats", "قطط"], ["dog", "Dogs", "كلاب"], ["bird", "Birds", "طيور"],
  ["fish", "Fish", "أسماك"], ["small_pet", "Small pets", "حيوانات صغيرة"], ["other", "Other", "أخرى"]];
const TYPES = [["dry_food", "Dry food", "طعام جاف"], ["wet_food", "Wet food", "طعام رطب"], ["treats", "Treats", "مكافآت"],
  ["litter", "Litter", "رمل"], ["health", "Health", "صحة"], ["grooming", "Grooming", "عناية"], ["toys", "Toys", "ألعاب"],
  ["housing", "Cages & beds", "أقفاص وأسرّة"], ["bowls", "Bowls", "أوعية"], ["collars", "Collars", "أطواق"],
  ["accessories", "Accessories", "إكسسوارات"], ["other", "Other", "أخرى"]];

export function facetCounts(rows) {
  const out = { animal: {}, type: {} };
  rows.forEach((r) => {
    const a = r.facet_animal || "other";
    const t = r.facet_type || "other";
    out.animal[a] = (out.animal[a] || 0) + 1;
    out.type[t] = (out.type[t] || 0) + 1;
  });
  return out;
}

export const facetMatch = (r, animal, ptype) =>
  (animal === "all" || (r.facet_animal || "other") === animal) && (ptype === "all" || (r.facet_type || "other") === ptype);

function Chip({ active, onClick, children, testId }) {
  return (
    <button onClick={onClick} data-testid={testId}
      className={`inline-flex items-center gap-1.5 px-2.5 h-7 rounded-full text-xs whitespace-nowrap transition-all ${active ? "bg-[#1E988E] text-[#090E1C] font-semibold" : "bg-white/5 text-[#A1E4DB] hover:text-white hover:bg-white/10"}`}>
      {children}
    </button>
  );
}

export function FacetTabs({ counts, animal, ptype, onAnimal, onType, prefix = "facet" }) {
  const { isRTL } = useI18n();
  const total = Object.values(counts?.animal || {}).reduce((a, b) => a + b, 0);
  const totalTypes = Object.values(counts?.type || {}).reduce((a, b) => a + b, 0);
  return (
    <div className="space-y-1.5" data-testid={`${prefix}-tabs`}>
      <div className="flex gap-1 overflow-x-auto pb-0.5">
        <Chip active={animal === "all"} onClick={() => onAnimal("all")} testId={`${prefix}-animal-all`}>{isRTL ? "كل الحيوانات" : "All animals"} <span className="opacity-70">{total}</span></Chip>
        {ANIMALS.filter(([id]) => counts?.animal?.[id]).map(([id, en, ar]) => (
          <Chip key={id} active={animal === id} onClick={() => onAnimal(id)} testId={`${prefix}-animal-${id}`}>{isRTL ? ar : en} <span className="opacity-70">{counts.animal[id]}</span></Chip>
        ))}
      </div>
      <div className="flex gap-1 overflow-x-auto pb-0.5">
        <Chip active={ptype === "all"} onClick={() => onType("all")} testId={`${prefix}-type-all`}>{isRTL ? "كل الأنواع" : "All types"} <span className="opacity-70">{totalTypes}</span></Chip>
        {TYPES.filter(([id]) => counts?.type?.[id]).map(([id, en, ar]) => (
          <Chip key={id} active={ptype === id} onClick={() => onType(id)} testId={`${prefix}-type-${id}`}>{isRTL ? ar : en} <span className="opacity-70">{counts.type[id]}</span></Chip>
        ))}
      </div>
    </div>
  );
}

export function StoreTabs({ stores, value, onChange, prefix = "store" }) {
  const { isRTL } = useI18n();
  const total = stores.reduce((a, s) => a + (s.count || 0), 0);
  return (
    <div className="flex gap-1 overflow-x-auto pb-0.5" data-testid={`${prefix}-tabs`}>
      <Chip active={value === "all"} onClick={() => onChange("all")} testId={`${prefix}-tab-all`}>{isRTL ? "كل المتاجر" : "All stores"} <span className="opacity-70">{total}</span></Chip>
      {stores.map((s) => (
        <Chip key={s.id} active={value === s.id} onClick={() => onChange(s.id)} testId={`${prefix}-tab-${s.id}`}>
          <StoreLogo storeId={s.id} name={s.name} size={16} />{s.name} <span className="opacity-70">{s.count}</span>
        </Chip>
      ))}
    </div>
  );
}

export function storesOf(rows) {
  const by = {};
  rows.forEach((r) => {
    if (!r.store_id) return;
    by[r.store_id] = by[r.store_id] || { id: r.store_id, name: r.store_name || r.store_id, count: 0 };
    by[r.store_id].count += 1;
  });
  return Object.values(by).sort((a, b) => b.count - a.count);
}
