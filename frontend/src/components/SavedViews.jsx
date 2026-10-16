/**
 * Saved views (16 Oct 2026): name the current filters and sort of a page and
 * come back to them with one click. Stored per user (/saved-filters), tagged
 * with the page they belong to.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Bookmark, Trash2, Plus } from "lucide-react";
import api from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function SavedViews({ page, current, onApply }) {
  const { isRTL } = useI18n();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["saved-filters"], queryFn: async () => (await api.get("/saved-filters")).data, staleTime: 60000 });
  const views = (q.data || []).filter((v) => v.filters?.page === page);

  const save = async () => {
    const label = name.trim();
    if (!label) return;
    try {
      await api.post("/saved-filters", { name: label, filters: { ...current, page } });
      setName("");
      qc.invalidateQueries({ queryKey: ["saved-filters"] });
      toast.success(isRTL ? "تم حفظ العرض" : "View saved");
    } catch { toast.error(isRTL ? "تعذر حفظ العرض" : "Could not save the view"); }
  };
  const remove = async (id) => {
    try {
      await api.delete(`/saved-filters/${id}`);
      qc.invalidateQueries({ queryKey: ["saved-filters"] });
    } catch { toast.error(isRTL ? "تعذر الحذف" : "Could not delete"); }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="h-8 px-3 rounded-xl text-xs inline-flex items-center gap-1.5 bg-white/5 border border-white/10 text-white hover:bg-white/10" data-testid="saved-views-btn">
          <Bookmark className="w-3.5 h-3.5" />{isRTL ? "العروض المحفوظة" : "Saved views"}{views.length > 0 && <span className="text-[#A1E4DB]">({views.length})</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-3 bg-[#104745] border-white/10 text-white space-y-2" align="start">
        {views.length === 0 ? (
          <p className="text-[11px] text-[#A1E4DB]">{isRTL ? "لا توجد عروض محفوظة بعد." : "No saved views yet."}</p>
        ) : (
          <div className="space-y-1 max-h-56 overflow-y-auto" data-testid="saved-views-list">
            {views.map((v) => (
              <div key={v.id} className="flex items-center justify-between gap-2 rounded px-2 py-1 hover:bg-white/5">
                <button className="text-xs text-start flex-1 truncate" onClick={() => { onApply(v.filters); setOpen(false); }}>{v.name}</button>
                <button className="text-[#A1E4DB] hover:text-red-300" onClick={() => remove(v.id)} aria-label="delete"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-1.5 pt-2 border-t border-white/10">
          <input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && save()} maxLength={60}
            placeholder={isRTL ? "اسم العرض الحالي" : "Name the current view"} data-testid="saved-views-name"
            className="flex-1 h-7 px-2 text-xs rounded bg-[#0A2728] border border-[#13625F] text-white placeholder:text-[#A1E4DB]/50" />
          <button onClick={save} className="h-7 px-2 rounded bg-[#1E988E] text-[#090E1C] text-xs inline-flex items-center gap-1" data-testid="saved-views-save">
            <Plus className="w-3.5 h-3.5" />{isRTL ? "حفظ" : "Save"}
          </button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
