import { useEffect } from "react";
import { Outlet, useParams, Navigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SUPPORTED_LANGS, applyDirection } from "@/i18n";

/** Validates the :lang segment, activates it in i18next, and syncs text direction. */
export function LangLayout() {
  const { lang } = useParams();
  const { i18n } = useTranslation();
  const valid = SUPPORTED_LANGS.includes(lang as never);

  useEffect(() => {
    if (valid && lang && i18n.language !== lang) {
      void i18n.changeLanguage(lang);
    }
    if (valid && lang) applyDirection(lang);
  }, [lang, valid, i18n]);

  if (!valid) return <Navigate to="/en" replace />;
  return <Outlet />;
}
