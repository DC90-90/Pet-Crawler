import { forwardRef } from "react";
import { Link, useParams } from "react-router-dom";
import type { LinkProps } from "react-router-dom";
import { SUPPORTED_LANGS } from "@/i18n";
import type { Lang } from "./types";

export function useLang(): Lang {
  const { lang } = useParams();
  return (SUPPORTED_LANGS.includes(lang as never) ? lang : "en") as Lang;
}

/** Prefix an app-relative path with the active language segment. */
export function useLangHref() {
  const lang = useLang();
  return (href: string) => {
    if (!href || href.startsWith("http") || href.startsWith("#")) return href;
    if (href.startsWith("/admin")) return href;
    const clean = href.startsWith("/") ? href : `/${href}`;
    return `/${lang}${clean === "/" ? "" : clean}`;
  };
}

/** Router Link that automatically carries the active language prefix. */
export const LangLink = forwardRef<HTMLAnchorElement, LinkProps & { to: string }>(
  function LangLink({ to, ...props }, ref) {
    const langHref = useLangHref();
    return <Link ref={ref} to={langHref(to)} {...props} />;
  },
);
