import { useState, useCallback } from "react";
import { ReferenceLine, ReferenceArea } from "recharts";
import SAUDI_SEASONAL_EVENTS from "@/config/seasonal_events";

export function useSeasonalEvents() {
  const [show, setShow] = useState(() => localStorage.getItem("daleel_seasonal") !== "off");
  const toggle = useCallback(() => {
    setShow((prev) => {
      const next = !prev;
      localStorage.setItem("daleel_seasonal", next ? "on" : "off");
      return next;
    });
  }, []);
  return { show, toggle };
}

export function SeasonalToggle({ show, toggle }) {
  return (
    <label className="flex items-center gap-1.5 text-[10px] text-[#4B5563] cursor-pointer select-none" data-testid="seasonal-toggle">
      <input type="checkbox" checked={show} onChange={toggle} className="w-3 h-3 rounded accent-[#002DF5]" />
      <span>Seasonal Events</span>
    </label>
  );
}

export function getSeasonalAnnotations(show, dateRange) {
  if (!show) return { lines: [], areas: [] };
  const lines = [];
  const areas = [];
  for (const ev of SAUDI_SEASONAL_EVENTS) {
    if (dateRange) {
      const evStart = new Date(ev.start);
      const rangeStart = new Date(dateRange[0]);
      const rangeEnd = new Date(dateRange[1]);
      if (evStart < rangeStart || evStart > rangeEnd) continue;
    }
    if (ev.start === ev.end) {
      lines.push(ev);
    } else {
      areas.push(ev);
      lines.push({ ...ev, label_only: true });
    }
  }
  return { lines, areas };
}

export function SeasonalChartElements({ show, dateRange }) {
  const { lines, areas } = getSeasonalAnnotations(show, dateRange);
  return (
    <>
      {areas.map((ev) => (
        <ReferenceArea key={`area-${ev.id}`} x1={ev.start} x2={ev.end} fill={ev.color} fillOpacity={0.08} />
      ))}
      {lines.map((ev) => (
        <ReferenceLine key={`line-${ev.id}`} x={ev.start} stroke={ev.color} strokeDasharray="4 3" strokeWidth={1.5}
          label={{ value: `${ev.name_ar}`, position: "top", fontSize: 8, fill: ev.color }} />
      ))}
    </>
  );
}
