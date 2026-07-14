import { useTranslation } from "react-i18next";
import { usePage, useSettings } from "@/lib/queries";
import { useLang } from "@/lib/nav";
import { tt } from "@/i18n";
import { SectionRenderer } from "@/components/content/sections";
import { Seo } from "@/components/site/Seo";
import type { PageSection } from "@/lib/types";

const DEFAULT_SECTIONS: PageSection[] = [
  { id: "hero", type: "hero", order: 0, data: {} },
  {
    id: "trust",
    type: "stats",
    order: 1,
    data: {
      points: [
        { icon: "🗺", title: { en: "Local knowledge" }, text: { en: "Born in Mestia, guiding in Svaneti." } },
        { icon: "🧭", title: { en: "Flexible private tours" }, text: { en: "Journeys shaped around your pace." } },
        { icon: "🏔", title: { en: "Mountains & villages" }, text: { en: "From glaciers to Svan towers." } },
        { icon: "🤝", title: { en: "Cultural experiences" }, text: { en: "Food, towers and living traditions." } },
      ],
    },
  },
  { id: "tours", type: "tourGrid", order: 2, data: { featuredOnly: true, limit: 6 } },
  { id: "dest", type: "destinationGrid", order: 3, data: {} },
  { id: "seasonal", type: "seasonalCards", order: 4, data: {} },
  { id: "map", type: "map", order: 5, data: {} },
  { id: "video", type: "video", order: 6, data: {} },
  { id: "gallery", type: "gallery", order: 7, data: {} },
  { id: "offers", type: "offers", order: 8, data: {} },
  { id: "testimonials", type: "testimonials", order: 9, data: {} },
  { id: "guide", type: "faq", order: 10, data: {} },
  { id: "cta", type: "cta", order: 11, data: {} },
];

export function Component() {
  const { data: page } = usePage("home");
  const { data: settings } = useSettings();
  const lang = useLang();
  const { t } = useTranslation();

  const sections =
    page?.sections && page.sections.length
      ? [...page.sections].sort((a, b) => a.order - b.order)
      : DEFAULT_SECTIONS;

  return (
    <>
      <Seo
        title={`${settings?.brandName ?? t("brand")} — ${tt(settings?.tagline, lang) || "Mestia & Ushguli"}`}
        description={tt(settings?.tagline, lang)}
        canonicalPath={`/${lang}`}
        jsonLd={{
          "@context": "https://schema.org",
          "@type": "TravelAgency",
          name: settings?.brandName ?? "Svaneti with Georgie",
          areaServed: "Upper Svaneti, Georgia",
        }}
      />
      {sections.map((s) => (
        <SectionRenderer key={s.id} section={s} />
      ))}
    </>
  );
}
