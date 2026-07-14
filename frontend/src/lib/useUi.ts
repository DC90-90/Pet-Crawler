import { useCallback, useEffect, useState } from "react";

type Mode = "light" | "dark";

const THEME_KEY = "svaneti-theme";

function applyTheme(mode: Mode) {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  root.classList.add(mode);
  root.setAttribute("data-theme", mode === "dark" ? "alpine-dark" : "alpine");
}

export function useThemeMode() {
  const [mode, setMode] = useState<Mode>(() => {
    const saved = localStorage.getItem(THEME_KEY) as Mode | null;
    if (saved) return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  });

  useEffect(() => {
    applyTheme(mode);
    localStorage.setItem(THEME_KEY, mode);
  }, [mode]);

  const toggle = useCallback(
    () => setMode((m) => (m === "dark" ? "light" : "dark")),
    [],
  );
  return { mode, setMode, toggle };
}

/** Coarse device class used for banner/popup targeting. */
export function useDevice(): "desktop" | "mobile" {
  const [device, setDevice] = useState<"desktop" | "mobile">(() =>
    window.matchMedia("(max-width: 767px)").matches ? "mobile" : "desktop",
  );
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const onChange = () => setDevice(mq.matches ? "mobile" : "desktop");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return device;
}

const VISITOR_KEY = "svaneti-visitor";
/** "new" on first ever visit, "returning" afterwards. */
export function getVisitorType(): "new" | "returning" {
  const seen = localStorage.getItem(VISITOR_KEY);
  if (!seen) {
    localStorage.setItem(VISITOR_KEY, String(Date.now()));
    return "new";
  }
  return "returning";
}
