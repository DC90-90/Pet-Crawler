/**
 * DataTable (27 Oct 2026) — the client asked for a filter on every column of
 * the Market tables and to see all the data. One table for all of them:
 *   • a filter under every header: text contains, number min–max, or a list;
 *   • sort by any column (click the header);
 *   • a Columns menu to show or hide any column (more columns than before:
 *     every field the rows carry), and drag a header edge to resize;
 *   • full text, wrapped — nothing cut with "…";
 *   • "N of M rows", Clear filters, Export (filtered rows, visible columns).
 * Layout (visible columns, widths) is remembered per table in this browser.
 *
 * Client mode: pass every row; filtering, sorting and paging happen here.
 * Server mode (onQuery): the page asks the server with {colf, sort_by,
 * sort_dir} — the same filter grammar (backend/table_query.py) — and passes
 * the returned rows and total; fetchAll(query) feeds Export.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Columns3, Download, FilterX, ChevronUp, ChevronDown, ArrowUpDown } from "lucide-react";
import { useI18n } from "@/lib/i18n";

const PAGE = 100;

function load(key, fallback) {
  try { const v = JSON.parse(localStorage.getItem(key)); return v ?? fallback; } catch { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode: keep in memory only */ }
}

// Same rules as backend/table_query.py, for client mode.
function valuesOf(col, row) {
  const v = col.get ? col.get(row) : row[col.id];
  if (v == null || v === "") return [];
  return Array.isArray(v) ? v.filter((x) => x != null && x !== "") : [v];
}
function passes(vals, rule) {
  if (!rule) return true;
  const q = String(rule.q || "").trim().toLowerCase();
  if (q && !vals.some((v) => String(v).toLowerCase().includes(q))) return false;
  if (rule.in && rule.in.length && !vals.some((v) => rule.in.map((x) => String(x).toLowerCase()).includes(String(v).toLowerCase()))) return false;
  const lo = rule.min === "" || rule.min == null ? null : Number(rule.min);
  const hi = rule.max === "" || rule.max == null ? null : Number(rule.max);
  if (lo != null || hi != null) {
    const nums = vals.map(Number).filter((n) => !Number.isNaN(n));
    if (!nums.some((n) => (lo == null || n >= lo) && (hi == null || n <= hi))) return false;
  }
  return true;
}
function isActive(rule) {
  return rule && ((rule.q && String(rule.q).trim()) || (rule.in && rule.in.length) || (rule.min !== "" && rule.min != null) || (rule.max !== "" && rule.max != null));
}
function csvCell(v) {
  const s = Array.isArray(v) ? v.join(" | ") : v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function FilterInput({ col, rule, onChange, isRTL }) {
  const base = "w-full h-7 px-2 rounded-md bg-[#090E1C] border border-white/10 text-white text-xs placeholder:text-[#A1E4DB]/50 focus:outline-none focus:border-[#1E988E]";
  if (col.filter === false) return null;
  if (col.type === "number") {
    return (
      <div className="flex gap-1">
        <input type="number" inputMode="decimal" className={base} placeholder={isRTL ? "من" : "min"} value={rule?.min ?? ""}
          onChange={(e) => onChange({ ...rule, min: e.target.value })} aria-label={`${col.label} min`} />
        <input type="number" inputMode="decimal" className={base} placeholder={isRTL ? "إلى" : "max"} value={rule?.max ?? ""}
          onChange={(e) => onChange({ ...rule, max: e.target.value })} aria-label={`${col.label} max`} />
      </div>
    );
  }
  if (col.type === "enum") {
    return (
      <select className={base} value={rule?.in?.[0] ?? ""} aria-label={col.label}
        onChange={(e) => onChange(e.target.value ? { in: [e.target.value] } : null)}>
        <option value="" className="bg-[#0B1220]">{isRTL ? "الكل" : "All"}</option>
        {(col.options || []).map((o) => {
          const [v, l] = Array.isArray(o) ? o : [o, o];
          return <option key={v} value={v} className="bg-[#0B1220]">{l}</option>;
        })}
      </select>
    );
  }
  return <input className={base} placeholder={isRTL ? "يحتوي على…" : "contains…"} value={rule?.q ?? ""}
    onChange={(e) => onChange(e.target.value ? { q: e.target.value } : null)} aria-label={col.label} />;
}

export default function DataTable({
  columns, rows, storageKey, exportName = "daleel", onRowClick, rowKey, initialSort,
  // server mode
  onQuery, total: serverTotal, allTotal, loading, fetchAll, emptyText,
}) {
  const { isRTL } = useI18n();
  const server = typeof onQuery === "function";
  const defaults = columns.filter((c) => !c.hidden).map((c) => c.id);
  const [visible, setVisible] = useState(() => {
    const saved = load(`dt:${storageKey}:cols`, null);
    return Array.isArray(saved) ? saved.filter((id) => columns.some((c) => c.id === id)) : defaults;
  });
  const [widths, setWidths] = useState(() => load(`dt:${storageKey}:w`, {}));
  const [filters, setFilters] = useState({});
  const [debounced, setDebounced] = useState({});
  const [sort, setSort] = useState(initialSort || null);
  const [shown, setShown] = useState(PAGE);
  const [menu, setMenu] = useState(false);
  const [exporting, setExporting] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => { save(`dt:${storageKey}:cols`, visible); }, [visible, storageKey]);
  useEffect(() => { save(`dt:${storageKey}:w`, widths); }, [widths, storageKey]);
  useEffect(() => { const t = setTimeout(() => setDebounced(filters), 400); return () => clearTimeout(t); }, [filters]);
  useEffect(() => {
    const close = (e) => { if (menuRef.current && !menuRef.current.contains(e.target)) setMenu(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const byId = useMemo(() => Object.fromEntries(columns.map((c) => [c.id, c])), [columns]);
  const cols = visible.map((id) => byId[id]).filter(Boolean);
  const activeFilters = Object.fromEntries(Object.entries(debounced).filter(([, r]) => isActive(r)));
  const query = useMemo(() => {
    const colf = {};
    for (const [id, rule] of Object.entries(activeFilters)) colf[byId[id]?.field || id] = rule;
    return { colf: Object.keys(colf).length ? JSON.stringify(colf) : undefined,
             sort_by: sort ? (byId[sort.id]?.field || sort.id) : undefined, sort_dir: sort?.dir };
  }, [JSON.stringify(activeFilters), sort, byId]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { if (server) onQuery(query); setShown(PAGE); }, [query]);   // eslint-disable-line react-hooks/exhaustive-deps

  const view = useMemo(() => {
    if (server) return rows || [];
    let out = (rows || []).filter((r) => Object.entries(activeFilters).every(([id, rule]) => byId[id] && passes(valuesOf(byId[id], r), rule)));
    if (sort && byId[sort.id]) {
      const col = byId[sort.id];
      const first = (r) => valuesOf(col, r)[0];
      const filled = out.filter((r) => first(r) != null);
      const blank = out.filter((r) => first(r) == null);
      const numeric = filled.every((r) => !Number.isNaN(Number(first(r))));
      filled.sort((a, b) => {
        const x = first(a), y = first(b);
        const c = numeric ? Number(x) - Number(y) : String(x).localeCompare(String(y), isRTL ? "ar" : "en");
        return sort.dir === "desc" ? -c : c;
      });
      out = [...filled, ...blank];
    }
    return out;
  }, [rows, server, JSON.stringify(activeFilters), sort, byId, isRTL]);   // eslint-disable-line react-hooks/exhaustive-deps

  const total = server ? (allTotal ?? serverTotal ?? view.length) : (rows || []).length;
  const matched = server ? (serverTotal ?? view.length) : view.length;
  const nActive = Object.keys(activeFilters).length;

  const toggleSort = (id) => setSort((s) => (!s || s.id !== id ? { id, dir: byId[id]?.type === "text" ? "asc" : "desc" }
    : s.dir === "desc" ? { id, dir: "asc" } : s.dir === "asc" && byId[id]?.type !== "text" ? null : { id, dir: "desc" }));

  const startResize = (e, id) => {
    e.preventDefault(); e.stopPropagation();
    const th = e.currentTarget.parentElement;
    const startX = e.clientX, startW = th.getBoundingClientRect().width;
    const move = (ev) => setWidths((w) => ({ ...w, [id]: Math.max(70, Math.round(startW + (isRTL ? startX - ev.clientX : ev.clientX - startX))) }));
    const up = () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
    window.addEventListener("mousemove", move); window.addEventListener("mouseup", up);
  };

  const exportCsv = async () => {
    setExporting(true);
    try {
      const all = server && fetchAll ? await fetchAll(query) : view;
      const head = cols.map((c) => csvCell(c.label)).join(",");
      const body = all.map((r) => cols.map((c) => csvCell(c.exportValue ? c.exportValue(r) : (c.get ? c.get(r) : r[c.id]))).join(","));
      const blob = new Blob(["﻿" + [head, ...body].join("\n")], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${exportName}-${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(a.href);
    } finally { setExporting(false); }
  };

  const btn = "h-8 px-3 rounded-lg text-xs inline-flex items-center gap-1.5 bg-white/5 text-[#A1E4DB] hover:text-white";
  return (
    <div className="space-y-2" data-testid={`dt-${storageKey}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm text-[#A1E4DB]" data-testid={`dt-${storageKey}-count`}>
          {isRTL ? `${matched.toLocaleString()} من ${total.toLocaleString()} صف` : `${matched.toLocaleString()} of ${total.toLocaleString()} rows`}
          {nActive > 0 && <span className="text-[#F59E0B]">{isRTL ? ` · ${nActive} عامل تصفية` : ` · ${nActive} filter${nActive > 1 ? "s" : ""}`}</span>}
        </p>
        <div className="ms-auto flex flex-wrap items-center gap-2">
          {nActive > 0 && <button className={btn} onClick={() => { setFilters({}); setDebounced({}); }} data-testid={`dt-${storageKey}-clear`}>
            <FilterX className="w-3.5 h-3.5" />{isRTL ? "مسح التصفية" : "Clear filters"}</button>}
          <div className="relative" ref={menuRef}>
            <button className={btn} onClick={() => setMenu((m) => !m)} data-testid={`dt-${storageKey}-columns`}>
              <Columns3 className="w-3.5 h-3.5" />{isRTL ? `الأعمدة (${cols.length}/${columns.length})` : `Columns (${cols.length}/${columns.length})`}</button>
            {menu && (
              <div className="absolute end-0 mt-1 z-30 w-64 max-h-96 overflow-auto rounded-lg border border-white/10 bg-[#0A2728] p-2 shadow-xl">
                {columns.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/5 text-sm text-white cursor-pointer">
                    <input type="checkbox" checked={visible.includes(c.id)} disabled={c.always}
                      onChange={(e) => setVisible((v) => e.target.checked ? columns.filter((x) => v.includes(x.id) || x.id === c.id).map((x) => x.id) : v.filter((x) => x !== c.id))} />
                    {c.label}
                  </label>
                ))}
                <div className="flex gap-2 border-t border-white/10 mt-2 pt-2">
                  <button className="text-xs text-[#6AC1B5] hover:text-white" onClick={() => setVisible(columns.map((c) => c.id))}>{isRTL ? "إظهار الكل" : "Show all"}</button>
                  <button className="text-xs text-[#6AC1B5] hover:text-white" onClick={() => { setVisible(defaults); setWidths({}); }}>{isRTL ? "الافتراضي" : "Reset"}</button>
                </div>
              </div>
            )}
          </div>
          <button className={btn} onClick={exportCsv} disabled={exporting} data-testid={`dt-${storageKey}-export`}>
            <Download className="w-3.5 h-3.5" />{exporting ? "…" : (isRTL ? "تصدير" : "Export")}</button>
        </div>
      </div>

      <div className="glass-card overflow-x-auto">
        <table className="dt-table w-full text-sm" style={{ tableLayout: "fixed", minWidth: cols.reduce((n, c) => n + (widths[c.id] || c.width || 140), 0) }}>
          <colgroup>{cols.map((c) => <col key={c.id} style={{ width: widths[c.id] || c.width || 140 }} />)}</colgroup>
          <thead>
            <tr>
              {cols.map((c) => (
                <th key={c.id} className={`relative select-none ${c.align === "end" ? "text-end" : "text-start"}`}>
                  <button className="inline-flex items-center gap-1 hover:text-white text-start" onClick={() => toggleSort(c.id)} title={c.tip || c.label}>
                    {c.label}
                    {sort?.id === c.id ? (sort.dir === "desc" ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />) : <ArrowUpDown className="w-3 h-3 opacity-30" />}
                  </button>
                  <span onMouseDown={(e) => startResize(e, c.id)} className="absolute top-0 end-0 h-full w-1.5 cursor-col-resize hover:bg-[#1E988E]/60" aria-hidden />
                </th>
              ))}
            </tr>
            <tr data-testid={`dt-${storageKey}-filters`}>
              {cols.map((c) => (
                <th key={c.id} className="!py-1.5 !static">
                  <FilterInput col={c} rule={filters[c.id]} isRTL={isRTL}
                    onChange={(rule) => setFilters((f) => { const n = { ...f }; if (isActive(rule)) n[c.id] = rule; else delete n[c.id]; return n; })} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={cols.length} className="text-center text-[#A1E4DB] py-6">{isRTL ? "جارٍ التحميل…" : "Loading…"}</td></tr>}
            {!loading && view.length === 0 && <tr><td colSpan={cols.length} className="text-center text-[#A1E4DB] py-6">{emptyText || (isRTL ? "لا شيء يطابق هذه التصفية" : "Nothing matches these filters")}</td></tr>}
            {!loading && view.slice(0, server ? view.length : shown).map((r, i) => (
              <tr key={rowKey ? rowKey(r) : i} onClick={onRowClick ? () => onRowClick(r) : undefined} className={onRowClick ? "cursor-pointer" : ""}>
                {cols.map((c) => (
                  <td key={c.id} className={`align-top whitespace-normal break-words ${c.align === "end" ? "text-end" : ""}`}>
                    {c.render ? c.render(r) : (() => { const v = c.get ? c.get(r) : r[c.id]; return v == null || v === "" ? <span className="text-[#A1E4DB]/60">—</span> : Array.isArray(v) ? v.join(", ") : String(v); })()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!server && view.length > shown && (
        <button className="text-sm text-[#6AC1B5] hover:text-white" onClick={() => setShown((n) => n + PAGE)}>
          {isRTL ? `عرض المزيد (${(view.length - shown).toLocaleString()})` : `Show more (${(view.length - shown).toLocaleString()})`}</button>
      )}
    </div>
  );
}
