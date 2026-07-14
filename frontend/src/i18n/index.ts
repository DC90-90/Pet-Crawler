import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import en from "./locales/en.json";
import ka from "./locales/ka.json";
import ar from "./locales/ar.json";
import type { Lang, LocalizedText } from "@/lib/types";

export const SUPPORTED_LANGS: Lang[] = ["en", "ka", "ar"];
export const RTL_LANGS: Lang[] = ["ar"];

export function isRtl(lang: string): boolean {
  return RTL_LANGS.includes(lang.split("-")[0] as Lang);
}

/** Pick a localized string with graceful English fallback. */
export function tt(value: LocalizedText | undefined, lang: string): string {
  if (!value) return "";
  const base = lang.split("-")[0] as Lang;
  return value[base] || value.en || "";
}

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, ka: { translation: ka }, ar: { translation: ar } },
    fallbackLng: "en",
    supportedLngs: SUPPORTED_LANGS,
    nonExplicitSupportedLngs: true,
    interpolation: { escapeValue: false },
    detection: {
      order: ["path", "localStorage", "navigator"],
      lookupFromPathIndex: 0,
      caches: ["localStorage"],
    },
  });

/** Keep <html> lang/dir in sync with the active language (RTL for Arabic). */
export function applyDirection(lang: string): void {
  const rtl = isRtl(lang);
  document.documentElement.lang = lang;
  document.documentElement.dir = rtl ? "rtl" : "ltr";
}

i18n.on("languageChanged", applyDirection);
applyDirection(i18n.language || "en");

export default i18n;
