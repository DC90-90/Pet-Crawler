import { useEffect } from "react";
import { SUPPORTED_LANGS } from "@/i18n";

interface SeoProps {
  title?: string;
  description?: string;
  canonicalPath?: string;
  ogImage?: string;
  noindex?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  jsonLd?: Record<string, any> | Record<string, any>[];
}

function setMeta(attr: "name" | "property", key: string, content?: string) {
  if (!content) return;
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

/**
 * Client-side head management for the SPA. In production the FastAPI SSR shell
 * injects route-specific tags server-side for crawlers; this keeps the client
 * in sync and covers SPA navigation.
 */
export function Seo({ title, description, canonicalPath, ogImage, noindex, jsonLd }: SeoProps) {
  useEffect(() => {
    if (title) document.title = title;
    setMeta("name", "description", description);
    setMeta("property", "og:title", title);
    setMeta("property", "og:description", description);
    setMeta("property", "og:image", ogImage);
    setMeta("name", "twitter:card", "summary_large_image");
    setMeta("name", "robots", noindex ? "noindex,nofollow" : "index,follow");

    const base = import.meta.env.VITE_PUBLIC_SITE_URL || window.location.origin;
    const path = canonicalPath ?? window.location.pathname;

    const upsertLink = (rel: string, href: string, hreflang?: string) => {
      const sel = hreflang
        ? `link[rel="${rel}"][hreflang="${hreflang}"]`
        : `link[rel="${rel}"]:not([hreflang])`;
      let el = document.head.querySelector<HTMLLinkElement>(sel);
      if (!el) {
        el = document.createElement("link");
        el.setAttribute("rel", rel);
        if (hreflang) el.setAttribute("hreflang", hreflang);
        document.head.appendChild(el);
      }
      el.setAttribute("href", href);
    };
    upsertLink("canonical", `${base}${path}`);
    // hreflang alternates for supported languages
    const stripped = path.replace(/^\/(en|ka|ar)/, "");
    SUPPORTED_LANGS.forEach((l) => upsertLink("alternate", `${base}/${l}${stripped}`, l));

    // JSON-LD structured data
    const id = "route-jsonld";
    document.getElementById(id)?.remove();
    if (jsonLd) {
      const script = document.createElement("script");
      script.type = "application/ld+json";
      script.id = id;
      script.textContent = JSON.stringify(jsonLd);
      document.head.appendChild(script);
    }
  }, [title, description, canonicalPath, ogImage, noindex, jsonLd]);

  return null;
}
